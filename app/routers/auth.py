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
    state = secrets.token_urlsafe(16)
    
    params = {
        "response_type": "code",
        "client_id": settings.line_channel_id,
        "redirect_uri": settings.line_redirect_uri,
        "state": state,
        "scope": "profile openid",
    }
    
    url = f"https://access.line.me/oauth2/v2.1/authorize?{urlencode(params)}"
    return RedirectResponse(url=url)


@router.get("/callback")
async def callback(code: str, state: str, db: Session = Depends(get_db)):
    """LINE 登入回調"""
    try:
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
        
        # 建立 JWT token
        token = create_access_token({"user_id": user.id})
        
        # 設定 cookie 並導向首頁
        response = RedirectResponse(url="/home?toast=login_success", status_code=302)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            max_age=30 * 24 * 60 * 60,  # 30 days
            samesite="lax",
        )
        return response
        
    except Exception as e:
        # 登入失敗，導回首頁
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
