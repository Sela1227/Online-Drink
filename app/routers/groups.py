from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import qrcode
import io
import base64

from app.config import get_settings
from app.database import get_db
from app.models.group import Group
from app.models.store import Store, StoreBranch, CategoryType
from app.models.menu import Menu, MenuItem
from app.models.order import Order, OrderItem, OrderStatus
from app.services.auth import get_current_user, get_current_user_optional
from app.services.export_service import generate_order_text, generate_payment_text

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

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


@router.get("/new")
async def new_group_page(request: Request, db: Session = Depends(get_db)):
    """開團頁面"""
    user = await get_current_user(request, db)
    
    # 取得啟用中的店家（含分店）
    stores = db.query(Store).options(
        joinedload(Store.branches)
    ).filter(Store.is_active == True).all()
    
    return templates.TemplateResponse("group_new.html", {
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.post("")
async def create_group(
    request: Request,
    store_id: int = Form(...),
    name: str = Form(...),
    deadline: str = Form(...),
    note: str = Form(None),
    branch_id: int = Form(None),
    delivery_fee: float = Form(None),
    default_sugar: str = Form(None),
    default_ice: str = Form(None),
    lock_sugar: bool = Form(False),
    lock_ice: bool = Form(False),
    db: Session = Depends(get_db),
):
    """建立團單"""
    from decimal import Decimal
    
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
        branch_id=branch_id if branch_id else None,
        name=name,
        note=note.strip() if note else None,
        category=store.category,
        deadline=deadline_dt,
        delivery_fee=Decimal(str(delivery_fee)) if delivery_fee and delivery_fee > 0 else None,
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
    from app.models.user import User
    
    user, new_token = await get_current_user_optional(request, db)
    
    # 未登入：導向登入頁面，登入後回來
    if not user:
        next_url = f"/groups/{group_id}"
        return RedirectResponse(
            url=f"/auth/login?next={quote(next_url)}", 
            status_code=302
        )
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得已結單的訂單（訂單牆）- 使用 eager loading
    submitted_orders = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).options(
        joinedload(Order.user),
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).all()
    
    # 取得我的訂單 - 使用 eager loading
    my_order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).first()
    
    # 統計未結單人數
    pending_count = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status.in_([OrderStatus.DRAFT, OrderStatus.EDITING])
    ).count()
    
    # 取得未結單的訂單（用於催單）
    pending_orders = []
    if group.owner_id == user.id or user.is_admin:
        pending_orders = db.query(Order).filter(
            Order.group_id == group_id,
            Order.status.in_([OrderStatus.DRAFT, OrderStatus.EDITING])
        ).options(
            joinedload(Order.user),
            joinedload(Order.items)
        ).all()
        # 只保留有品項的訂單
        pending_orders = [o for o in pending_orders if len(o.items) > 0]
    
    # 取得用戶在同店家的上次訂單（用於複製上次訂單）
    last_order = None
    last_order_items = []
    previous_order = db.query(Order).join(Group).filter(
        Group.store_id == group.store_id,
        Order.user_id == user.id,
        Order.status == OrderStatus.SUBMITTED,
        Order.group_id != group_id  # 排除當前團
    ).order_by(Order.created_at.desc()).first()
    
    if previous_order:
        last_order = previous_order
        last_order_items = previous_order.items
    
    # 取得用戶在同店家的常點品項（統計前 5 名）
    from sqlalchemy import func
    favorite_items = db.query(
        OrderItem.item_name,
        OrderItem.menu_item_id,
        func.count(OrderItem.id).label('count')
    ).join(Order).join(Group).filter(
        Group.store_id == group.store_id,
        Order.user_id == user.id,
        Order.status == OrderStatus.SUBMITTED
    ).group_by(OrderItem.item_name, OrderItem.menu_item_id).order_by(
        func.count(OrderItem.id).desc()
    ).limit(5).all()
    
    # 取得菜單品項（含分類）
    menu = group.menu
    
    # 取得所有用戶（用於轉移團主）
    all_users = []
    if group.owner_id == user.id or user.is_admin:
        all_users = db.query(User).order_by(User.display_name).all()
    
    # 檢查是否已收藏此店家
    from app.models.user import UserFavorite
    is_favorited = db.query(UserFavorite).filter(
        UserFavorite.user_id == user.id,
        UserFavorite.store_id == group.store_id
    ).first() is not None
    
    return templates.TemplateResponse("group.html", {
        "request": request,
        "user": user,
        "group": group,
        "store": group.store,
        "menu": menu,
        "submitted_orders": submitted_orders,
        "my_order": my_order,
        "pending_count": pending_count,
        "pending_orders": pending_orders,
        "last_order": last_order,
        "last_order_items": last_order_items,
        "favorite_items": favorite_items,
        "is_owner": group.owner_id == user.id,
        "is_admin": user.is_admin,
        "is_open": group.is_open,
        "all_users": all_users,
        "is_favorited": is_favorited,
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


@router.post("/{group_id}/delete")
async def delete_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除團單"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主或管理員可以刪除團單")
    
    # 刪除相關訂單和訂單項目
    orders = db.query(Order).filter(Order.group_id == group_id).all()
    for order in orders:
        for item in order.items:
            # 刪除訂單項目的選項
            for opt in item.selected_options:
                db.delete(opt)
            db.delete(item)
        db.delete(order)
    
    db.delete(group)
    db.commit()
    
    return RedirectResponse(url="/home", status_code=302)


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


@router.post("/{group_id}/orders/copy-last")
async def copy_last_order(group_id: int, request: Request, db: Session = Depends(get_db)):
    """複製上次訂單到購物車"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    if not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    
    # 找到上次在同店家的訂單
    previous_order = db.query(Order).join(Group).filter(
        Group.store_id == group.store_id,
        Order.user_id == user.id,
        Order.status == OrderStatus.SUBMITTED,
        Order.group_id != group_id
    ).order_by(Order.created_at.desc()).first()
    
    if not previous_order:
        raise HTTPException(status_code=404, detail="找不到上次訂單")
    
    # 取得或建立當前訂單
    my_order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id
    ).first()
    
    if not my_order:
        my_order = Order(
            group_id=group_id,
            user_id=user.id,
            status=OrderStatus.DRAFT,
        )
        db.add(my_order)
        db.flush()
    elif my_order.status == OrderStatus.SUBMITTED:
        # 已結單，先改為編輯狀態
        my_order.status = OrderStatus.EDITING
    
    # 複製品項
    for old_item in previous_order.items:
        # 檢查品項是否還在菜單上
        menu_item = db.query(MenuItem).filter(
            MenuItem.id == old_item.menu_item_id,
            MenuItem.menu_id == group.menu_id
        ).first()
        
        if menu_item:  # 品項還存在才複製
            new_item = OrderItem(
                order_id=my_order.id,
                menu_item_id=old_item.menu_item_id,
                item_name=old_item.item_name,
                size=old_item.size,
                price=old_item.price,
                sugar=old_item.sugar,
                ice=old_item.ice,
                quantity=old_item.quantity,
                note=old_item.note,
            )
            db.add(new_item)
    
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)


@router.get("/{group_id}/copy")
async def copy_group_page(group_id: int, request: Request, db: Session = Depends(get_db)):
    """複製開團頁面"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得店家選項
    stores = db.query(Store).filter(Store.is_active == True).all()
    
    return templates.TemplateResponse("group_new.html", {
        "request": request,
        "user": user,
        "stores": stores,
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


@router.post("/{group_id}/edit")
async def edit_group(
    group_id: int,
    request: Request,
    name: str = Form(...),
    note: str = Form(None),
    deadline: str = Form(None),
    delivery_fee: float = Form(None),
    db: Session = Depends(get_db),
):
    """編輯團單"""
    from decimal import Decimal
    
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有團主或管理者可以編輯
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以編輯")
    
    # 更新團名和備註（任何時候都可以改）
    group.name = name
    group.note = note.strip() if note else None
    
    # 更新外送費
    if delivery_fee is not None:
        group.delivery_fee = Decimal(str(delivery_fee)) if delivery_fee > 0 else None
    
    # 更新截止時間
    if deadline:
        try:
            deadline_dt = datetime.fromisoformat(deadline)
            group.deadline = deadline_dt
        except ValueError:
            pass
    
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)


@router.post("/{group_id}/transfer")
async def transfer_group(
    group_id: int,
    request: Request,
    new_owner_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """轉移團主"""
    from app.models.user import User
    import logging
    logger = logging.getLogger("groups")
    
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有團主或管理者可以轉移
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以轉移")
    
    # 確認新團主存在
    new_owner = db.query(User).filter(User.id == new_owner_id).first()
    if not new_owner:
        raise HTTPException(status_code=404, detail="找不到該用戶")
    
    old_owner_name = group.owner.display_name
    group.owner_id = new_owner_id
    db.commit()
    
    logger.info(f"團單 {group_id} 團主從 {old_owner_name} 轉移到 {new_owner.display_name}")
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)


@router.get("/{group_id}/export/excel")
async def export_excel(request: Request, group_id: int, db: Session = Depends(get_db)):
    """匯出訂單為 Excel"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.orders).joinedload(Order.user),
        joinedload(Group.orders).joinedload(Order.items)
    ).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有團主或管理員可以匯出
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以匯出")
    
    from app.services.excel_service import export_orders_to_excel
    
    excel_file = export_orders_to_excel(group, group.orders)
    
    # 檔名
    filename = f"{group.name}_{group.deadline.strftime('%Y%m%d')}.xlsx"
    encoded_filename = quote(filename)
    
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )
