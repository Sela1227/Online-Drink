from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
import qrcode
import io
import base64

from app.config import get_settings
from app.database import get_db
from app.models.group import Group
from app.models.store import Store, StoreBranch, CategoryType
from app.models.menu import Menu, MenuItem, MenuCategory
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.services.auth import get_current_user, get_current_user_optional
from app.services.export_service import generate_order_text, generate_payment_text

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

# 台北時區
TAIPEI_TZ = timezone(timedelta(hours=8))

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
async def new_group_page(request: Request, store_id: int = None, db: Session = Depends(get_db)):
    """開團頁面"""
    user = await get_current_user(request, db)
    
    # 取得用戶的部門 IDs
    from app.models.department import Department, UserDepartment, StoreDepartment
    user_dept_ids = [ud.department_id for ud in db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id
    ).all()]
    
    # 取得啟用中的店家（含分店）
    all_stores = db.query(Store).filter(Store.is_personal != True).options(
        joinedload(Store.branches)
    ).filter(Store.is_active == True).all()
    
    # 過濾用戶可見的店家
    visible_stores = []
    for s in all_stores:
        if s.is_public:
            visible_stores.append(s)
        elif user.is_admin:
            visible_stores.append(s)
        else:
            store_dept_ids = {sd.department_id for sd in db.query(StoreDepartment).filter(
                StoreDepartment.store_id == s.id
            ).all()}
            if store_dept_ids & set(user_dept_ids):
                visible_stores.append(s)
    stores = visible_stores
    
    # 取得啟用中的部門
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
        "preselect_store_id": store_id,
    })


@router.post("")
async def create_group(
    request: Request,
    store_id: int = Form(None),
    is_proxy: bool = Form(False),
    name: str = Form(...),
    deadline: str = Form(...),
    note: str = Form(None),
    branch_id: int = Form(None),
    delivery_fee: float = Form(None),
    order_limit: float = Form(None),
    allow_over_limit: bool = Form(False),
    enable_backup: bool = Form(False),
    backup_count: int = Form(2),
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
    
    if is_proxy:
        # 代購（V2.7.0）：取得/建立個人店家 + 每團一份自訂菜單
        store = db.query(Store).filter(
            Store.is_personal == True,
            Store.owner_user_id == user.id,
        ).first()
        if not store:
            store = Store(
                name=f"{user.show_name} 的代購",
                category=CategoryType.GROUP_BUY,
                is_personal=True,
                owner_user_id=user.id,
            )
            db.add(store)
            db.flush()
        menu = Menu(store_id=store.id, is_active=False)  # 不啟用，避免干擾一般選單邏輯
        db.add(menu)
        db.flush()
        db.add(MenuCategory(menu_id=menu.id, name="代購品項", sort_order=0))
        db.flush()
        store_id = store.id
    else:
        if not store_id:
            raise HTTPException(status_code=400, detail="請選擇店家")
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
        order_limit=Decimal(str(order_limit)) if order_limit and order_limit > 0 else None,
        allow_over_limit=allow_over_limit,
        enable_backup=enable_backup,
        backup_count=max(1, min(3, backup_count)),
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
    
    # 取得該店家熱門品項（全站統計，最近 30 天）
    from datetime import timedelta
    # V2.10.2：Order.created_at 是 UTC，門檻若從台北時間算，窗口會變成 29 天 16 小時
    # （坑 #25 的反向案例）。滾動窗直接從 utcnow() 起算，寫法同 home.py::get_hot_items
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    hot_items = db.query(
        OrderItem.item_name,
        OrderItem.menu_item_id,
        func.sum(OrderItem.quantity).label('total_qty')
    ).join(Order).join(Group).filter(
        Group.store_id == group.store_id,
        Order.status == OrderStatus.SUBMITTED,
        Order.created_at >= thirty_days_ago
    ).group_by(OrderItem.item_name, OrderItem.menu_item_id).order_by(
        func.sum(OrderItem.quantity).desc()
    ).limit(5).all()
    
    # 限定部門/私人團可見性（V2.8.0 審稿：後端真正阻擋）
    if not group.is_visible_to(user, db):
        raise HTTPException(status_code=403, detail="您無權查看此團單")
    
    # 取得菜單品項（含分類）
    menu = group.menu

    # 個人常點（此使用者在此店家點過最多的品項，對應到目前菜單中可點的）
    my_freq_rows = db.query(
        OrderItem.menu_item_id,
        func.sum(OrderItem.quantity).label('cnt')
    ).join(Order).join(Group).filter(
        Order.user_id == user.id,
        Group.store_id == group.store_id,
        OrderItem.menu_item_id.isnot(None)
    ).group_by(OrderItem.menu_item_id).order_by(
        func.sum(OrderItem.quantity).desc()
    ).limit(8).all()
    _freq_ids = [r[0] for r in my_freq_rows]
    _menu_items_by_id = {}
    for _cat in menu.categories:
        for _it in _cat.items:
            _menu_items_by_id[_it.id] = _it
    my_frequent = [_menu_items_by_id[i] for i in _freq_ids if i in _menu_items_by_id][:4]
    
    # 庫存已用量（V2.7.0：已送出佔用；有設上限的品項才需要）
    stock_used = {}
    _limited_ids = [i for i, m in _menu_items_by_id.items() if m.stock_limit is not None]
    if _limited_ids:
        rows = db.query(
            OrderItem.menu_item_id, func.coalesce(func.sum(OrderItem.quantity), 0)
        ).join(Order).filter(
            OrderItem.menu_item_id.in_(_limited_ids),
            Order.group_id == group.id,
            Order.status.in_((OrderStatus.SUBMITTED, OrderStatus.EDITING)),
        ).group_by(OrderItem.menu_item_id).all()
        stock_used = {r[0]: int(r[1]) for r in rows}
    
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
        "branch": next((b for b in store.branches if b.id == group.branch_id), None) if group.branch_id else None,
        "menu": menu,
        "submitted_orders": submitted_orders,
        "my_order": my_order,
        "pending_count": pending_count,
        "pending_orders": pending_orders,
        "last_order": last_order,
        "last_order_items": last_order_items,
        "favorite_items": favorite_items,
        "hot_items": hot_items,
        "my_frequent": my_frequent,
        "stock_used": stock_used,
        "is_owner": group.owner_id == user.id,
        "is_admin": user.is_admin,
        "is_open": group.is_open,
        "all_users": all_users,
        "is_favorited": is_favorited,
        "treat_user": treat_user,
    })


