from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.store import CategoryType, Store  # V2.11.1 P1-05 驗證用
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


def _validate_item_spec(group, store, size, sugar, ice, quantity, options, note):
    """品項規格的後端驗證（V2.11.1 P1-05）。

    這些原本只靠前端限制，後端全盤照收，實測可以：
      - 團單設了「鎖定甜度」，仍然送任意 sugar 上來
      - sugar/ice/size 送任意字串（PostgreSQL 超過欄位長度會 500）
      - options=[5,5,5] 產生三筆同樣的選項並加價三次
      - quantity 送 100000
    表單能改，所以前端限制不是限制。
    """
    from app.models.store import OptionType

    if size not in (None, "", "M", "L"):
        raise HTTPException(status_code=400, detail="尺寸錯誤")
    size = size or None

    if group.category == CategoryType.DRINK and store is not None:
        sugars = {o.option_value for o in store.options if o.option_type == OptionType.SUGAR}
        ices = {o.option_value for o in store.options if o.option_type == OptionType.ICE}
        # 鎖定時一律用團單預設，不看前端送什麼
        if group.lock_sugar:
            sugar = group.default_sugar
        if group.lock_ice:
            ice = group.default_ice
        if sugar and sugars and sugar not in sugars:
            raise HTTPException(status_code=400, detail="甜度選項不存在")
        if ice and ices and ice not in ices:
            raise HTTPException(status_code=400, detail="冰塊選項不存在")
        # V2.11.2 N-08：店家沒設定甜冰選項時上面兩條整個略過（空集合），
        # 任意長度字串照收。飲料選項功能 V2.10.0 才有，很多店家目前還沒設。
        # PostgreSQL 超過 String(50) 會 500，SQLite 照收所以本機測不出來。
        from app.services.validation import clean_text as _ct
        sugar = _ct(sugar, 50, field="甜度")
        ice = _ct(ice, 50, field="冰塊")
    else:
        sugar = ice = None

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="數量錯誤")
    if not (1 <= quantity <= 99):
        raise HTTPException(status_code=400, detail="數量需介於 1 到 99")

    # 去重：同一個選項送多次會被加價多次
    options = list(dict.fromkeys(options or []))

    from app.services.validation import clean_text
    note = clean_text(note, 200, field="備註")

    return size, (sugar or None), (ice or None), quantity, options, note


def get_or_create_order(db: Session, group_id: int, user_id: int) -> Order:
    """取得或建立訂單。

    V2.11.1 P1-06：原本是「先查再建」，兩個請求同時進來（手機連點兩下「加入」）
    會各自查到 None、各自 insert，產生兩筆 Order。之後 `.first()` 拿到哪筆不確定，
    兩筆都可能被送出 → 重複收款。改成「建立衝突就回頭查」，搭配
    `uq_orders_group_user` 唯一索引，讓資料庫來仲裁而不是靠時間差。
    """
    from sqlalchemy.exc import IntegrityError

    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user_id,
    ).first()
    
    if not order:
        try:
            with db.begin_nested():
                order = Order(
                    group_id=group_id,
                    user_id=user_id,
                    status=OrderStatus.DRAFT,
                )
                db.add(order)
            db.commit()
            db.refresh(order)
        except IntegrityError:
            # 另一個請求先建好了，回頭拿它的
            db.rollback()
            order = db.query(Order).filter(
                Order.group_id == group_id,
                Order.user_id == user_id,
            ).first()
            if order is None:
                raise
    
    return order


@router.get("/groups/{group_id}/orders/wall")
async def order_wall(group_id: int, request: Request, db: Session = Depends(get_db)):
    """訂單牆片段（HTMX）"""
    user = await get_current_user(request, db)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    # V2.11.1 P0-05：原本沒有檢查，任何人都讀得到私密團的訂單內容與姓名
    _ensure_visible(group, user, db)

    submitted_orders = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).options(
        joinedload(Order.user),
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).all()

    is_open = group.is_open

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


