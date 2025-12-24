"""
auth.py - 認證服務
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.config import get_settings

settings = get_settings()

SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """建立 JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """驗證 JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """取得當前登入用戶"""
    token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"}
        )
    
    # 移除 Bearer 前綴
    if token.startswith("Bearer "):
        token = token[7:]
    
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"}
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"}
        )
    
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"}
        )
    
    # 更新最後活動時間
    user.last_active_at = datetime.utcnow()
    db.commit()
    
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """取得當前用戶（可選，未登入返回 None）"""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def get_admin_user(request: Request, db: Session = Depends(get_db)) -> User:
    """取得管理員用戶"""
    user = get_current_user(request, db)
    
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
        )
    
    return user


def get_or_create_user(
    db: Session,
    line_id: str,
    display_name: str,
    picture_url: Optional[str] = None
) -> User:
    """取得或建立用戶"""
    user = db.query(User).filter(User.line_id == line_id).first()
    
    if user:
        # 更新用戶資料
        user.display_name = display_name
        if picture_url:
            user.picture_url = picture_url
        user.last_active_at = datetime.utcnow()
        db.commit()
        return user
    
    # 建立新用戶
    user = User(
        line_id=line_id,
        display_name=display_name,
        picture_url=picture_url,
        last_active_at=datetime.utcnow()
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user