@router.get("/{group_id}/items-panel")
async def proxy_items_panel(group_id: int, request: Request, db: Session = Depends(get_db)):
    """代購品項管理面板（團主/管理員，僅代購團）"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.store or not group.store.is_personal:
        raise HTTPException(status_code=404, detail="非代購團")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可管理品項")
    items = []
    if group.menu:
        for cat in group.menu.categories:
            items.extend(cat.items)
    items.sort(key=lambda x: (x.sort_order, x.id))
    return templates.TemplateResponse("partials/proxy_items_panel.html", {
        "request": request, "group": group, "items": items,
    })


@router.post("/{group_id}/items")
async def proxy_item_create(
    group_id: int,
    request: Request,
    item_name: str = Form(...),
    price: str = Form(None),
    price_tbd: bool = Form(False),
    description: str = Form(None),
    stock_limit: int = Form(None),
    image_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """代購新增品項"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.store or not group.store.is_personal:
        raise HTTPException(status_code=404, detail="非代購團")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可管理品項")
    item_name = (item_name or "").strip()
    if not (1 <= len(item_name) <= 100):
        raise HTTPException(status_code=400, detail="品名需 1-100 字")
    if description and len(description.strip()) > 200:
        raise HTTPException(status_code=400, detail="說明最多 200 字")
    if price_tbd:
        price_dec = Decimal("0")  # 未訂：先以 0 佔位，定價後回寫
    else:
        try:
            price_dec = Decimal(str(price).strip())
        except Exception:
            raise HTTPException(status_code=400, detail="價格格式錯誤（或勾選「未訂」）")
        if not (Decimal("1") <= price_dec <= Decimal("1000000")):
            raise HTTPException(status_code=400, detail="價格需為 1 ~ 1,000,000")
    if stock_limit is not None and stock_limit != 0 and not (1 <= stock_limit <= 99999):
        raise HTTPException(status_code=400, detail="數量上限需為 1 ~ 99999")
    
    cat = group.menu.categories[0] if group.menu and group.menu.categories else None
    if cat is None:
        cat = MenuCategory(menu_id=group.menu_id, name="代購品項", sort_order=0)
        db.add(cat)
        db.flush()
    
    image_url = None
    if image_file and image_file.filename:
        from app.services.upload_service import upload_image
        image_url = await upload_image(image_file, folder="sela/items")
    
    db.add(MenuItem(
        menu_id=group.menu_id,
        category_id=cat.id,
        name=item_name.strip(),
        price=price_dec,
        description=description.strip() if description else None,
        image_url=image_url,
        stock_limit=stock_limit if stock_limit and stock_limit > 0 else None,
        price_tbd=price_tbd,
    ))
    db.commit()
    return await proxy_items_panel(group_id, request, db)


@router.post("/{group_id}/items/{item_id}/update")
async def proxy_item_update(
    group_id: int,
    item_id: int,
    request: Request,
    item_name: str = Form(...),
    price: str = Form(None),
    price_tbd: bool = Form(False),
    description: str = Form(None),
    stock_limit: int = Form(None),
    image_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """代購修改品項（不影響已送出訂單的快照）"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.store or not group.store.is_personal:
        raise HTTPException(status_code=404, detail="非代購團")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可管理品項")
    item = db.query(MenuItem).filter(MenuItem.id == item_id, MenuItem.menu_id == group.menu_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="品項不存在")
    item_name = (item_name or "").strip()
    if not (1 <= len(item_name) <= 100):
        raise HTTPException(status_code=400, detail="品名需 1-100 字")
    if description and len(description.strip()) > 200:
        raise HTTPException(status_code=400, detail="說明最多 200 字")
    if price_tbd:
        price_dec = Decimal("0")  # 未訂：先以 0 佔位，定價後回寫
    else:
        try:
            price_dec = Decimal(str(price).strip())
        except Exception:
            raise HTTPException(status_code=400, detail="價格格式錯誤（或勾選「未訂」）")
        if not (Decimal("1") <= price_dec <= Decimal("1000000")):
            raise HTTPException(status_code=400, detail="價格需為 1 ~ 1,000,000")
    if stock_limit is not None and stock_limit != 0 and not (1 <= stock_limit <= 99999):
        raise HTTPException(status_code=400, detail="數量上限需為 1 ~ 99999")
    
    if stock_limit and stock_limit > 0:
        from app.models.order import OrderItem as _OI, Order as _O, OrderStatus as _OS
        _used = db.query(func.coalesce(func.sum(_OI.quantity), 0)).join(_O).filter(
            _OI.menu_item_id == item.id,
            _O.group_id == group.id,
            _O.status.in_((_OS.SUBMITTED, _OS.EDITING)),
        ).scalar() or 0
        if stock_limit < int(_used):
            raise HTTPException(status_code=400, detail=f"已有 {int(_used)} 份被訂走，上限不可低於 {int(_used)}")
    # 未訂 → 定價：回寫此團所有引用此品項且仍為 0 元的訂單（未訂快照本為暫定，唯一允許回寫的情境）
    if item.price_tbd and not price_tbd and price_dec > 0:
        db.query(OrderItem).filter(
            OrderItem.menu_item_id == item.id,
            OrderItem.order_id.in_(db.query(Order.id).filter(Order.group_id == group.id)),
            OrderItem.unit_price == 0,
        ).update({OrderItem.unit_price: price_dec}, synchronize_session=False)
    item.price_tbd = price_tbd
    item.name = item_name.strip()
    item.price = price_dec
    item.description = description.strip() if description else None
    item.stock_limit = stock_limit if stock_limit and stock_limit > 0 else None
    if image_file and image_file.filename:
        from app.services.upload_service import upload_image
        new_url = await upload_image(image_file, folder="sela/items")
        if new_url:
            item.image_url = new_url
    db.commit()
    return await proxy_items_panel(group_id, request, db)


@router.post("/{group_id}/items/{item_id}/toggle")
async def proxy_item_toggle(group_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    """代購品項上/下架"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.store or not group.store.is_personal:
        raise HTTPException(status_code=404, detail="非代購團")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可管理品項")
    item = db.query(MenuItem).filter(MenuItem.id == item_id, MenuItem.menu_id == group.menu_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="品項不存在")
    item.is_available = not (item.is_available if item.is_available is not None else True)
    db.commit()
    return await proxy_items_panel(group_id, request, db)


@router.post("/{group_id}/store-icon")
async def proxy_store_icon(
    group_id: int,
    request: Request,
    icon_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """代購團 icon 上傳（個人店家 logo）"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.store or not group.store.is_personal:
        raise HTTPException(status_code=404, detail="非代購團")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可操作")
    from app.services.upload_service import upload_image
    url = await upload_image(icon_file, folder="sela/proxy")
    if url:
        group.store.logo_url = url
        db.commit()
    return await proxy_items_panel(group_id, request, db)


@router.get("/{group_id}/fulfillment")
async def fulfillment_panel(group_id: int, request: Request, db: Session = Depends(get_db)):
    """缺貨處理面板（團主/管理員）"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可操作")
    
    from app.models.order import OrderItem as OI
    orders = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).options(
        joinedload(Order.items).joinedload(OI.backups),
        joinedload(Order.user),
    ).all()
    
    # 依「品項名(尺寸)」分組，店家說什麼缺貨就找那一組
    groups_map = {}
    for o in orders:
        for it in o.items:
            label = it.item_name + (f"（{it.size}）" if it.size else "")
            groups_map.setdefault(label, []).append({"order": o, "item": it})
    item_groups = [{"label": k, "entries": v} for k, v in sorted(groups_map.items())]
    
    return templates.TemplateResponse("partials/fulfillment_panel.html", {
        "request": request,
        "group": group,
        "item_groups": item_groups,
    })


