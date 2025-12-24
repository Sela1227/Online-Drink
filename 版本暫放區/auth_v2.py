from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
import httpx

from app.config import get_settings
from app.models.user import User

settings = get_settings()

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_line_user_profile(access_token: str) -> dict:
    """取得 LINE 使用者資料"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        response.raise_for_status()
        return response.json()


async def exchange_line_token(code: str) -> str:
    """用授權碼換取 access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.line_redirect_uri,
                "client_id": settings.line_channel_id,
                "client_secret": settings.line_channel_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        return response.json()["access_token"]


def get_or_create_user(db: Session, line_user_id: str, display_name: str, picture_url: str | None) -> User:
    """取得或建立使用者"""
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    
    if user:
        # 更新資料
        user.display_name = display_name
        user.picture_url = picture_url
        db.commit()
    else:
        # 建立新使用者
        is_admin = line_user_id == settings.admin_line_user_id
        user = User(
            line_user_id=line_user_id,
            display_name=display_name,
            picture_url=picture_url,
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    return user


async def get_current_user_optional(request: Request, db: Session) -> User | None:
    """取得目前使用者（可選）"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    
    payload = decode_token(token)
    if not payload:
        return None
    
    user_id = payload.get("user_id")
    if not user_id:
        return None
    
    return db.query(User).filter(User.id == user_id).first()


async def get_current_user(request: Request, db: Session) -> User:
    """取得目前使用者（必須登入）"""
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="請先登入")
    return user


async def get_admin_user(request: Request, db: Session) -> User:
    """取得管理者使用者"""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="權限不足")
    return user
