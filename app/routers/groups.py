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
from app.models.user import User
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
    
    # 取得啟用中的部門
    from app.models.department import Department
    departments = db.query(Department).filter(Department.is_active == True).all()
    
    # 取得使用者的開團模板
    from app.models.template import GroupTemplate
    my_templates = db.query(GroupTemplate).filter(
        GroupTemplate.user_id == user.id
    ).options(joinedload(GroupTemplate.store)).order_by(GroupTemplate.use_count.desc()).limit(5).all()
    
    return templates.TemplateResponse("group_new.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "departments": departments,
        "my_templates": my_templates,
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
    visibility: str = Form("public"),
    default_sugar: str = Form(None),
    default_ice: str = Form(None),
    lock_sugar: bool = Form(False),
    lock_ice: bool = Form(False),
    is_blind_mode: bool = Form(False),
    enable_lucky_draw: bool = Form(False),
    lucky_draw_count: int = Form(1),
    min_members: int = Form(None),
    auto_extend: bool = Form(False),
    auto_remind_minutes: int = Form(None),
    i_treat: bool = Form(False),
    db: Session = Depends(get_db),
):
    """建立團單"""
    from decimal import Decimal
    
    user = await get_current_user(request, db)
    
    # 取得 department_ids（多選）
    form_data = await request.form()
    department_ids = form_data.getlist("department_ids")
    
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
    
    # 判斷是否公開
    is_public = visibility == "public"
    
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
        is_public=is_public,
        delivery_fee=Decimal(str(delivery_fee)) if delivery_fee and delivery_fee > 0 else None,
        default_sugar=default_sugar if store.category == CategoryType.DRINK else None,
        default_ice=default_ice if store.category == CategoryType.DRINK else None,
        lock_sugar=lock_sugar if store.category == CategoryType.DRINK else False,
        lock_ice=lock_ice if store.category == CategoryType.DRINK else False,
        is_blind_mode=is_blind_mode,
        enable_lucky_draw=enable_lucky_draw,
        lucky_draw_count=lucky_draw_count if enable_lucky_draw else 1,
        min_members=min_members if min_members and min_members >= 2 else None,
        auto_extend=auto_extend if min_members else False,
        auto_remind_minutes=auto_remind_minutes if auto_remind_minutes else None,
        treat_user_id=user.id if i_treat else None,
    )
    db.add(group)
    db.flush()  # 取得 group.id
    
    # 如果選擇限定部門，建立關聯
    if not is_public and department_ids:
        from app.models.department import GroupDepartment
        for dept_id in department_ids:
            gd = GroupDepartment(group_id=group.id, department_id=int(dept_id))
            db.add(gd)
    
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
    
    # 載入 store 及其 toppings（用於加料選項）
    from app.models.store import Store, StoreTopping
    store = db.query(Store).filter(Store.id == group.store_id).options(
        joinedload(Store.toppings),
        joinedload(Store.branches)
    ).first()
    
    # 如果團單已過期且啟用隨機免單但尚未抽獎，進行抽獎
    if not group.is_open and group.enable_lucky_draw and not group.lucky_winner_ids:
        import random
        submitted_for_draw = db.query(Order).filter(
            Order.group_id == group_id,
            Order.status == OrderStatus.SUBMITTED
        ).all()
        if submitted_for_draw:
            winner_count = min(group.lucky_draw_count, len(submitted_for_draw))
            winners = random.sample(submitted_for_draw, winner_count)
            group.lucky_winner_ids = ",".join(str(o.user_id) for o in winners)
            db.commit()
    
    # 取得已結單的訂單（訂單牆）- 使用 eager loading
    submitted_orders = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).options(
        joinedload(Order.user),
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).all()
    
    # 取得我的訂單 - 使用 eager loading
    my_order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
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
    
    # 取得請客者資訊
    treat_user = None
    if group.treat_user_id:
        treat_user = db.query(User).filter(User.id == group.treat_user_id).first()
    
    return templates.TemplateResponse("group.html", {
        "request": request,
        "user": user,
        "group": group,
        "store": store,
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
        "treat_user": treat_user,
    })


@router.post("/{group_id}/close")
async def close_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    """提前截止團單"""
    import random
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以截止團單")
    
    group.is_closed = True
    
    # 如果啟用隨機免單，進行抽獎
    if group.enable_lucky_draw and not group.lucky_winner_ids:
        from app.models.order import Order, OrderStatus
        # 取得所有已結單的訂單
        submitted_orders = db.query(Order).filter(
            Order.group_id == group_id,
            Order.status == OrderStatus.SUBMITTED
        ).all()
        
        if submitted_orders:
            # 抽選幸運兒
            winner_count = min(group.lucky_draw_count, len(submitted_orders))
            winners = random.sample(submitted_orders, winner_count)
            group.lucky_winner_ids = ",".join(str(o.user_id) for o in winners)
    
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
    
    # 刪除請客記錄
    from app.models.treat import TreatRecord
    db.query(TreatRecord).filter(TreatRecord.group_id == group_id).delete()
    
    # 刪除部門關聯
    from app.models.department import GroupDepartment
    db.query(GroupDepartment).filter(GroupDepartment.group_id == group_id).delete()
    
    # 刪除相關訂單和訂單項目
    from app.models.order import OrderItemOption, OrderItemTopping
    orders = db.query(Order).filter(Order.group_id == group_id).all()
    for order in orders:
        for item in order.items:
            # 刪除訂單項目的選項
            db.query(OrderItemOption).filter(OrderItemOption.order_item_id == item.id).delete()
            # 刪除訂單項目的加料
            db.query(OrderItemTopping).filter(OrderItemTopping.order_item_id == item.id).delete()
            db.delete(item)
        db.delete(order)
    
    db.delete(group)
    db.commit()
    
    return RedirectResponse(url="/home", status_code=302)


