"""
home.py 更新版

新增功能：
1. 超夯清單（全站熱門品項）
2. 首頁自動刷新（團單到期時局部更新）
"""
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.group import Group
from app.models.store import CategoryType
from app.services.auth import get_current_user
from app.services.stats_service import get_global_hot_items

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# 加入台北時區過濾器
def to_taipei_time(dt):
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    utc_dt = dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time


@router.get("")
async def home(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    
    # ===== 開放中的飲料團 =====
    drink_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.DRINK,
        Group.is_closed == False,
        Group.deadline > now,
    ).order_by(Group.deadline.asc()).all()
    
    # ===== 開放中的餐點團 =====
    meal_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.MEAL,
        Group.is_closed == False,
        Group.deadline > now,
    ).order_by(Group.deadline.asc()).all()
    
    # ===== 開放中的團購團 =====
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
    
    # ===== 已截止區（最近一週內） =====
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        or_(
            Group.is_closed == True,
            Group.deadline <= now
        ),
        or_(
            Group.deadline >= one_week_ago,
            Group.updated_at >= one_week_ago
        )
    ).order_by(Group.deadline.desc()).limit(20).all()
    
    # ===== 歷史區（超過一週，只有管理員能看） =====
    history_groups = []
    if user.is_admin:
        history_groups = db.query(Group).options(
            joinedload(Group.store),
            joinedload(Group.owner),
            joinedload(Group.orders)
        ).filter(
            or_(
                Group.is_closed == True,
                Group.deadline <= now
            ),
            Group.deadline < one_week_ago,
            Group.updated_at < one_week_ago
        ).order_by(Group.deadline.desc()).limit(30).all()
    
    # ===== 超夯清單（全站熱門） =====
    hot_items = get_global_hot_items(db, days=30, limit=10)
    
    # 計算最近的截止時間（用於自動刷新）
    all_open_groups = drink_groups + meal_groups + groupbuy_groups
    next_deadline = None
    if all_open_groups:
        next_deadline = min(g.deadline for g in all_open_groups)
    
    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "history_groups": history_groups,
        "hot_items": hot_items,
        "next_deadline": next_deadline,
    })


@router.get("/groups")
async def home_groups(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """HTMX: 刷新首頁團單列表（自動刷新用）"""
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    
    # ... 與上面相同的查詢邏輯 ...
    drink_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.DRINK,
        Group.is_closed == False,
        Group.deadline > now,
    ).order_by(Group.deadline.asc()).all()
    
    meal_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.MEAL,
        Group.is_closed == False,
        Group.deadline > now,
    ).order_by(Group.deadline.asc()).all()
    
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
    
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        or_(
            Group.is_closed == True,
            Group.deadline <= now
        ),
        or_(
            Group.deadline >= one_week_ago,
            Group.updated_at >= one_week_ago
        )
    ).order_by(Group.deadline.desc()).limit(20).all()
    
    history_groups = []
    if user.is_admin:
        history_groups = db.query(Group).options(
            joinedload(Group.store),
            joinedload(Group.owner),
            joinedload(Group.orders)
        ).filter(
            or_(
                Group.is_closed == True,
                Group.deadline <= now
            ),
            Group.deadline < one_week_ago,
            Group.updated_at < one_week_ago
        ).order_by(Group.deadline.desc()).limit(30).all()
    
    return templates.TemplateResponse("partials/home_groups.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "history_groups": history_groups,
    })
