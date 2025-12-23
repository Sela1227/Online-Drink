from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from datetime import datetime
import qrcode
import io
import base64

from app.config import get_settings
from app.database import get_db
from app.models.group import Group
from app.models.store import Store, CategoryType
from app.models.menu import Menu, MenuItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User, UserPreset
from app.services.auth import get_current_user
from app.services.export_service import generate_order_text, generate_payment_text

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def get_quick_selections(db: Session, user_id: int, store_id: int, menu_id: int):
    """取得快選品項"""
    
    # 1. 我的常點 Top 5 (該店家)
    my_frequent_query = db.query(
        OrderItem.menu_item_id,
        MenuItem.name,
        MenuItem.price,
        func.sum(OrderItem.quantity).label('total_qty')
    ).join(
        MenuItem, OrderItem.menu_item_id == MenuItem.id
    ).join(
        Order, OrderItem.order_id == Order.id
    ).join(
        Group, Order.group_id == Group.id
    ).filter(
        Order.user_id == user_id,
        Group.store_id == store_id,
        Order.status == OrderStatus.SUBMITTED
    ).group_by(
        OrderItem.menu_item_id, MenuItem.name, MenuItem.price
    ).order_by(
        desc('total_qty')
    ).limit(5).all()
    
    # 2. 我的最近 5 項 (該店家) - 使用 subquery 來取得每個品項最後一次點的時間
    # 直接查詢最近的訂單品項，然後在 Python 中去重
    recent_items_query = db.query(
        OrderItem.menu_item_id,
        MenuItem.name,
        MenuItem.price,
        Order.created_at
    ).join(
        MenuItem, OrderItem.menu_item_id == MenuItem.id
    ).join(
        Order, OrderItem.order_id == Order.id
    ).join(
        Group, Order.group_id == Group.id
    ).filter(
        Order.user_id == user_id,
        Group.store_id == store_id,
        Order.status == OrderStatus.SUBMITTED
    ).order_by(
        desc(Order.created_at)
    ).limit(20).all()
    
    # 在 Python 中去重，保留每個品項第一次出現的（最近的）
    seen_items = set()
    my_recent = []
    for item in recent_items_query:
        if item[0] not in seen_items and len(my_recent) < 5:
            seen_items.add(item[0])
            my_recent.append({'id': item[0], 'name': item[1], 'price': item[2]})
    
    # 3. 店家熱門 Top 5 (所有人)
    store_popular_query = db.query(
        OrderItem.menu_item_id,
        MenuItem.name,
        MenuItem.price,
        func.sum(OrderItem.quantity).label('total_qty')
    ).join(
        MenuItem, OrderItem.menu_item_id == MenuItem.id
    ).join(
        Order, OrderItem.order_id == Order.id
    ).join(
        Group, Order.group_id == Group.id
    ).filter(
        Group.store_id == store_id,
        Order.status == OrderStatus.SUBMITTED
    ).group_by(
        OrderItem.menu_item_id, MenuItem.name, MenuItem.price
    ).order_by(
        desc('total_qty')
    ).limit(5).all()
    
    return {
        'my_frequent': [{'id': r[0], 'name': r[1], 'price': r[2]} for r in my_frequent_query],
        'my_recent': my_recent,
        'store_popular': [{'id': r[0], 'name': r[1], 'price': r[2]} for r in store_popular_query],
    }


@router.get("/new")
async def new_group_page(request: Request, db: Session = Depends(get_db)):
    """開團頁面"""
    user = await get_current_user(request, db)
    
    # 取得啟用中的店家
    stores = db.query(Store).filter(Store.is_active == True).all()
    
    # 取得使用者時間預設
    user_preset = db.query(UserPreset).filter(UserPreset.user_id == user.id).first()
    time_presets = user_preset.time_presets if user_preset and user_preset.time_presets else [
        "30分鐘後", "1小時後", "今天 12:00", "今天 17:00", "明天 12:00"
    ]
    
    return templates.TemplateResponse("group_new.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "time_presets": time_presets,
    })


