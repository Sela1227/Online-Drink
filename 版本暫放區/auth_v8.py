from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import urlencode
import secrets

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


@router.get("/callback")
async def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    """LINE 登入回調"""
    import logging
    from datetime import datetime
    
    # 設定日誌
    logger = logging.getLogger("auth")
    request_id = secrets.token_hex(4)  # 追蹤用 ID
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(f"[{request_id}] === 登入開始 ===")
    logger.info(f"[{request_id}] IP: {client_ip}")
    logger.info(f"[{request_id}] State received: {state[:8]}...")
    
    try:
        # 驗證 state（防止 CSRF）
        saved_state = request.cookies.get("oauth_state")
        logger.info(f"[{request_id}] State saved: {saved_state[:8] if saved_state else 'None'}...")
        
        if not saved_state or saved_state != state:
            logger.warning(f"[{request_id}] ⚠️ State 驗證失敗！saved={saved_state}, received={state}")
            return RedirectResponse(url="/?error=invalid_state", status_code=302)
        
        logger.info(f"[{request_id}] State 驗證通過")
        
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
            return RedirectResponse(url="/?error=user_mismatch", status_code=302)
        
        # 建立 JWT token（包含更多驗證資訊）
        token = create_access_token(
            user_id=user.id,
            line_user_id=line_user_id
        )
        
        logger.info(f"[{request_id}] Token 建立成功，導向首頁")
        logger.info(f"[{request_id}] === 登入完成：{display_name} (id={user.id}) ===")
        
        # 取得登入後要跳轉的頁面
        next_url = request.cookies.get("login_next") or "/home"
        # 安全檢查：只允許相對路徑
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/home"
        
        logger.info(f"[{request_id}] 導向到: {next_url}")
        
        # 設定 cookie 並導向
        response = RedirectResponse(url=next_url, status_code=302)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,  # 7 days（縮短）
            samesite="lax",
            secure=True,
        )
        # 清除 oauth_state 和 login_next cookie
        response.delete_cookie("oauth_state")
        response.delete_cookie("login_next")
        return response
        
    except Exception as e:
        logger.error(f"[{request_id}] 登入錯誤：{e}")
        import traceback
        logger.error(f"[{request_id}] {traceback.format_exc()}")
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