def _own_qty(db: Session, order_id: int, menu_item_id) -> int:
    """這張訂單目前已經佔用了這個品項幾份（以資料庫為準，V2.11.3 R-01）。

    原本用 `sum(i.quantity for i in order.items ...)` 讀記憶體 collection，兩個方向都會錯：
      - 迴圈內新建的 OrderItem(order_id=...) **不會**自動加進 order.items，
        所以複製第二行同品項時不會把第一行已複製的量算進去；
      - 取代模式刪除並 flush 之後，被刪的物件仍留在 collection 裡直到 expire，
        又會多算。
    查資料庫沒有這些問題（呼叫前確保已 flush）。
    """
    if not menu_item_id:
        return 0
    return int(
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0)).filter(
            OrderItem.order_id == order_id,
            OrderItem.menu_item_id == menu_item_id,
        ).scalar() or 0
    )


def _available_for(db: Session, group_id: int, menu_item, order) -> int | None:
    """這張 EDITING 訂單還能再加幾份（None = 不限量）。呼叫前須已 flush。"""
    if menu_item is None or menu_item.stock_limit is None:
        return None
    _lock_menu_items(db, [menu_item.id])
    remaining = _stock_remaining(db, group_id, menu_item, exclude_order_id=order.id)
    if remaining is None:
        return None
    return max(0, remaining - _own_qty(db, order.id, menu_item.id))


def _reserve_stock(db: Session, group_id: int, menu_item, delta: int, order):
    """在 EDITING 訂單上增量時檢查並佔用庫存（V2.11.1 P1-09）。

    V2.8 定義「佔用 = SUBMITTED + EDITING」，所以在修改中的訂單加品項／加量／
    跟點會**立即佔用**庫存。但這些路徑原本只有「先查再送」、沒有 `_lock_menu_items`，
    兩個人同時操作仍可能超賣 —— 這正是 CLAUDE.md 那條「先查再送不是庫存機制」。

    DRAFT 不佔用（送出時才鎖），所以不需要經過這裡。
    """
    if menu_item is None or menu_item.stock_limit is None or delta <= 0:
        return
    if order.status != OrderStatus.EDITING:
        return
    _lock_menu_items(db, [menu_item.id])
    remaining = _stock_remaining(db, group_id, menu_item, exclude_order_id=order.id)
    if remaining is None:
        return
    # V2.11.3 R-01：改以資料庫為準，不依賴 order.items collection 的狀態
    mine = _own_qty(db, order.id, menu_item.id)
    if mine + delta > remaining:
        left = max(0, remaining - mine)
        raise HTTPException(
            status_code=400,
            detail=f"「{menu_item.name}」只剩 {left} 份" if left else f"「{menu_item.name}」已售完",
        )


