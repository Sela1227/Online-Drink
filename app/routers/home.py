from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from datetime import datetime, timedelta

from app.database import get_db
from app.models.group import Group
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import CategoryType, Store
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_hot_items(db: Session, limit: int = 10):
    """取得全站熱門品項（最近 30 天）"""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    hot_items = db.query(
        OrderItem.item_name,
        Store.name.label('store_name'),
        Store.logo_url.label('store_logo'),
        func.sum(OrderItem.quantity).label('total_qty'),
    ).join(Order).join(Group).join(Store).filter(
        Order.status == OrderStatus.SUBMITTED,
        Order.created_at >= thirty_days_ago,
    ).group_by(
        OrderItem.item_name,
        Store.name,
        Store.logo_url,
    ).order_by(
        func.sum(OrderItem.quantity).desc()
    ).limit(limit).all()
    
    return hot_items


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
        db.rollback()
        groupbuy_groups = []
    
    # 已截止的團（最近 10 個）
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner)
    ).filter(
        or_(Group.is_closed == True, Group.deadline <= now)
    ).order_by(Group.deadline.desc()).limit(10).all()
    
    # 超夯清單（全站熱門）
    hot_items = get_hot_items(db, limit=10)
    
    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "hot_items": hot_items,
        "now": now,
    })


@router.get("/home/groups")
async def home_groups_partial(request: Request, db: Session = Depends(get_db)):
    """首頁團單列表（HTMX partial）"""
    user = await get_current_user(request, db)
    
    now = datetime.utcnow()
    
    # 開放中的飲料團
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
    
    # 開放中的團購團
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
        db.rollback()
        groupbuy_groups = []
    
    # 已截止的團（最近 10 個）
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner)
    ).filter(
        or_(Group.is_closed == True, Group.deadline <= now)
    ).order_by(Group.deadline.desc()).limit(10).all()
    
    # 超夯清單
    hot_items = get_hot_items(db, limit=10)
    
    return templates.TemplateResponse("partials/home_groups.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "hot_items": hot_items,
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


@router.get("/welcome")
async def welcome_page(request: Request, db: Session = Depends(get_db)):
    """首次登入歡迎頁面"""
    user = await get_current_user(request, db)
    
    return templates.TemplateResponse("welcome.html", {
        "request": request,
        "user": user,
    })


@router.post("/welcome")
async def complete_welcome(
    request: Request,
    nickname: str = Form(""),
    db: Session = Depends(get_db),
):
    """完成首次設定"""
    user = await get_current_user(request, db)
    
    # 設定暱稱（空白則用 LINE 名稱，但標記為已設定）
    nickname = nickname.strip()
    if nickname:
        user.nickname = nickname
    else:
        # 使用 LINE 名稱，但設定為相同值表示已完成設定
        user.nickname = user.display_name
    
    db.commit()
    
    return RedirectResponse(url="/home", status_code=302)


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
