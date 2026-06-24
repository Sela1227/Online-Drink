"""
Phase 1 額外功能：
- 一鍵複製上次訂單
- 隨機選擇
- 最常點清單
- 催單功能
"""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from decimal import Decimal, InvalidOperation
import random

from app.database import get_db
from app.models.group import Group
from app.models.order import Order, OrderItem, OrderStatus
from app.models.menu import Menu, MenuItem, MenuCategory
from app.services.auth import get_current_user
from app.services.stats_service import get_user_last_order, get_user_favorites, get_store_hot_items

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/{group_id}/copy-last")
async def copy_last_order(
    group_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    一鍵複製上次訂單到購物車
    """
    group = db.query(Group).options(
        joinedload(Group.store)
    ).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 取得上次訂單
    last_order = get_user_last_order(db, user.id, group.store_id)
    
    if not last_order:
        return HTMLResponse("""
            <div class="text-center text-gray-500 py-4">
                <p>找不到上次在這間店的訂單</p>
            </div>
        """)
    
    # 找或建立當前訂單
    current_order = db.query(Order).filter(
        Order.group_id == group_id,
        Order.user_id == user.id
    ).first()
    
    if not current_order:
        current_order = Order(
            group_id=group_id,
            user_id=user.id,
            status=OrderStatus.DRAFT
        )
        db.add(current_order)
        db.flush()
    elif current_order.status == OrderStatus.SUBMITTED:
        # 已結單的話，進入編輯模式
        current_order.status = OrderStatus.EDITING
        current_order.snapshot = {
            "items": [
                {
                    "menu_item_id": item.menu_item_id,
                    "quantity": item.quantity,
                    "sugar": item.sugar,
                    "ice": item.ice,
                    "size": item.size,
                    "note": item.note,
                }
                for item in current_order.items
            ]
        }
    
    # 複製品項到當前訂單
    for item in last_order.items:
        # 檢查品項是否還在當前菜單
        menu_item = db.query(MenuItem).filter(
            MenuItem.id == item.menu_item_id,
            MenuItem.menu_id == group.menu_id
        ).first()
        
        if menu_item:
            new_item = OrderItem(
                order_id=current_order.id,
                menu_item_id=item.menu_item_id,
                quantity=item.quantity,
                sugar=item.sugar,
                ice=item.ice,
                size=item.size,
                note=item.note,
                unit_price=menu_item.price,
            )
            db.add(new_item)
    
    db.commit()
    
    # 返回更新後的購物車
    return templates.TemplateResponse("partials/my_order.html", {
        "request": Request,
        "order": current_order,
        "group": group,
    })


@router.get("/{group_id}/random-pick")
async def random_pick(
    group_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    隨機選擇一個品項
    """
    group = db.query(Group).options(
        joinedload(Group.menu).joinedload(Menu.categories).joinedload(MenuCategory.items)
    ).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 收集所有品項
    all_items = []
    for category in group.menu.categories:
        all_items.extend(category.items)
    
    if not all_items:
        return HTMLResponse("""
            <div class="text-center text-gray-500 py-4">
                <p>菜單沒有品項</p>
            </div>
        """)
    
    # 隨機選一個
    picked = random.choice(all_items)
    
    return HTMLResponse(f"""
        <div class="text-center py-6 animate-bounce-in">
            <div class="text-6xl mb-4">🎲</div>
            <div class="text-xl font-bold text-orange-600 mb-2">{picked.name}</div>
            <div class="text-gray-500">${picked.price}</div>
            <button onclick="addToCart({picked.id})" 
                    class="mt-4 bg-orange-500 text-white px-6 py-2 rounded-lg">
                就決定是你了！
            </button>
        </div>
    """)


@router.get("/{group_id}/my-favorites")
async def get_my_favorites(
    group_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    取得我在這間店的常點清單
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    favorites = get_user_favorites(db, user.id, group.store_id, limit=5)
    
    if not favorites:
        return HTMLResponse("""
            <div class="text-sm text-gray-500 text-center py-2">
                還沒有常點紀錄
            </div>
        """)
    
    html = '<div class="space-y-2">'
    for fav in favorites:
        item = fav["menu_item"]
        count = fav["count"]
        html += f'''
            <button onclick="addToCart({item.id})" 
                    class="w-full flex items-center justify-between p-2 bg-orange-50 rounded-lg hover:bg-orange-100 transition">
                <span class="font-medium">{item.name}</span>
                <span class="text-sm text-gray-500">點過 {count} 次</span>
            </button>
        '''
    html += '</div>'
    
    return HTMLResponse(html)


@router.get("/{group_id}/hot-items")
async def get_hot_items(
    group_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    取得這間店的熱門品項
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    hot_items = get_store_hot_items(db, group.store_id, days=30, limit=5)
    
    if not hot_items:
        return HTMLResponse("""
            <div class="text-sm text-gray-500 text-center py-2">
                暫無熱門資料
            </div>
        """)
    
    html = '<div class="space-y-2">'
    for idx, hot in enumerate(hot_items, 1):
        item = hot["menu_item"]
        count = hot["count"]
        html += f'''
            <button onclick="addToCart({item.id})" 
                    class="w-full flex items-center justify-between p-2 bg-red-50 rounded-lg hover:bg-red-100 transition">
                <div class="flex items-center gap-2">
                    <span class="text-orange-500 font-bold">#{idx}</span>
                    <span class="font-medium">{item.name}</span>
                </div>
                <span class="text-sm text-gray-500">{count} 杯</span>
            </button>
        '''
    html += '</div>'
    
    return HTMLResponse(html)


@router.get("/{group_id}/pending-users")
async def get_pending_users(
    group_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    催單功能：取得未結單的用戶列表
    """
    group = db.query(Group).options(
        joinedload(Group.orders).joinedload(Order.user)
    ).filter(Group.id == group_id).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 找出購物車有東西但未結單的人
    pending_users = []
    for order in group.orders:
        if order.status in (OrderStatus.DRAFT, OrderStatus.EDITING) and len(order.items) > 0:
            pending_users.append(order.user)
    
    if not pending_users:
        return HTMLResponse("""
            <div class="text-center text-green-600 py-4">
                <div class="text-2xl mb-2">✅</div>
                <p>太棒了！所有人都已結單</p>
            </div>
        """)
    
    html = f'''
        <div class="text-center mb-4">
            <div class="text-2xl mb-2">⏰</div>
            <p class="text-orange-600 font-medium">{len(pending_users)} 人尚未結單</p>
        </div>
        <div class="space-y-2">
    '''
    
    for u in pending_users:
        html += f'''
            <div class="flex items-center gap-3 p-2 bg-gray-50 rounded-lg">
                <img src="{u.picture_url or '/static/images/default-avatar.png'}" 
                     class="w-8 h-8 rounded-full">
                <span>{u.display_name}</span>
            </div>
        '''
    
    html += '</div>'
    
    return HTMLResponse(html)
