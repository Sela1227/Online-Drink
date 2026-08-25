from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.group import Group
from app.models.menu import MenuItem, ItemOption
from app.models.order import Order, OrderItem, OrderItemOption, OrderItemTopping, OrderStatus
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


def get_or_create_order(db: Session, group_id: int, user_id: int) -> Order:
    """取得或建立訂單"""
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user_id,
    ).first()
    
    if not order:
        order = Order(
            group_id=group_id,
            user_id=user_id,
            status=OrderStatus.DRAFT,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
    
    return order


@router.get("/groups/{group_id}/orders/wall")
async def order_wall(group_id: int, request: Request, db: Session = Depends(get_db)):
    """訂單牆片段（HTMX）"""
    user = await get_current_user(request, db)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")

    submitted_orders = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).options(
        joinedload(Order.user),
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).all()

    from datetime import datetime
    is_open = group.deadline > datetime.utcnow() if group.deadline else True

    return templates.TemplateResponse("partials/order_wall.html", {
        "request": request,
        "submitted_orders": submitted_orders,
        "group_id": group_id,
        "group": group,
        "is_open": is_open,
        "is_owner": group.owner_id == user.id,
        "is_admin": user.is_admin,
    })


@router.get("/groups/{group_id}/orders/mine")
async def my_order(group_id: int, request: Request, db: Session = Depends(get_db)):
    """我的訂單片段（HTMX）"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open if group else False,
    })


def _stock_remaining(db: Session, group_id: int, menu_item, exclude_order_id: int | None = None) -> int | None:
    """品項剩餘量（None=不限）。
    V2.8.0：佔用=已送出＋修改中（審稿方案 A——修改期間保留原庫存，不會因進修改被搶走；
    減量/刪除仍即時釋放）。exclude_order_id 用於送出/還原時排除自身避免重複計算。"""
    if menu_item is None or menu_item.stock_limit is None:
        return None
    q = db.query(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order).filter(
        OrderItem.menu_item_id == menu_item.id,
        Order.group_id == group_id,
        Order.status.in_((OrderStatus.SUBMITTED, OrderStatus.EDITING)),
    )
    if exclude_order_id is not None:
        q = q.filter(Order.id != exclude_order_id)
    used = q.scalar()
    return max(0, menu_item.stock_limit - int(used or 0))


def _lock_menu_items(db: Session, menu_item_ids):
    """交易內鎖定品項列（PostgreSQL SELECT FOR UPDATE，固定依 ID 排序防死鎖；SQLite 無效但無害）"""
    from app.models.menu import MenuItem as _MI
    ids = sorted(set(i for i in menu_item_ids if i))
    if not ids:
        return
    db.query(_MI).filter(_MI.id.in_(ids)).order_by(_MI.id).with_for_update().all()


def _ensure_visible(group, user, db):
    """限定部門/私人團可見性（審稿 #10：不能只靠畫面隱藏）"""
    if not group.is_visible_to(user, db):
        raise HTTPException(status_code=403, detail="您無權查看此團單")


