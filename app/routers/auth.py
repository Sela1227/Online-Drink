from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import urlencode
import secrets
import asyncio
import hashlib
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import get_db
from app.services.auth import (
    exchange_line_token,
    get_line_user_profile,
    get_or_create_user,
    create_access_token,
)

router = APIRouter()
settings = get_settings()


@router.get("/login")
async def login(request: Request, next: str = None):
    """導向 LINE 登入頁面"""
    state = secrets.token_urlsafe(32)  # 加長 state
    
    params = {
        "response_type": "code",
        "client_id": settings.line_channel_id,
        "redirect_uri": settings.line_redirect_uri,
        "state": state,
        "scope": "profile openid",
    }
    
    url = f"https://access.line.me/oauth2/v2.1/authorize?{urlencode(params)}"
    
    # 儲存 state 到 cookie 供 callback 驗證
    response = RedirectResponse(url=url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        max_age=600,  # 10 分鐘有效
        samesite="lax",
        secure=True,
    )
    
    # 儲存 next URL（登入後要跳轉的頁面）
    if next:
        response.set_cookie(
            key="login_next",
            value=next,
            httponly=True,
            max_age=600,
            samesite="lax",
            secure=True,
        )
    
    return response


LOGIN_ATTEMPT_WAIT_SECONDS = 6


def _attempt_key(state: str, code: str) -> str:
    return hashlib.sha256(f"{state}:{code}".encode()).hexdigest()


def _login_response(request: Request, db: Session, user, next_url: str) -> RedirectResponse:
    """發 JWT、寫 cookie、導向（第一次與重複的那一次共用）"""
    from app.services.auth import get_system_token_version
    token = create_access_token(user_id=user.id, line_user_id=user.line_user_id, token_version=get_system_token_version(db))
    response = RedirectResponse(url=next_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,  # 7 days（縮短）
        samesite="lax",
        secure=True,
    )
    response.delete_cookie("oauth_state")
    response.delete_cookie("login_next")
    return response


def _claim_attempt(db: Session, key: str):
    """搶這次登入的處理權。回傳 None＝我是第一個，要真的去跟 LINE 換；否則回傳已存在的那一列。"""
    from app.models.user import LoginAttempt
    db.query(LoginAttempt).filter(LoginAttempt.created_at < datetime.utcnow() - timedelta(minutes=10)).delete(synchronize_session=False)
    db.commit()
    db.add(LoginAttempt(attempt_key=key, status="pending"))
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        return db.query(LoginAttempt).filter(LoginAttempt.attempt_key == key).first()


def _finish_attempt(db: Session, key: str, status: str, user_id: int | None = None, next_url: str | None = None):
    from app.models.user import LoginAttempt
    try:
        db.rollback()
        row = db.query(LoginAttempt).filter(LoginAttempt.attempt_key == key).first()
        if row:
            row.status, row.user_id, row.next_url = status, user_id, next_url
            db.commit()
    except Exception:
        db.rollback()


