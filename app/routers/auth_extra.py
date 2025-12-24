"""
首次登入設定暱稱功能

修改說明：
1. 在 User model 新增 is_first_login 欄位（預設 True）
2. 登入 callback 後檢查是否首次登入
3. 首次登入導向 /auth/welcome 設定暱稱
4. 設定完成後將 is_first_login 設為 False
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/welcome")
async def welcome_page(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    首次登入歡迎頁面
    """
    # 如果不是首次登入，直接導向首頁
    if not getattr(user, 'is_first_login', True):
        return RedirectResponse("/home", status_code=302)
    
    return templates.TemplateResponse("welcome.html", {
        "request": request,
        "user": user,
    })


@router.post("/set-nickname")
async def set_nickname(
    nickname: str = Form(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    設定暱稱並完成首次登入
    """
    if nickname.strip():
        user.nickname = nickname.strip()
    
    # 標記為已完成首次登入
    user.is_first_login = False
    db.commit()
    
    return RedirectResponse("/home", status_code=302)


# ====================================
# 以下是需要加到 User model 的欄位
# ====================================
"""
在 app/models/user.py 的 User class 中加入：

    # 首次登入標記
    is_first_login: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # LINE 原始名稱（用於顯示）
    line_display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

在 auth.py 的 callback 中加入：
    
    # 首次登入檢查
    if user.is_first_login:
        return RedirectResponse("/auth/welcome", status_code=302)
"""