@router.post("/groups/{group_id}/orders/items")
async def add_item(
    group_id: int,
    request: Request,
    menu_item_id: int = Form(...),
    size: str = Form(None),
    sugar: str = Form(None),
    ice: str = Form(None),
    quantity: int = Form(1),
    note: str = Form(None),
    options: list[int] = Form(default=[]),
    toppings: list[int] = Form(default=[]),
    backup_for: str = Form(None),
    db: Session = Depends(get_db),
):
    """加入品項（backup_for 有值時＝為該訂單品項新增缺貨候補）"""
    import logging
    logger = logging.getLogger("orders")
    
    user = await get_current_user(request, db)
    
    # 日誌：記錄誰在加品項
    logger.info(f"[加品項] user_id={user.id}, name={user.display_name}, group_id={group_id}, menu_item_id={menu_item_id}")
    
    # 檢查團單狀態
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    _ensure_visible(group, user, db)
    
    # 取得菜單品項（必須屬於本團菜單，防跨店/舊菜單注入）
    menu_item = db.query(MenuItem).filter(
        MenuItem.id == menu_item_id,
        MenuItem.menu_id == group.menu_id,
    ).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="品項不存在或不屬於本團菜單")
    if menu_item.is_available is False:
        raise HTTPException(status_code=400, detail="此品項已下架")
    if not backup_for:
        _rem = _stock_remaining(db, group_id, menu_item)
        if _rem is not None and quantity > _rem:
            raise HTTPException(status_code=400, detail=f"「{menu_item.name}」只剩 {_rem} 份" if _rem > 0 else f"「{menu_item.name}」已售完")
    
    # 決定單價（根據尺寸）
    if size == 'L' and menu_item.price_l:
        unit_price = menu_item.price_l
    else:
        unit_price = menu_item.price
        if not menu_item.price_l:
            size = None  # 沒有 L 價格就不記錄尺寸
    
    # 數量驗證（後端防異常值）
    if not backup_for and not (1 <= quantity <= 99):
        raise HTTPException(status_code=400, detail="數量需為 1-99")
    
    # ── 缺貨候補分支（V2.4.0 資訊型）──
    if backup_for:
        from app.models.order import OrderItemBackup
        from app.models.store import StoreTopping
        try:
            backup_for_id = int(backup_for)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="候補目標格式錯誤")
        target = db.query(OrderItem).join(Order).filter(
            OrderItem.id == backup_for_id,
            Order.user_id == user.id,
            Order.group_id == group_id,
        ).first()
        if not target:
            raise HTTPException(status_code=404, detail="找不到要加候補的品項")
        if target.order.status == OrderStatus.SUBMITTED:
            raise HTTPException(status_code=400, detail="請先進入修改模式")
        if not group.enable_backup:
            raise HTTPException(status_code=400, detail="此團未開啟候補")
        if len(target.backups) >= (group.backup_count or 1):
            raise HTTPException(status_code=400, detail="候補已達上限")
        
        # 每份總價 = 尺寸單價 + 加購 + 加料（快照）
        full_unit = Decimal(str(unit_price))
        extras = []
        for option_id in options:
            option = db.query(ItemOption).filter(
                ItemOption.id == option_id,
                ItemOption.menu_item_id == menu_item.id,
            ).first()
            if not option:
                raise HTTPException(status_code=400, detail="加購選項不存在或不屬於此品項")
            full_unit += option.price_diff
            extras.append(option.name)
        for topping_id in toppings:
            topping = db.query(StoreTopping).filter(
                StoreTopping.id == topping_id,
                StoreTopping.store_id == group.store_id,
            ).first()
            if not topping:
                raise HTTPException(status_code=400, detail="加料不存在或不屬於此店家")
            full_unit += topping.price
            extras.append("+" + topping.name)
        
        db.add(OrderItemBackup(
            order_item_id=target.id,
            priority=len(target.backups) + 1,
            menu_item_id=menu_item_id,
            item_name=menu_item.name,
            size=size,
            sugar=sugar,
            ice=ice,
            extras_text=" ".join(extras) if extras else None,
            unit_price=full_unit,
        ))
        db.commit()
        
        order = db.query(Order).filter(Order.id == target.order_id).options(
            joinedload(Order.items).joinedload(OrderItem.selected_options),
            joinedload(Order.items).joinedload(OrderItem.selected_toppings)
        ).first()
        return templates.TemplateResponse("partials/my_order.html", {
            "request": request,
            "order": order,
            "group": group,
            "is_open": group.is_open,
        })
    
    # 取得或建立訂單
    order = get_or_create_order(db, group_id, user.id)
    
    logger.info(f"[加品項] order_id={order.id}, order_user_id={order.user_id}")
    
    # 驗證：訂單的 user_id 應該和當前用戶一致
    if order.user_id != user.id:
        logger.error(f"🚨 訂單用戶不匹配！order.user_id={order.user_id}, current user.id={user.id}")
        raise HTTPException(status_code=403, detail="訂單用戶不匹配")
    
    # 如果是已結單狀態，不能直接加
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="請先進入修改模式")
    
    # 檢查是否有相同品項+設定，有的話合併杯數
    existing_item = None
    for item in order.items:
        if (item.menu_item_id == menu_item_id and 
            item.size == size and
            item.sugar == sugar and 
            item.ice == ice and
            item.note == note):
            # 檢查選項是否相同
            existing_option_ids = {opt.item_option_id for opt in item.selected_options}
            existing_topping_ids = {t.store_topping_id for t in item.selected_toppings}
            if existing_option_ids == set(options) and existing_topping_ids == set(toppings):
                existing_item = item
                break
    
    if existing_item:
        existing_item.quantity += quantity
    else:
        # 建立新的訂單品項
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=menu_item_id,
            item_name=menu_item.name,
            size=size,
            sugar=sugar,
            ice=ice,
            quantity=quantity,
            unit_price=unit_price,
            note=note,
        )
        db.add(order_item)
        db.flush()
        
        # 加入選項（驗證歸屬，不合法即拒絕）
        for option_id in options:
            option = db.query(ItemOption).filter(
                ItemOption.id == option_id,
                ItemOption.menu_item_id == menu_item.id,
            ).first()
            if not option:
                raise HTTPException(status_code=400, detail="加購選項不存在或不屬於此品項")
            order_item_option = OrderItemOption(
                order_item_id=order_item.id,
                item_option_id=option_id,
                option_name=option.name,
                price_diff=option.price_diff,
            )
            db.add(order_item_option)
        
        # 加入加料（驗證歸屬，不合法即拒絕）
        from app.models.store import StoreTopping
        for topping_id in toppings:
            topping = db.query(StoreTopping).filter(
                StoreTopping.id == topping_id,
                StoreTopping.store_id == group.store_id,
            ).first()
            if not topping:
                raise HTTPException(status_code=400, detail="加料不存在或不屬於此店家")
            order_item_topping = OrderItemTopping(
                order_item_id=order_item.id,
                store_topping_id=topping_id,
                topping_name=topping.name,
                price=topping.price,
            )
            db.add(order_item_topping)
    
    db.commit()
    
    # 重新載入 order 及其 items 和 toppings
    order = db.query(Order).filter(Order.id == order.id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    # 回傳更新後的訂單
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.delete("/orders/backups/{backup_id}")
async def delete_backup(
    backup_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """刪除缺貨候補（並重排順位）"""
    from app.models.order import OrderItemBackup
    user = await get_current_user(request, db)
    
    backup = db.query(OrderItemBackup).join(OrderItem).join(Order).filter(
        OrderItemBackup.id == backup_id,
        Order.user_id == user.id,
    ).first()
    if not backup:
        raise HTTPException(status_code=404, detail="候補不存在")
    
    target_item = backup.order_item
    order_id = target_item.order_id
    if target_item.order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="請先進入修改模式")
    group = target_item.order.group
    
    db.delete(backup)
    db.flush()
    # 重排順位 1..n
    remaining = db.query(OrderItemBackup).filter(
        OrderItemBackup.order_item_id == target_item.id
    ).order_by(OrderItemBackup.priority).all()
    for i, b in enumerate(remaining, start=1):
        b.priority = i
    db.commit()
    
    order = db.query(Order).filter(Order.id == order_id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.put("/orders/items/{item_id}")
async def update_item(
    item_id: int,
    request: Request,
    quantity: int = Form(...),
    db: Session = Depends(get_db),
):
    """更新品項杯數"""
    user = await get_current_user(request, db)
    
    order_item = db.query(OrderItem).filter(OrderItem.id == item_id).first()
    if not order_item:
        raise HTTPException(status_code=404, detail="品項不存在")
    
    order = order_item.order
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能修改自己的訂單")
    
    group = order.group
    if not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="請先進入修改模式")
    
    if quantity <= 0:
        db.delete(order_item)
    else:
        if order_item.menu_item is not None and quantity > order_item.quantity:
            _rem = _stock_remaining(db, order.group_id, order_item.menu_item)
            if _rem is not None and (quantity - order_item.quantity) > _rem:
                raise HTTPException(status_code=400, detail=f"「{order_item.item_name}」僅剩 {_rem} 份可再增加")
        order_item.quantity = quantity
    
    db.commit()
    
    # 重新載入 order
    order = db.query(Order).filter(Order.id == order.id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.delete("/orders/items/{item_id}")
async def delete_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除品項"""
    user = await get_current_user(request, db)
    
    order_item = db.query(OrderItem).filter(OrderItem.id == item_id).first()
    if not order_item:
        raise HTTPException(status_code=404, detail="品項不存在")
    
    order = order_item.order
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能修改自己的訂單")
    
    group = order.group
    if not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="請先進入修改模式")
    
    order_id = order.id
    db.delete(order_item)
    db.commit()
    
    # 重新載入 order
    order = db.query(Order).filter(Order.id == order_id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.post("/groups/{group_id}/orders/submit")
async def submit_order(group_id: int, request: Request, db: Session = Depends(get_db)):
    """結單"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    _ensure_visible(group, user, db)
    
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).first()
    
    if not order or not order.items:
        raise HTTPException(status_code=400, detail="請先加入品項")
    
    # 庫存權威檢查（V2.8.0：同品項多列彙總＋交易內鎖定，資料庫層保證先送先贏）
    _requested = {}
    _mi_map = {}
    for _it in order.items:
        if _it.menu_item is not None and _it.menu_item.stock_limit is not None:
            _requested[_it.menu_item_id] = _requested.get(_it.menu_item_id, 0) + _it.quantity
            _mi_map[_it.menu_item_id] = _it.menu_item
    if _requested:
        _lock_menu_items(db, _requested.keys())
        for _mid, _qty in _requested.items():
            _rem = _stock_remaining(db, group_id, _mi_map[_mid], exclude_order_id=order.id)
            if _rem is not None and _qty > _rem:
                raise HTTPException(status_code=400, detail=f"「{_mi_map[_mid].name}」只剩 {_rem} 份（你共點了 {_qty} 份），請調整數量後再送出")
    
    # 每單上限檢查（不允許超過時擋下）
    if group.order_limit and not group.allow_over_limit and order.final_amount > group.order_limit:
        raise HTTPException(status_code=400, detail=f"超過每單上限 ${int(group.order_limit)}，請調整品項")
    
    order.status = OrderStatus.SUBMITTED
    order.snapshot = None  # 清除快照
    db.commit()
    
    # 重新載入 order
    order = db.query(Order).filter(Order.id == order.id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.post("/groups/{group_id}/orders/edit")
async def edit_order(group_id: int, request: Request, db: Session = Depends(get_db)):
    """進入修改模式"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    _ensure_visible(group, user, db)
    
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")
    
    if order.status != OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="只能修改已結單的訂單")
    
    # 保存快照
    snapshot = {
        "items": [
            {
                "menu_item_id": item.menu_item_id,
                "item_name": item.item_name,
                "size": item.size,
                "sugar": item.sugar,
                "ice": item.ice,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "note": item.note,
                "options": [
                    {
                        "item_option_id": opt.item_option_id,
                        "option_name": opt.option_name,
                        "price_diff": str(opt.price_diff),
                    }
                    for opt in item.selected_options
                ],
                "toppings": [
                    {
                        "store_topping_id": t.store_topping_id,
                        "topping_name": t.topping_name,
                        "price": str(t.price),
                    }
                    for t in item.selected_toppings
                ],
                "fulfillment": item.fulfillment,
                "fulfilled_backup_priority": (item.fulfilled_backup.priority if item.fulfilled_backup else None),
                "diff_settled": item.diff_settled,
                "backups": [
                    {
                        "priority": b.priority,
                        "menu_item_id": b.menu_item_id,
                        "item_name": b.item_name,
                        "size": b.size,
                        "sugar": b.sugar,
                        "ice": b.ice,
                        "extras_text": b.extras_text,
                        "unit_price": str(b.unit_price),
                    }
                    for b in item.backups
                ],
            }
            for item in order.items
        ]
    }
    
    order.status = OrderStatus.EDITING
    order.snapshot = snapshot
    db.commit()
    
    # 重新載入 order
    order = db.query(Order).filter(Order.id == order.id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.post("/groups/{group_id}/orders/cancel")
async def cancel_edit(group_id: int, request: Request, db: Session = Depends(get_db)):
    """取消修改"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if group:
        _ensure_visible(group, user, db)
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")
    
    if order.status != OrderStatus.EDITING:
        raise HTTPException(status_code=400, detail="目前不在修改模式")
    
    if not order.snapshot:
        raise HTTPException(status_code=400, detail="無法還原訂單")
    
    # V2.8.0：還原前重驗庫存（修改期間若把限量品項刪除，名額可能已被他人取走）
    _snap_req = {}
    for _idata in order.snapshot["items"]:
        _mid = _idata.get("menu_item_id")
        if _mid:
            _snap_req[_mid] = _snap_req.get(_mid, 0) + int(_idata.get("quantity", 1))
    if _snap_req:
        from app.models.menu import MenuItem as _MI
        _lock_menu_items(db, _snap_req.keys())
        for _mid, _qty in _snap_req.items():
            _mi = db.query(_MI).filter(_MI.id == _mid).first()
            if _mi is None or _mi.stock_limit is None:
                continue
            _rem = _stock_remaining(db, group_id, _mi, exclude_order_id=order.id)
            if _rem is not None and _qty > _rem:
                raise HTTPException(status_code=400, detail=f"原訂單中的「{_mi.name}」目前僅剩 {_rem} 份，無法完整還原，請調整後重新送出")
    
    # 刪除目前的品項
    for item in order.items:
        db.delete(item)
    
    # 從快照還原
    for item_data in order.snapshot["items"]:
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=item_data["menu_item_id"],
            item_name=item_data["item_name"],
            size=item_data.get("size"),
            sugar=item_data["sugar"],
            ice=item_data["ice"],
            quantity=item_data["quantity"],
            unit_price=Decimal(item_data["unit_price"]),
            note=item_data["note"],
        )
        db.add(order_item)
        db.flush()
        
        for opt_data in item_data["options"]:
            order_item_option = OrderItemOption(
                order_item_id=order_item.id,
                item_option_id=opt_data["item_option_id"],
                option_name=opt_data["option_name"],
                price_diff=Decimal(opt_data["price_diff"]),
            )
            db.add(order_item_option)
        
        # 還原加料（V2.4.1 修：舊版快照漏存導致取消修改後加料遺失）
        for t_data in item_data.get("toppings", []):
            db.add(OrderItemTopping(
                order_item_id=order_item.id,
                store_topping_id=t_data["store_topping_id"],
                topping_name=t_data["topping_name"],
                price=Decimal(t_data["price"]),
            ))
        
        # 還原候補（V2.4.1 修；V2.8.0 加回填出貨狀態）
        from app.models.order import OrderItemBackup
        _new_backups = {}
        for b_data in item_data.get("backups", []):
            _nb = OrderItemBackup(
                order_item_id=order_item.id,
                priority=b_data["priority"],
                menu_item_id=b_data.get("menu_item_id"),
                item_name=b_data["item_name"],
                size=b_data.get("size"),
                sugar=b_data.get("sugar"),
                ice=b_data.get("ice"),
                extras_text=b_data.get("extras_text"),
                unit_price=Decimal(b_data["unit_price"]),
            )
            db.add(_nb)
            _new_backups[b_data["priority"]] = _nb
        # 出貨狀態還原（缺貨處理結果不因取消修改消失；fulfilled_backup_id 依順位重連新候補）
        if item_data.get("fulfillment"):
            order_item.fulfillment = item_data["fulfillment"]
            order_item.diff_settled = bool(item_data.get("diff_settled"))
            _fp = item_data.get("fulfilled_backup_priority")
            if _fp is not None and _fp in _new_backups:
                db.flush()
                order_item.fulfilled_backup_id = _new_backups[_fp].id
    
    order.status = OrderStatus.SUBMITTED
    order.snapshot = None
    db.commit()
    db.refresh(order)
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open if group else False,
    })