@router.post("/{group_id}/treat")
async def set_treat(group_id: int, request: Request, db: Session = Depends(get_db)):
    """設定請客"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 檢查用戶是否有結單的訂單
    my_order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
        Order.status == OrderStatus.SUBMITTED
    ).first()
    
    if not my_order:
        raise HTTPException(status_code=400, detail="您尚未結單，無法請客")
    
    # 設定請客者
    group.treat_user_id = user.id
    
    # 記錄請客歷史
    from app.models.treat import TreatRecord
    treat_record = TreatRecord(
        group_id=group_id,
        treat_user_id=user.id,
        amount=group.total_amount
    )
    db.add(treat_record)
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)


@router.post("/{group_id}/cancel-treat")
async def cancel_treat(group_id: int, request: Request, db: Session = Depends(get_db)):
    """取消請客"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有請客者本人或團主可以取消
    if group.treat_user_id != user.id and group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="無權取消請客")
    
    # 刪除請客記錄
    from app.models.treat import TreatRecord
    db.query(TreatRecord).filter(
        TreatRecord.group_id == group_id,
        TreatRecord.treat_user_id == group.treat_user_id
    ).delete()
    
    group.treat_user_id = None
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)


@router.get("/{group_id}/treat-history")
async def treat_history(group_id: int, request: Request, db: Session = Depends(get_db)):
    """查看請客記錄"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得此店家的所有請客記錄
    from app.models.treat import TreatRecord
    from sqlalchemy import func
    
    records = db.query(
        TreatRecord.treat_user_id,
        User.display_name,
        func.count(TreatRecord.id).label('count'),
        func.max(TreatRecord.created_at).label('last_treat')
    ).join(User, TreatRecord.treat_user_id == User.id).join(
        Group, TreatRecord.group_id == Group.id
    ).filter(
        Group.store_id == group.store_id
    ).group_by(
        TreatRecord.treat_user_id, User.display_name
    ).order_by(func.count(TreatRecord.id).desc()).all()
    
    return templates.TemplateResponse("partials/treat_history.html", {
        "request": request,
        "records": records,
        "store_name": group.store.name
    })


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
    
    # 取得啟用中的部門
    from app.models.department import Department
    departments = db.query(Department).filter(Department.is_active == True).all()
    
    return templates.TemplateResponse("group_new.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "departments": departments,
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


# ============ 訪客模式 ============

@router.post("/{group_id}/guest-link")
async def generate_guest_link(group_id: int, request: Request, db: Session = Depends(get_db)):
    """產生訪客連結"""
    import secrets
    import hashlib
    
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 只有團主或管理員可以產生
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以產生訪客連結")
    
    # 產生一個基於 group_id 和時間的 token（簡單版）
    # 實際上可以存到資料庫，這裡用 hash 簡化
    secret = settings.secret_key or "default-secret"
    raw = f"{group_id}-{secret}-guest"
    token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    
    base_url = str(request.base_url).rstrip("/")
    link = f"{base_url}/groups/{group_id}/guest?token={token}"
    
    return {"link": link}


@router.get("/{group_id}/guest")
async def guest_access(group_id: int, token: str, request: Request, db: Session = Depends(get_db)):
    """訪客存取團單"""
    import hashlib
    from fastapi.responses import Response
    
    group = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner)
    ).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 驗證 token
    secret = settings.secret_key or "default-secret"
    raw = f"{group_id}-{secret}-guest"
    expected_token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    
    if token != expected_token:
        raise HTTPException(status_code=403, detail="無效的訪客連結")
    
    # 檢查是否已登入
    from app.services.auth import get_current_user_optional
    user, _ = await get_current_user_optional(request, db)
    
    if user:
        # 已登入，直接導向團單頁面
        return RedirectResponse(url=f"/groups/{group_id}", status_code=302)
    
    # 未登入，顯示訪客進入頁面
    return templates.TemplateResponse("guest_entry.html", {
        "request": request,
        "group": group,
        "store": group.store,
        "token": token,
    })


@router.post("/{group_id}/guest")
async def guest_enter(
    group_id: int,
    token: str = Form(...),
    guest_name: str = Form(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """訪客輸入名字進入團單"""
    import hashlib
    import secrets
    from app.models.user import User
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 驗證 token
    secret = settings.secret_key or "default-secret"
    raw = f"{group_id}-{secret}-guest"
    expected_token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    
    if token != expected_token:
        raise HTTPException(status_code=403, detail="無效的訪客連結")
    
    # 建立訪客帳號
    guest_line_id = f"guest_{secrets.token_hex(8)}"
    guest_user = User(
        line_user_id=guest_line_id,
        display_name=guest_name.strip(),
        nickname=guest_name.strip(),
        is_guest=True,
    )
    db.add(guest_user)
    db.commit()
    db.refresh(guest_user)
    
    # 建立 JWT token
    from app.services.auth import create_access_token
    access_token = create_access_token(data={"sub": guest_line_id})
    
    response = RedirectResponse(url=f"/groups/{group_id}", status_code=302)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400  # 24 小時
    )
    
    return response
