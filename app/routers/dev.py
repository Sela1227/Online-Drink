"""
開發環境用的模擬登入
僅在 DEBUG=true 時啟用
"""
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.auth import create_access_token

router = APIRouter()
settings = get_settings()


@router.get("/dev/login/{user_id}")
async def dev_login(user_id: int, db: Session = Depends(get_db)):
    """開發用模擬登入（僅 DEBUG 模式）"""
    if not settings.debug:
        return RedirectResponse(url="/", status_code=302)
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/?error=user_not_found", status_code=302)
    
    token = create_access_token({"user_id": user.id})
    
    response = RedirectResponse(url="/home", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=30 * 24 * 60 * 60,
        samesite="lax",
    )
    return response


@router.get("/dev/users")
async def dev_users(db: Session = Depends(get_db)):
    """列出所有使用者（僅 DEBUG 模式）"""
    if not settings.debug:
        return {"error": "Not available in production"}
    
    users = db.query(User).all()
    return {
        "users": [
            {
                "id": u.id,
                "display_name": u.display_name,
                "is_admin": u.is_admin,
                "login_url": f"/dev/login/{u.id}"
            }
            for u in users
        ]
    }