@router.post("/{group_id}/fulfillment/{item_id}")
async def fulfillment_action(
    group_id: int,
    item_id: int,
    request: Request,
    action: str = Form(...),
    backup_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """缺貨處理動作：backup=換候補 / unavailable=缺貨不出 / reset=還原 / toggle_settled=補退結清切換"""
    user = await get_current_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="僅團主可操作")
    if group.is_open:
        raise HTTPException(status_code=400, detail="請先截止團單，再進行缺貨與換貨處理")
    
    from app.models.order import OrderItem as OI
    item = db.query(OI).join(Order).filter(
        OI.id == item_id,
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="品項不存在或未結單")
    
    if action == "backup":
        backup = next((b for b in item.backups if b.id == backup_id), None)
        if not backup:
            raise HTTPException(status_code=400, detail="候補不存在或不屬於此品項")
        item.fulfillment = "substituted"
        item.fulfilled_backup_id = backup.id
        item.diff_settled = False
    elif action == "unavailable":
        item.fulfillment = "unavailable"
        item.fulfilled_backup_id = None
        item.diff_settled = False
    elif action == "reset":
        item.fulfillment = None
        item.fulfilled_backup_id = None
        item.diff_settled = False
    elif action == "toggle_settled":
        if not item.fulfillment:
            raise HTTPException(status_code=400, detail="此品項無換貨紀錄")
        item.diff_settled = not item.diff_settled
    else:
        raise HTTPException(status_code=400, detail="未知動作")
    
    db.commit()
    return await fulfillment_panel(group_id, request, db)


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


@router.post("/{group_id}/orders/{order_id}/discount")
async def set_order_discount(
    group_id: int,
    order_id: int,
    request: Request,
    discount_amount: str = Form(""),
    discount_note: str = Form(""),
    db: Session = Depends(get_db),
):
    """團主/管理員對某人訂單設定折扣（店家優惠，連動所有金額處）"""
    user = await get_current_user(request, db)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    # 權限：只有團主或管理員
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以調整折扣")

    order = db.query(Order).filter(Order.id == order_id, Order.group_id == group_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")

    # 解析折扣金額（空字串或 0 = 取消折扣）
    amt = Decimal("0")
    if discount_amount and discount_amount.strip():
        try:
            amt = Decimal(discount_amount.strip())
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail="折扣金額必須是數字")
    if amt < 0:
        amt = Decimal("0")
    # 折扣不可超過原價
    if amt > order.items_subtotal:
        amt = order.items_subtotal

    order.discount_amount = amt
    order.discount_note = (discount_note.strip()[:100] or None) if amt > 0 else None
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
    stores = db.query(Store).filter(Store.is_active == True, Store.is_personal != True).all()
    
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
    order_limit: float = Form(None),
    allow_over_limit: bool = Form(False),
    discount_percent: float = Form(None),
    enable_backup: bool = Form(False),
    backup_count: int = Form(2),
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
    
    # 更新每單上限
    group.order_limit = Decimal(str(order_limit)) if order_limit and order_limit > 0 else None
    group.allow_over_limit = allow_over_limit
    
    # 整單折扣（1-99 有效，其餘=無折扣）
    group.discount_percent = Decimal(str(int(discount_percent))) if discount_percent and 0 < discount_percent < 100 else None
    
    # 缺貨候補
    group.enable_backup = enable_backup
    group.backup_count = max(1, min(3, backup_count))
    
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


