from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from datetime import datetime

from app.database import get_db
from app.models.group import Group
from app.models.order import Order
from app.models.store import CategoryType
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/home")
async def home(request: Request, db: Session = Depends(get_db)):
    """首頁 - 團列表"""
    user = await get_current_user(request, db)
    
    now = datetime.utcnow()
    
    # 開放中的飲料團（eager load orders 和 store）
    drink_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.DRINK,
        Group.is_closed == False,
        Group.deadline > now,
    ).order_by(Group.deadline.asc()).all()
    
    # 開放中的訂餐團
    meal_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.MEAL,
        Group.is_closed == False,
        Group.deadline > now,
    ).order_by(Group.deadline.asc()).all()
    
    # 開放中的團購團（新類型，可能不存在）
    try:
        groupbuy_groups = db.query(Group).options(
            joinedload(Group.store),
            joinedload(Group.owner),
            joinedload(Group.orders)
        ).filter(
            Group.category == CategoryType.GROUP_BUY,
            Group.is_closed == False,
            Group.deadline > now,
        ).order_by(Group.deadline.asc()).all()
    except Exception:
        groupbuy_groups = []
    
    # 已截止的團（最近 10 個）
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner)
    ).filter(
        or_(Group.is_closed == True, Group.deadline <= now)
    ).order_by(Group.deadline.desc()).limit(10).all()
    
    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "now": now,
    })


@router.get("/my/groups")
async def my_groups(request: Request, db: Session = Depends(get_db)):
    """我參與過的團單"""
    user = await get_current_user(request, db)
    
    # 我開的團 + 我有下單的團
    my_group_ids = db.query(Order.group_id).filter(Order.user_id == user.id).distinct()
    
    groups = db.query(Group).filter(
        or_(
            Group.owner_id == user.id,
            Group.id.in_(my_group_ids)
        )
    ).order_by(Group.created_at.desc()).all()
    
    return templates.TemplateResponse("my_groups.html", {
        "request": request,
        "user": user,
        "groups": groups,
    })


@router.get("/profile")
async def profile_page(request: Request, db: Session = Depends(get_db)):
    """個人資料頁面"""
    user = await get_current_user(request, db)
    
    # 統計資料
    order_count = db.query(Order).filter(Order.user_id == user.id).count()
    group_count = db.query(Group).filter(Group.owner_id == user.id).count()
    
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "order_count": order_count,
        "group_count": group_count,
    })


@router.post("/profile")
async def update_profile(
    request: Request,
    nickname: str = Form(...),
    db: Session = Depends(get_db),
):
    """更新個人資料"""
    from app.models.user import User
    
    user = await get_current_user(request, db)
    
    # 更新暱稱（系統顯示名）
    user.nickname = nickname.strip() if nickname else None
    db.commit()
    
    return RedirectResponse(url="/profile?success=1", status_code=302)