@router.delete("/groups/{group_id}/orders")
async def delete_order(group_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除我的訂單"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    _ensure_visible(group, user, db)
    
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).first()
    
    if order:
        # 刪除所有品項
        for item in order.items:
            db.delete(item)
        # 重置訂單狀態
        order.status = OrderStatus.DRAFT
        order.snapshot = None
        db.commit()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.post("/groups/{group_id}/orders/follow/{item_id}")
async def follow_item(
    group_id: int,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """跟點"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    _ensure_visible(group, user, db)
    
    # 取得要跟的品項（V2.4.1 修：限本團、已結單的品項，防跨團複製）
    source_item = db.query(OrderItem).join(Order).filter(
        OrderItem.id == item_id,
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).first()
    if not source_item:
        raise HTTPException(status_code=404, detail="品項不存在或不屬於本團")
    
    # 取得或建立訂單
    order = get_or_create_order(db, group_id, user.id)
    
    # V2.4.1 修：已結單不再靜默改狀態（原本偷偷進 EDITING 且無快照，取消修改會壞）
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="請先在「我的訂單」按修改訂單，再跟點")
    
    # V2.7.0：跟點也吃庫存/上下架
    if source_item.menu_item is not None:
        if source_item.menu_item.is_available is False:
            raise HTTPException(status_code=400, detail="此品項已下架")
        _rem = _stock_remaining(db, group_id, source_item.menu_item)
        if _rem is not None and _rem < 1:
            raise HTTPException(status_code=400, detail=f"「{source_item.item_name}」已售完")
    
    # 複製品項
    order_item = OrderItem(
        order_id=order.id,
        menu_item_id=source_item.menu_item_id,
        item_name=source_item.item_name,
        size=source_item.size,
        sugar=source_item.sugar,
        ice=source_item.ice,
        quantity=1,
        unit_price=source_item.unit_price,
        note=source_item.note,
    )
    db.add(order_item)
    db.flush()
    
    # 複製選項
    for opt in source_item.selected_options:
        order_item_option = OrderItemOption(
            order_item_id=order_item.id,
            item_option_id=opt.item_option_id,
            option_name=opt.option_name,
            price_diff=opt.price_diff,
        )
        db.add(order_item_option)
    
    # 複製加料
    for topping in source_item.selected_toppings:
        from app.models.order import OrderItemTopping
        order_item_topping = OrderItemTopping(
            order_item_id=order_item.id,
            store_topping_id=topping.store_topping_id,
            topping_name=topping.topping_name,
            price=topping.price,
        )
        db.add(order_item_topping)
    
    db.commit()
    
    # 重新載入 order（修復：確保 items 被載入）
    order = db.query(Order).filter(Order.id == order.id).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })


@router.post("/groups/{group_id}/orders/copy-last")
async def copy_last_order(group_id: int, request: Request, mode: str = Form("replace"), db: Session = Depends(get_db)):
    """複製上次訂單到購物車（mode: replace=取代現有 / append=加入保留現有）"""
    from fastapi.responses import RedirectResponse
    from app.models.store import Store, StoreTopping
    
    user = await get_current_user(request, db)
    
    group = db.query(Group).options(
        joinedload(Group.store)
    ).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    
    # 找到上次在同店家的訂單
    previous_order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings),
    ).join(Group).filter(
        Order.user_id == user.id,
        Group.store_id == group.store_id,
        Order.status == OrderStatus.SUBMITTED,
        Order.id != db.query(Order.id).filter(
            Order.group_id == group_id,
            Order.user_id == user.id,
        ).scalar_subquery(),
    ).order_by(Order.created_at.desc()).first()
    
    if not previous_order:
        raise HTTPException(status_code=404, detail="找不到上次的訂單")
    
    # 取得或建立當前訂單
    order = get_or_create_order(db, group_id, user.id)
    
    # V2.6.0 修：已送出的訂單不可被複製覆蓋（原本會靜默清空已送出內容）
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="訂單已送出，請先按「修改訂單」再複製")
    
    # 取代模式才清空現有品項；加入模式保留
    if mode != "append":
        for item in order.items:
            for opt in item.selected_options:
                db.delete(opt)
            for topping in item.selected_toppings:
                db.delete(topping)
            db.delete(item)
    
    # 複製上次訂單的品項（V2.7.0：過濾非本團菜單/已下架，數量封頂到剩餘庫存）
    _menu_item_ids = {mi.id for cat in group.menu.categories for mi in cat.items} if group.menu else set()
    for old_item in previous_order.items:
        if old_item.menu_item_id and _menu_item_ids and old_item.menu_item_id not in _menu_item_ids:
            continue
        _mi = old_item.menu_item
        if _mi is not None and _mi.is_available is False:
            continue
        _copy_qty = old_item.quantity
        if _mi is not None:
            _rem = _stock_remaining(db, group_id, _mi)
            if _rem is not None:
                if _rem < 1:
                    continue
                _copy_qty = min(_copy_qty, _rem)
        new_item = OrderItem(
            order_id=order.id,
            menu_item_id=old_item.menu_item_id,
            item_name=old_item.item_name,
            size=old_item.size,
            sugar=old_item.sugar,
            ice=old_item.ice,
            quantity=_copy_qty,
            unit_price=old_item.unit_price,
            note=old_item.note,
        )
        db.add(new_item)
        db.flush()
        
        # 複製選項
        for old_opt in old_item.selected_options:
            new_opt = OrderItemOption(
                order_item_id=new_item.id,
                item_option_id=old_opt.item_option_id,
                option_name=old_opt.option_name,
                price_diff=old_opt.price_diff,
            )
            db.add(new_opt)
        
        # 複製加料
        for old_topping in old_item.selected_toppings:
            new_topping = OrderItemTopping(
                order_item_id=new_item.id,
                store_topping_id=old_topping.store_topping_id,
                topping_name=old_topping.topping_name,
                price=old_topping.price,
            )
            db.add(new_topping)
    
    order.status = OrderStatus.DRAFT
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}?copied=1", status_code=302)


@router.get("/groups/{group_id}/random")
async def random_item(group_id: int, request: Request, db: Session = Depends(get_db)):
    """隨機推薦品項"""
    import random
    from app.models.menu import Menu, MenuItem
    
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得該菜單的所有品項
    items = db.query(MenuItem).filter(MenuItem.menu_id == group.menu_id).all()
    
    if not items:
        return HTMLResponse("<div class='text-center text-gray-500'>此菜單沒有品項</div>")
    
    # 隨機選一個
    chosen = random.choice(items)
    
    return HTMLResponse(f"""
    <div class="text-center p-4">
        <div class="text-4xl mb-3">🎲</div>
        <div class="text-xl font-bold text-gray-800 mb-1">{chosen.name}</div>
        <div class="text-orange-600 text-lg mb-3">${chosen.price}</div>
        <button onclick="scrollToItem({chosen.id}); document.querySelector('[x-data]').__x.$data.showRandom = false;"
                class="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg text-sm">
            去點這個！
        </button>
        <button onclick="htmx.trigger(this.closest('.random-result'), 'refreshRandom')"
                class="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm ml-2">
            🔄 再抽一次
        </button>
    </div>
    """)


@router.get("/groups/{group_id}/favorites")
async def get_favorites(group_id: int, request: Request, db: Session = Depends(get_db)):
    """取得用戶在此店家的最常點品項"""
    from sqlalchemy import func
    from app.models.menu import MenuItem
    
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 查詢用戶在此店家的歷史訂單品項，按品項名稱分組計數
    favorites = db.query(
        OrderItem.item_name,
        OrderItem.sugar,
        OrderItem.ice,
        OrderItem.size,
        func.sum(OrderItem.quantity).label('total_qty'),
        func.max(OrderItem.unit_price).label('price'),
        func.max(OrderItem.menu_item_id).label('menu_item_id'),
    ).join(Order).join(Group).filter(
        Order.user_id == user.id,
        Group.store_id == group.store_id,
        Order.status == OrderStatus.SUBMITTED,
    ).group_by(
        OrderItem.item_name,
        OrderItem.sugar,
        OrderItem.ice,
        OrderItem.size,
    ).order_by(
        func.sum(OrderItem.quantity).desc()
    ).limit(10).all()
    
    if not favorites:
        return HTMLResponse("""
        <div class="text-center py-8 text-gray-500">
            <div class="text-3xl mb-2">📝</div>
            <p>還沒有點過這家店</p>
            <p class="text-sm">點過幾次後就會出現你的最愛！</p>
        </div>
        """)
    
    # 生成 HTML
    items_html = ""
    for fav in favorites:
        spec_parts = []
        if fav.size:
            spec_parts.append(fav.size)
        if fav.sugar:
            spec_parts.append(fav.sugar)
        if fav.ice:
            spec_parts.append(fav.ice)
        spec = " / ".join(spec_parts) if spec_parts else ""
        
        items_html += f"""
        <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 cursor-pointer"
             onclick="scrollToItem({fav.menu_item_id}); document.querySelector('[x-data]').__x.$data.showFavorites = false;">
            <div class="flex-1">
                <div class="font-medium text-gray-800">{fav.item_name}</div>
                <div class="text-xs text-gray-500">{spec}</div>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-orange-600">${fav.price}</span>
                <span class="text-xs text-gray-400">點過 {int(fav.total_qty)} 次</span>
            </div>
        </div>
        """
    
    return HTMLResponse(f"""
    <div class="space-y-2">
        {items_html}
    </div>
    <p class="text-xs text-gray-400 text-center mt-4">點擊品項可快速跳到菜單位置</p>
    """)
