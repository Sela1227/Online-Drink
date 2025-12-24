"""
home.py 修復版

修復問題：
1. 時間到的團單必須移到已截止區（不管 is_closed 狀態）
2. 只有 deadline > now AND is_closed == False 的才顯示在開放區
"""
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.group import Group
from app.models.store import Store, CategoryType
from app.models.order import Order, OrderStatus
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# ===== 註冊台北時區過濾器 =====
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


@router.get("")
async def home(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    
    # ===== 開放中的飲料團 =====
    # 條件：未手動關閉 AND 未過期
    drink_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.DRINK,
        Group.is_closed == False,
        Group.deadline > now,  # 必須未過期
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
    
    # ===== 已截止區（最近一週） =====
    # 條件：(手動關閉 OR 已過期) AND 最近一週內
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        or_(
            Group.is_closed == True,
            Group.deadline <= now  # 時間到就是截止
        ),
        or_(
            Group.deadline >= one_week_ago,
            Group.updated_at >= one_week_ago
        )
    ).order_by(Group.deadline.desc()).limit(20).all()
    
    # ===== 歷史區（超過一週，管理員可見） =====
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
    
    # 公告
    try:
        from app.models.system import SystemSetting
        announcement_setting = db.query(SystemSetting).filter(
            SystemSetting.key == "announcement"
        ).first()
        announcement = announcement_setting.value if announcement_setting else ""
    except:
        announcement = ""
    
    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "history_groups": history_groups,
        "announcement": announcement,
    })


@router.get("/groups")
async def home_groups(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """HTMX: 刷新首頁團單列表"""
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
    
    # ===== 已截止區 =====
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
    
    # ===== 歷史區 =====
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
