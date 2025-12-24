from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
import httpx
import secrets

from app.config import get_settings
from app.models.user import User

settings = get_settings()

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7  # 縮短到 7 天
SESSION_TIMEOUT_MINUTES = 30  # 閒置超時時間


def create_access_token(user_id: int, line_user_id: str) -> str:
    """建立 JWT token，包含更多驗證資訊"""
    now = datetime.utcnow()
    to_encode = {
        "user_id": user_id,
        "line_user_id": line_user_id,  # 雙重驗證
        "iat": now,  # 發行時間
        "exp": now + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
        "last_active": now.isoformat(),  # 最後活動時間
        "token_version": secrets.token_hex(8),  # Token 版本
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def check_session_timeout(payload: dict) -> bool:
    """檢查 session 是否已超時"""
    last_active_str = payload.get("last_active")
    if not last_active_str:
        return True  # 舊版 token，視為超時
    
    try:
        last_active = datetime.fromisoformat(last_active_str)
        timeout_delta = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
        return datetime.utcnow() - last_active > timeout_delta
    except:
        return True


def refresh_token_if_needed(payload: dict) -> str | None:
    """如果需要，刷新 token（更新 last_active）"""
    last_active_str = payload.get("last_active")
    if not last_active_str:
        return None
    
    try:
        last_active = datetime.fromisoformat(last_active_str)
        # 每 5 分鐘刷新一次
        if datetime.utcnow() - last_active > timedelta(minutes=5):
            payload["last_active"] = datetime.utcnow().isoformat()
            return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    except:
        pass
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


async def get_current_user_optional(request: Request, db: Session) -> tuple[User | None, str | None]:
    """取得目前使用者（可選）
    
    Returns:
        tuple: (user, new_token) - new_token 如果需要刷新則有值
    """
    token = request.cookies.get("access_token")
    if not token:
        return None, None
    
    payload = decode_token(token)
    if not payload:
        return None, None
    
    # 檢查 session 是否超時
    if check_session_timeout(payload):
        return None, None  # 超時，需重新登入
    
    user_id = payload.get("user_id")
    line_user_id = payload.get("line_user_id")
    
    if not user_id:
        return None, None
    
    user = db.query(User).filter(User.id == user_id).first()
    
    # 雙重驗證：確認 line_user_id 也匹配
    if user and line_user_id and user.line_user_id != line_user_id:
        # line_user_id 不匹配，可能是安全問題！
        print(f"⚠️ 安全警告：user_id={user_id} 的 line_user_id 不匹配")
        return None, None
    
    # 檢查是否需要刷新 token
    new_token = refresh_token_if_needed(payload)
    
    return user, new_token


async def get_current_user(request: Request, db: Session) -> User:
    """取得目前使用者（必須登入）"""
    user, _ = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="請先登入")
    return user


async def get_admin_user(request: Request, db: Session) -> User:
    """取得管理者使用者"""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="權限不足")
    return user