@router.get("/callback")
async def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    """LINE 登入回調"""
    import logging
    from app.models.user import LoginAttempt, User

    # 設定日誌
    logger = logging.getLogger("auth")
    request_id = secrets.token_hex(4)  # 追蹤用 ID
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(f"[{request_id}] === 登入開始 ===")
    logger.info(f"[{request_id}] IP: {client_ip}")
    logger.info(f"[{request_id}] State received: {state[:8]}...")
    
    # 驗證 state（防止 CSRF）
    saved_state = request.cookies.get("oauth_state")
    logger.info(f"[{request_id}] State saved: {saved_state[:8] if saved_state else 'None'}...")
    if not saved_state or not secrets.compare_digest(saved_state, state):
        logger.warning(f"[{request_id}] ⚠️ State 驗證失敗！saved={saved_state}, received={state}")
        return RedirectResponse(url="/?error=invalid_state", status_code=302)
    logger.info(f"[{request_id}] State 驗證通過")

    # V2.23.1：同一次登入（同 state＋同授權碼）只跟 LINE 換一次；重複送來的那一次等結果沿用
    key = _attempt_key(state, code)
    existing = _claim_attempt(db, key)
    if existing is not None:
        logger.info(f"[{request_id}] 重複的登入回呼（同一組授權碼），等第一次的結果")
        waited = 0.0
        while existing is not None and existing.status == "pending" and waited < LOGIN_ATTEMPT_WAIT_SECONDS:
            await asyncio.sleep(0.2)
            waited += 0.2
            db.expire_all()
            existing = db.query(LoginAttempt).filter(LoginAttempt.attempt_key == key).first()
        if existing is not None and existing.status == "done" and existing.user_id:
            user = db.query(User).filter(User.id == existing.user_id).first()
            if user:
                logger.info(f"[{request_id}] 沿用第一次的登入結果：{user.display_name} (id={user.id})，導向 {existing.next_url}")
                return _login_response(request, db, user, existing.next_url or "/home")
        logger.warning(f"[{request_id}] 第一次的登入沒有成功（{existing.status if existing else '找不到'}），不再重試這組授權碼")
        return RedirectResponse(url="/?error=login_failed", status_code=302)

    try:
        # 換取 access token
        line_access_token = await exchange_line_token(code)
        logger.info(f"[{request_id}] LINE token 取得成功")
        
        # 取得使用者資料
        profile = await get_line_user_profile(line_access_token)
        line_user_id = profile["userId"]
        display_name = profile["displayName"]
        
        logger.info(f"[{request_id}] LINE Profile: user_id={line_user_id[:8]}..., name={display_name}")
        
        # 取得或建立使用者
        user = get_or_create_user(
            db=db,
            line_user_id=line_user_id,
            display_name=display_name,
            picture_url=profile.get("pictureUrl"),
        )
        
        logger.info(f"[{request_id}] DB User: id={user.id}, line_user_id={user.line_user_id[:8]}..., name={user.display_name}")
        
        # 驗證：確保 LINE 回傳的 userId 和資料庫的一致
        if user.line_user_id != line_user_id:
            logger.error(f"[{request_id}] 🚨 嚴重錯誤：line_user_id 不匹配！")
            logger.error(f"[{request_id}] LINE 回傳: {line_user_id}")
            logger.error(f"[{request_id}] DB 記錄: {user.line_user_id}")
            _finish_attempt(db, key, "failed")
            return RedirectResponse(url="/?error=user_mismatch", status_code=302)
        
        # 取得登入後要跳轉的頁面
        next_url = request.cookies.get("login_next") or "/home"
        # 安全檢查：只允許相對路徑
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/home"
        
        # 首次登入（沒設過暱稱）導向歡迎頁面
        if user.nickname is None:
            next_url = "/welcome"
        
        _finish_attempt(db, key, "done", user.id, next_url)
        logger.info(f"[{request_id}] === 登入完成：{display_name} (id={user.id}) ===")
        logger.info(f"[{request_id}] 導向到: {next_url}")
        return _login_response(request, db, user, next_url)
        
    except Exception as e:
        logger.error(f"[{request_id}] 登入錯誤：{e}")
        import traceback
        logger.error(f"[{request_id}] {traceback.format_exc()}")
        _finish_attempt(db, key, "failed")
        return RedirectResponse(url="/?error=login_failed", status_code=302)


@router.post("/logout")
async def logout():
    """登出"""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/logout")
async def logout_get():
    """登出（GET for convenience）"""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.post("/heartbeat")
async def heartbeat(request: Request, db: Session = Depends(get_db)):
    """心跳 API - 更新 session 活動時間"""
    from app.services.auth import get_current_user_optional
    from fastapi.responses import JSONResponse
    
    user, new_token = await get_current_user_optional(request, db)
    if not user:
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    
    # 如果需要刷新 token，回傳新 token
    response = JSONResponse({"status": "ok", "user_id": user.id})
    
    if new_token:
        response.set_cookie(
            key="access_token",
            value=new_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            samesite="lax",
            secure=True,
        )
    
    return response