@router.post("")
async def create_group(
    request: Request,
    store_id: int = Form(...),
    name: str = Form(...),
    deadline: str = Form(...),
    default_sugar: str = Form(None),
    default_ice: str = Form(None),
    lock_sugar: bool = Form(False),
    lock_ice: bool = Form(False),
    db: Session = Depends(get_db),
):
    """建立團單"""
    user = await get_current_user(request, db)
    
    # 取得店家
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 取得啟用中的菜單
    menu = db.query(Menu).filter(
        Menu.store_id == store_id,
        Menu.is_active == True
    ).first()
    if not menu:
        raise HTTPException(status_code=400, detail="該店家尚無啟用的菜單")
    
    # 解析截止時間
    try:
        deadline_dt = datetime.fromisoformat(deadline)
    except ValueError:
        raise HTTPException(status_code=400, detail="截止時間格式錯誤")
    
    # 建立團單
    group = Group(
        store_id=store_id,
        menu_id=menu.id,
        owner_id=user.id,
        name=name,
        category=store.category,
        deadline=deadline_dt,
        default_sugar=default_sugar if store.category == CategoryType.DRINK else None,
        default_ice=default_ice if store.category == CategoryType.DRINK else None,
        lock_sugar=lock_sugar if store.category == CategoryType.DRINK else False,
        lock_ice=lock_ice if store.category == CategoryType.DRINK else False,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    
    return RedirectResponse(url=f"/groups/{group.id}", status_code=302)


@router.get("/{group_id}")
async def group_page(group_id: int, request: Request, db: Session = Depends(get_db)):
    """團單頁面"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得已結單的訂單（訂單牆）- eager load 關聯
    submitted_orders = db.query(Order).options(
        joinedload(Order.user),
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).all()
    
    # 取得我的訂單 - eager load 關聯
    my_order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).first()
    
    # 統計未結單人數
    pending_count = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status.in_([OrderStatus.DRAFT, OrderStatus.EDITING])
    ).count()
    
    # 取得菜單品項（含分類）
    menu = group.menu
    
    # 取得快選品項
    quick_selections = get_quick_selections(db, user.id, group.store_id, group.menu_id)
    
    return templates.TemplateResponse("group.html", {
        "request": request,
        "user": user,
        "group": group,
        "store": group.store,
        "menu": menu,
        "submitted_orders": submitted_orders,
        "my_order": my_order,
        "pending_count": pending_count,
        "is_owner": group.owner_id == user.id,
        "is_open": group.is_open,
        "quick_selections": quick_selections,
    })


@router.post("/{group_id}/close")
async def close_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    """提前截止團單"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以截止團單")
    
    group.is_closed = True
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)


@router.get("/{group_id}/qrcode")
async def group_qrcode(group_id: int, db: Session = Depends(get_db)):
    """產生 QR Code"""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    url = f"{settings.base_url}/groups/{group_id}"
    
    # 產生 QR Code
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # 轉為 base64
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()
    
    return HTMLResponse(
        content=f'<img src="data:image/png;base64,{img_str}" alt="QR Code" />',
        status_code=200,
    )


@router.get("/{group_id}/copy")
async def copy_group_page(group_id: int, request: Request, db: Session = Depends(get_db)):
    """複製開團頁面"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得店家選項
    stores = db.query(Store).filter(Store.is_active == True).all()
    
    # 取得使用者時間預設
    user_preset = db.query(UserPreset).filter(UserPreset.user_id == user.id).first()
    time_presets = user_preset.time_presets if user_preset and user_preset.time_presets else [
        "30分鐘後", "1小時後", "今天 12:00", "今天 17:00", "明天 12:00"
    ]
    
    return templates.TemplateResponse("group_new.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "time_presets": time_presets,
        "copy_from": group,  # 帶入預設值
    })


@router.get("/{group_id}/export/order")
async def export_order(group_id: int, request: Request, db: Session = Depends(get_db)):
    """匯出點餐文字"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有團主或管理者可以匯出
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以匯出")
    
    text = generate_order_text(db, group)
    
    return templates.TemplateResponse("export.html", {
        "request": request,
        "user": user,
        "group": group,
        "title": "點餐文字",
        "text": text,
    })


@router.get("/{group_id}/export/payment")
async def export_payment(group_id: int, request: Request, db: Session = Depends(get_db)):
    """匯出收款文字"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有團主或管理者可以匯出
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以匯出")
    
    text = generate_payment_text(db, group)
    
    return templates.TemplateResponse("export.html", {
        "request": request,
        "user": user,
        "group": group,
        "title": "收款文字",
        "text": text,
    })


@router.post("/presets/time")
async def save_time_presets(
    request: Request,
    presets: str = Form(...),
    db: Session = Depends(get_db),
):
    """儲存時間預設"""
    user = await get_current_user(request, db)
    
    # 解析預設值（逗號分隔）
    preset_list = [p.strip() for p in presets.split(',') if p.strip()][:5]
    
    # 取得或建立使用者預設
    user_preset = db.query(UserPreset).filter(UserPreset.user_id == user.id).first()
    
    if user_preset:
        user_preset.time_presets = preset_list
    else:
        user_preset = UserPreset(
            user_id=user.id,
            time_presets=preset_list,
        )
        db.add(user_preset)
    
    db.commit()
    
    return RedirectResponse(url="/groups/new", status_code=302)
