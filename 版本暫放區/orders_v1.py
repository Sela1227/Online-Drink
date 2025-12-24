from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from decimal import Decimal

from app.database import get_db
from app.models.group import Group
from app.models.menu import MenuItem, ItemOption
from app.models.order import Order, OrderItem, OrderItemOption, OrderStatus
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
    
    submitted_orders = db.query(Order).filter(
        Order.group_id == group_id,
        Order.status == OrderStatus.SUBMITTED,
    ).options(
        joinedload(Order.user),
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).all()
    
    return templates.TemplateResponse("partials/order_wall.html", {
        "request": request,
        "submitted_orders": submitted_orders,
        "group_id": group_id,
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
        joinedload(Order.items).joinedload(OrderItem.selected_options)
    ).first()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open if group else False,
    })


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
    db: Session = Depends(get_db),
):
    """加入品項"""
    user = await get_current_user(request, db)
    
    # 檢查團單狀態
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.is_open:
        raise HTTPException(status_code=400, detail="團單已截止")
    
    # 取得菜單品項
    menu_item = db.query(MenuItem).filter(MenuItem.id == menu_item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="品項不存在")
    
    # 決定單價（根據尺寸）
    if size == 'L' and menu_item.price_l:
        unit_price = menu_item.price_l
    else:
        unit_price = menu_item.price
        if not menu_item.price_l:
            size = None  # 沒有 L 價格就不記錄尺寸
    
    # 取得或建立訂單
    order = get_or_create_order(db, group_id, user.id)
    
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
            if existing_option_ids == set(options):
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
        
        # 加入選項
        for option_id in options:
            option = db.query(ItemOption).filter(ItemOption.id == option_id).first()
            if option:
                order_item_option = OrderItemOption(
                    order_item_id=order_item.id,
                    item_option_id=option_id,
                    option_name=option.name,
                    price_diff=option.price_diff,
                )
                db.add(order_item_option)
    
    db.commit()
    
    # 回傳更新後的訂單
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
        order_item.quantity = quantity
    
    db.commit()
    
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
    
    db.delete(order_item)
    db.commit()
    
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
    
    order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id,
    ).first()
    
    if not order or not order.items:
        raise HTTPException(status_code=400, detail="請先加入品項")
    
    order.status = OrderStatus.SUBMITTED
    order.snapshot = None  # 清除快照
    db.commit()
    
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
            }
            for item in order.items
        ]
    }
    
    order.status = OrderStatus.EDITING
    order.snapshot = snapshot
    db.commit()
    
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
    
    # 取得要跟的品項
    source_item = db.query(OrderItem).filter(OrderItem.id == item_id).first()
    if not source_item:
        raise HTTPException(status_code=404, detail="品項不存在")
    
    # 取得或建立訂單
    order = get_or_create_order(db, group_id, user.id)
    
    if order.status == OrderStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="請先進入修改模式")
    
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
    
    db.commit()
    
    return templates.TemplateResponse("partials/my_order.html", {
        "request": request,
        "order": order,
        "group": group,
        "is_open": group.is_open,
    })
