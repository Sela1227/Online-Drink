from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.group import Group
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import CategoryType, Store
from app.models.user import SystemSetting
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# 加入台北時區過濾器
def to_taipei_time(dt):
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time


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
    
    # 使用台北時間（因為 deadline 存的是台北時間）
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
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
    
    # 公告
    settings = db.query(SystemSetting).first()
    announcement = settings.announcement if settings else None
    
    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "hot_items": hot_items,
        "announcement": announcement,
        "now": now,
    })


@router.get("/home/groups")
async def home_groups_partial(request: Request, db: Session = Depends(get_db)):
    """首頁團單列表（HTMX partial）"""
    user = await get_current_user(request, db)
    
    # 使用台北時間（因為 deadline 存的是台北時間）
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
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
    
    # 公告
    settings = db.query(SystemSetting).first()
    announcement = settings.announcement if settings else None
    
    return templates.TemplateResponse("partials/home_groups.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "hot_items": hot_items,
        "announcement": announcement,
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


@router.get("/history")
async def history(request: Request, page: int = 1, db: Session = Depends(get_db)):
    """歷史團單列表"""
    user = await get_current_user(request, db)
    
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
    per_page = 20
    offset = (page - 1) * per_page
    
    # 總數
    total = db.query(Group).filter(
        or_(Group.is_closed == True, Group.deadline <= now)
    ).count()
    
    # 分頁查詢
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        or_(Group.is_closed == True, Group.deadline <= now)
    ).order_by(Group.deadline.desc()).offset(offset).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "groups": closed_groups,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.get("/my-orders")
async def my_orders(request: Request, page: int = 1, db: Session = Depends(get_db)):
    """我的訂單歷史"""
    user = await get_current_user(request, db)
    
    per_page = 20
    offset = (page - 1) * per_page
    
    # 總數
    total = db.query(Order).filter(Order.user_id == user.id).count()
    
    # 分頁查詢
    orders = db.query(Order).options(
        joinedload(Order.group).joinedload(Group.store)
    ).filter(
        Order.user_id == user.id
    ).order_by(Order.created_at.desc()).offset(offset).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return templates.TemplateResponse("my_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.get("/feedback")
async def feedback_page(request: Request, db: Session = Depends(get_db)):
    """問題回報頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import Feedback
    
    # 取得用戶的回報記錄
    feedbacks = db.query(Feedback).filter(
        Feedback.user_id == user.id
    ).order_by(Feedback.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "user": user,
        "feedbacks": feedbacks,
    })


@router.post("/feedback")
async def submit_feedback(
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db)
):
    """提交問題回報"""
    user = await get_current_user(request, db)
    
    from app.models.user import Feedback
    
    feedback = Feedback(
        user_id=user.id,
        content=content.strip()[:1000]  # 限制 1000 字
    )
    db.add(feedback)
    db.commit()
    
    return RedirectResponse(url="/feedback?success=1", status_code=302)


@router.get("/favorites")
async def favorites_page(request: Request, db: Session = Depends(get_db)):
    """收藏店家頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import UserFavorite
    
    favorites = db.query(UserFavorite).options(
        joinedload(UserFavorite.store)
    ).filter(
        UserFavorite.user_id == user.id
    ).order_by(UserFavorite.created_at.desc()).all()
    
    return templates.TemplateResponse("favorites.html", {
        "request": request,
        "user": user,
        "favorites": favorites,
    })


@router.post("/favorites/{store_id}")
async def toggle_favorite(
    request: Request,
    store_id: int,
    db: Session = Depends(get_db)
):
    """切換收藏狀態"""
    user = await get_current_user(request, db)
    
    from app.models.user import UserFavorite
    
    # 檢查是否已收藏
    existing = db.query(UserFavorite).filter(
        UserFavorite.user_id == user.id,
        UserFavorite.store_id == store_id
    ).first()
    
    if existing:
        db.delete(existing)
        db.commit()
        return {"status": "removed"}
    else:
        favorite = UserFavorite(user_id=user.id, store_id=store_id)
        db.add(favorite)
        db.commit()
        return {"status": "added"}
