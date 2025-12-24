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
async def login():
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
    return response


@router.get("/callback")
async def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    """LINE 登入回調"""
    try:
        # 驗證 state（防止 CSRF）
        saved_state = request.cookies.get("oauth_state")
        if not saved_state or saved_state != state:
            print(f"⚠️ State 驗證失敗：saved={saved_state}, received={state}")
            return RedirectResponse(url="/?error=invalid_state", status_code=302)
        
        # 換取 access token
        line_access_token = await exchange_line_token(code)
        
        # 取得使用者資料
        profile = await get_line_user_profile(line_access_token)
        
        # 取得或建立使用者
        user = get_or_create_user(
            db=db,
            line_user_id=profile["userId"],
            display_name=profile["displayName"],
            picture_url=profile.get("pictureUrl"),
        )
        
        # 建立 JWT token（包含更多驗證資訊）
        token = create_access_token(
            user_id=user.id,
            line_user_id=profile["userId"]
        )
        
        # 設定 cookie 並導向首頁
        response = RedirectResponse(url="/home", status_code=302)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,  # 7 days（縮短）
            samesite="lax",
            secure=True,
        )
        # 清除 oauth_state cookie
        response.delete_cookie("oauth_state")
        return response
        
    except Exception as e:
        print(f"登入錯誤：{e}")
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