@router.get("/{group_id}/export/receipt.pdf")
async def export_receipt_pdf(request: Request, group_id: int, db: Session = Depends(get_db)):
    """匯出訂單核對單 PDF（給團主跟店家核對）"""
    user = await get_current_user(request, db)

    group = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.orders).joinedload(Order.user),
        joinedload(Group.orders).joinedload(Order.items),
    ).filter(Group.id == group_id).first()

    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以匯出")

    from app.services.receipt_service import generate_receipt_pdf
    pdf_file = generate_receipt_pdf(db, group)

    filename = f"{group.name}_核對單_{group.deadline.strftime('%Y%m%d')}.pdf"
    encoded_filename = quote(filename)
    return StreamingResponse(
        pdf_file,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.get("/{group_id}/export/receipt.png")
async def export_receipt_png(request: Request, group_id: int, db: Session = Depends(get_db)):
    """匯出訂單核對單 PNG（方便貼 LINE 給店家）"""
    user = await get_current_user(request, db)

    group = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.orders).joinedload(Order.user),
        joinedload(Group.orders).joinedload(Order.items),
    ).filter(Group.id == group_id).first()

    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以匯出")

    from app.services.receipt_service import generate_receipt_png
    png_file = generate_receipt_png(db, group)

    filename = f"{group.name}_核對單_{group.deadline.strftime('%Y%m%d')}.png"
    encoded_filename = quote(filename)
    return StreamingResponse(
        png_file,
        media_type="image/png",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


# ============ 訪客模式（已停用，本系統只用 LINE 登入）============
# V1.19.2：訪客功能會建立空殼帳號污染用戶列表，且本系統只需 LINE 登入，故停用。
# 路由保留但回傳停用訊息，避免舊訪客連結被點到時建立新帳號。
GUEST_MODE_ENABLED = False


@router.post("/{group_id}/guest-link")
async def generate_guest_link(group_id: int, request: Request, db: Session = Depends(get_db)):
    """產生分享連結（點連結的人需用自己的 LINE 登入才能跟團）"""
    import hashlib
    user = await get_current_user(request, db)

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    if group.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有團主可以產生分享連結")

    secret = settings.secret_key or "default-secret"
    raw = f"{group_id}-{secret}-guest"
    token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    base_url = str(request.base_url).rstrip("/")
    link = f"{base_url}/groups/{group_id}/guest?token={token}"
    return {"link": link}


@router.get("/{group_id}/guest")
async def guest_access(group_id: int, token: str, request: Request, db: Session = Depends(get_db)):
    """分享連結存取：驗證 token 後，未登入導去 LINE 登入、登入後回團單"""
    import hashlib

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")

    # 驗證 token
    secret = settings.secret_key or "default-secret"
    raw = f"{group_id}-{secret}-guest"
    expected_token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    if token != expected_token:
        raise HTTPException(status_code=403, detail="無效的連結")

    # 已登入 → 直接進團單
    from app.services.auth import get_current_user_optional
    user, _ = await get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url=f"/groups/{group_id}", status_code=302)

    # 未登入 → 導去 LINE 登入，登入後回團單頁（要跟團一定要用自己的 LINE）
    resp = RedirectResponse(url=f"/auth/login?next=/groups/{group_id}", status_code=302)
    return resp


@router.post("/{group_id}/guest")
async def guest_enter(
    group_id: int,
    token: str = Form(...),
    guest_name: str = Form(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """訪客輸入名字進入團單（已停用）"""
    if not GUEST_MODE_ENABLED:
        raise HTTPException(status_code=410, detail="訪客功能已停用，請使用 LINE 登入")
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