def _ensure_visible(group, user, db):
    """限定部門/私人團可見性（審稿 #10：不能只靠畫面隱藏）。

    V2.11.1 P0-05：實作收斂到 app/services/visibility.py，與 SQL 層級的
    visible_group_clause 同一套規則。
    """
    from app.services.visibility import ensure_group_visible
    ensure_group_visible(group, user, db)


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
    
    # V2.11.1 P1-05：後端驗證規格（鎖甜冰可繞過、選項重複計價、數量無上限）
    _store = db.query(Store).options(joinedload(Store.options)).filter(
        Store.id == group.store_id
    ).first() if group.store_id else None
    size, sugar, ice, quantity, options, note = _validate_item_spec(
        group, _store, size, sugar, ice, quantity, options, note
    )
    
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
    
    # 數量已在 _validate_item_spec 驗過（V2.11.1 P1-05）
    
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
    
    # V2.11.1 P1-09：修改中的加品項會立即佔用庫存（V2.8 定義佔用＝SUBMITTED＋EDITING），
    # 但上面那道只是「先查」沒有鎖。EDITING 走加鎖版本重新驗一次。
    if order.status == OrderStatus.EDITING and not backup_for:
        _reserve_stock(db, group_id, menu_item, quantity, order)
    
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
        # V2.11.2 N-07：_validate_item_spec 只驗單次送出的量，
        # 連續加入兩次 99 合併後會變成 198
        if existing_item.quantity + quantity > 99:
            raise HTTPException(status_code=400, detail="同一品項最多 99 份")
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
    
    # V2.11.1 P1-05：原本沒有上限，實測 quantity=100000 照收
    if quantity > 99:
        raise HTTPException(status_code=400, detail="數量最多 99")
    
    if quantity <= 0:
        db.delete(order_item)
    else:
        if order_item.menu_item is not None and quantity > order_item.quantity:
            _delta = quantity - order_item.quantity
            if order.status == OrderStatus.EDITING:
                # V2.11.1 P1-09：修改中的加量會立即佔用庫存，要加鎖
                _reserve_stock(db, order.group_id, order_item.menu_item, _delta, order)
            else:
                _rem = _stock_remaining(db, order.group_id, order_item.menu_item)
                if _rem is not None and _delta > _rem:
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
    
    # V2.11.1 P0-08：還原邏輯抽到 app/services/order_restore.py，與截止時的
    # 自動結算共用同一套，避免兩邊各自維護而漏掉候補或出貨狀態。
    from app.services.order_restore import restore_snapshot
    restore_snapshot(db, order)
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
        if order.status == OrderStatus.EDITING:
            # V2.11.1 P1-09：修改中的跟點會立即佔用庫存，要加鎖
            _reserve_stock(db, group_id, source_item.menu_item, 1, order)
        else:
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
    
    # V2.11.1 P0-05：私密／部門團要擋
    _ensure_visible(group, user, db)
    
    # V2.11.1 P0-01：店家已刪除時 group.store_id 是 NULL，
    # `Group.store_id == None` 會被翻成 IS NULL，反而撈到其他已刪店家的訂單
    if group.store_id is None:
        raise HTTPException(status_code=404, detail="店家已移除，無法複製上次訂單")
    
    # 找到上次在同店家的訂單
    # V2.11.1 P0-01：原本用 `Order.id != (本團訂單 id 的子查詢)` 排除本團，
    # 但本團還沒有訂單時子查詢是 NULL，`id != NULL` 在 SQL 中為 NULL 而非 TRUE，
    # WHERE 整個被濾光 → 永遠 404。而「第一次進團、還沒點」正是這個功能最主要的使用情境。
    # 而且同一人在本團若有兩筆訂單（P1-06），PostgreSQL 會直接報 more than one row。
    # 改成直接排除本團 group_id。
    previous_order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.selected_options),
        joinedload(Order.items).joinedload(OrderItem.selected_toppings),
    ).join(Group).filter(
        Order.user_id == user.id,
        Group.store_id == group.store_id,
        Order.status == OrderStatus.SUBMITTED,
        Order.group_id != group_id,
    ).order_by(Order.updated_at.desc()).first()
    
    if not previous_order:
        raise HTTPException(status_code=404, detail="找不到上次的訂單")
    
    # 取得或建立當前訂單
    order = get_or_create_order(db, group_id, user.id)
    
    # V2.6.0 修：已送出的訂單不可被複製覆蓋（原本會靜默清空已送出內容）
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="訂單已送出，請先按「修改訂單」再複製")
    
    # ── 先算出「複製得成的清單」，確定有東西才動購物車（V2.11.2 N-03）──
    #
    # V2.11.1 的兩項修正交互產生了一個靜默失敗：P1-04 讓匯入一律新增菜單版本
    # （新版本的品項都是新 id），P1-01 讓複製只認 menu_item_id。於是店家只要更新
    # 過一次菜單，舊訂單的 id 全部指向舊版本，一筆都比對不到 —— 而取代模式會
    # **先清空購物車**才發現沒東西可複製，使用者已經放進去的就沒了，畫面上還
    # 沒有任何提示。
    #
    # 改法：先比 id（同版本），比不到再比品名（跨版本），全部比不到就直接回 400
    # 不動購物車。
    _menu_items = list(group.menu.items) if group.menu else []
    _by_id = {mi.id: mi for mi in _menu_items}
    _by_name = {}
    for _mi in _menu_items:
        if _mi.is_available is not False:
            _by_name.setdefault((_mi.name or "").strip(), _mi)
    
    def _match_current(_old):
        _cur = _by_id.get(_old.menu_item_id)
        if _cur is None:
            _cur = _by_name.get((_old.item_name or "").strip())
        return _cur
    
    _plan = [(o, _match_current(o)) for o in previous_order.items]
    _skipped = sum(1 for _, m in _plan if m is None or m.is_available is False)
    _plan = [(o, m) for o, m in _plan if m is not None and m.is_available is not False]
    if not _plan:
        raise HTTPException(status_code=400, detail="上次點的品項在目前菜單都找不到了")
    
    # V2.11.3 R-05：上面只過濾「比對不到」與「已下架」，沒有過濾「已售完」。
    # 若全部都會在迴圈裡因庫存被跳過，購物車已經清掉了才發現 copied=0 ——
    # 正是 N-03 要避免的情況。先做一次庫存可用性預檢。
    # 取代模式待會兒會刪光現有品項，所以預檢時要把自己的量視為 0。
    _any_available = False
    for _o, _m in _plan:
        if _m.stock_limit is None:
            _any_available = True
            break
        _pre_rem = _stock_remaining(
            db, group_id, _m,
            exclude_order_id=order.id if (mode != "append" or order.status == OrderStatus.EDITING) else None,
        )
        if _pre_rem is None:
            _any_available = True
            break
        if mode == "append" and order.status == OrderStatus.EDITING:
            _pre_rem -= _own_qty(db, order.id, _m.id)
        if _pre_rem >= 1:
            _any_available = True
            break
    if not _any_available:
        raise HTTPException(status_code=400, detail="上次點的品項目前都已售完")
    
    # 取代模式才清空現有品項；加入模式保留
    if mode != "append":
        for item in list(order.items):
            for opt in item.selected_options:
                db.delete(opt)
            for topping in item.selected_toppings:
                db.delete(topping)
            db.delete(item)
        # V2.11.2 N-09：autoflush=False，不 flush 的話下面算庫存時
        # 仍會把剛刪掉的量算成佔用，在 EDITING 訂單上會少複製
        db.flush()
    
    # 店家現行的甜冰選項（供比對；店家沒設就是空集合＝不比對）
    _store_opts = None
    if group.category == CategoryType.DRINK and group.store is not None:
        from app.models.store import OptionType as _OT
        _store_opts = (
            {o.option_value for o in group.store.options if o.option_type == _OT.SUGAR},
            {o.option_value for o in group.store.options if o.option_type == _OT.ICE},
        )
    _skipped_opt = False
    
    _copied = 0
    for old_item, _mi in _plan:
        _copy_qty = old_item.quantity
        if order.status == OrderStatus.EDITING:
            # V2.11.3 R-01：修改中的訂單會立即佔用庫存，要問「還能再加幾份」。
            # V2.11.2 用 try/except 做流程控制是錯的 —— except 分支算的剩餘量
            # 排除了自己（exclude_order_id=order.id），等於把剛被擋下的量又放回去：
            # 已送出 5 份、上次點 3 份、庫存 5，結果複製成 8 份。
            _avail = _available_for(db, group_id, _mi, order)
            if _avail is not None:
                if _avail < 1:
                    _skipped += 1
                    continue
                _copy_qty = min(_copy_qty, _avail)
        else:
            _rem = _stock_remaining(db, group_id, _mi)
            if _rem is not None:
                if _rem < 1:
                    _skipped += 1
                    continue
                _copy_qty = min(_copy_qty, _rem)
        # V2.11.2 N-09：團單若鎖定甜冰，複製過來的也要照團單走，
        # 否則等於從這條路徑繞過 P1-05 的鎖定
        _sugar = group.default_sugar if group.lock_sugar else old_item.sugar
        _ice = group.default_ice if group.lock_ice else old_item.ice
        # V2.11.3 R-05：新版本品項若沒有 price_l，單價會以 M 價算，但 size 仍記成
        # "L"，核對單就顯示 L。add_item 在同樣情況會把 size 清成 None，比照處理。
        _size = old_item.size if (old_item.size != 'L' or _mi.price_l) else None
        # 甜冰若已不在店家現行選項中（店家改過選項），改為不指定而不是照抄舊值
        if group.category == CategoryType.DRINK and _store_opts is not None:
            if _sugar and _store_opts[0] and _sugar not in _store_opts[0]:
                _sugar = None
                _skipped_opt = True
            if _ice and _store_opts[1] and _ice not in _store_opts[1]:
                _ice = None
                _skipped_opt = True
        new_item = OrderItem(
            order_id=order.id,
            menu_item_id=_mi.id,
            item_name=_mi.name,
            size=_size,
            sugar=_sugar,
            ice=_ice,
            quantity=_copy_qty,
            # V2.11.1 P1-01：原本沿用 old_item.unit_price。店家在後台改價時
            # menu_item 的 id 不變，複製過來的就是舊價，結帳金額直接錯。
            unit_price=(_mi.price_l if (_size == 'L' and _mi.price_l) else _mi.price),
            note=old_item.note,
        )
        db.add(new_item)
        db.flush()
        
        # 複製選項（V2.11.1 P1-01：以現行 ItemOption 重新取價；已不存在的略過）
        for old_opt in old_item.selected_options:
            # 先比 id，跨菜單版本時 id 也換了，再以名稱在新品項的選項裡找
            _cur_opt = db.query(ItemOption).filter(
                ItemOption.id == old_opt.item_option_id,
                ItemOption.menu_item_id == _mi.id,
            ).first() if old_opt.item_option_id else None
            if _cur_opt is None:
                _cur_opt = next(
                    (o for o in _mi.options if (o.name or "").strip() == (old_opt.option_name or "").strip()),
                    None,
                )
            if _cur_opt is None:
                continue
            db.add(OrderItemOption(
                order_item_id=new_item.id,
                item_option_id=_cur_opt.id,
                option_name=_cur_opt.name,
                price_diff=_cur_opt.price_diff,
            ))
        
        # 複製加料（同上，以現行 StoreTopping 重新取價）
        for old_topping in old_item.selected_toppings:
            # V2.11.3 R-05：原本沒有排除已停用的加料
            _cur_top = db.query(StoreTopping).filter(
                StoreTopping.id == old_topping.store_topping_id,
                StoreTopping.store_id == group.store_id,
                StoreTopping.is_active == True,
            ).first() if old_topping.store_topping_id else None
            if _cur_top is None:
                _cur_top = db.query(StoreTopping).filter(
                    StoreTopping.store_id == group.store_id,
                    StoreTopping.name == (old_topping.topping_name or "").strip(),
                    StoreTopping.is_active == True,
                ).first()
            if _cur_top is None:
                continue
            db.add(OrderItemTopping(
                order_item_id=new_item.id,
                store_topping_id=_cur_top.id,
                topping_name=_cur_top.name,
                price=_cur_top.price,
            ))
        _copied += 1
    
    # V2.11.1 P1-01：原本無條件設成 DRAFT。在「修改中」執行複製上次，會讓訂單
    # 從 EDITING 掉回 DRAFT：庫存佔用被釋放、快照殘留、「取消修改」按鈕也消失
    # （因為狀態不是 EDITING）。新建的訂單本來就是 DRAFT，這行只會造成傷害。
    db.commit()
    
    return RedirectResponse(
        url=f"/groups/{group_id}?copied={_copied}&skipped={_skipped}",
        status_code=302,
    )



# V2.11.1 P0-06：已刪除 `GET /groups/{id}/random` 與 `GET /groups/{id}/favorites`。
#   原因一：兩支用 f-string 直接組 HTML，完全沒有逸出。代購品名由任何使用者建立，
#           實測 `<img src=x onerror=alert(1)>` 會原樣輸出；sugar/ice/size 同樣直通。
#   原因二：前端早已不呼叫它們（隨機推薦改在前端跑、常點清單由模板渲染），
#           而且內含 Alpine v2 的 `__x.$data` API，在 v3 下本來就是壞的。
#   若日後要恢復，一律改用 TemplateResponse，交給 Jinja 自動逸出，不要自己拼 HTML。
