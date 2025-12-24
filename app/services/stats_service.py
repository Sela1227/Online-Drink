from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import List, Dict

from app.models.order import Order, OrderItem, OrderStatus
from app.models.menu import MenuItem
from app.models.store import Store


def get_user_favorites(db: Session, user_id: int, store_id: int, limit: int = 5) -> List[Dict]:
    """
    取得用戶在特定店家的最常點品項
    
    Returns:
        [{"menu_item": MenuItem, "count": int}, ...]
    """
    # 統計該用戶在該店家的點餐次數
    results = db.query(
        MenuItem,
        func.sum(OrderItem.quantity).label('total_qty')
    ).join(
        OrderItem, OrderItem.menu_item_id == MenuItem.id
    ).join(
        Order, Order.id == OrderItem.order_id
    ).filter(
        Order.user_id == user_id,
        Order.status == OrderStatus.SUBMITTED,
        MenuItem.menu_id == db.query(Store.id).filter(Store.id == store_id).scalar_subquery()
    ).group_by(
        MenuItem.id
    ).order_by(
        desc('total_qty')
    ).limit(limit).all()
    
    return [{"menu_item": r[0], "count": r[1]} for r in results]


def get_user_recent_orders(db: Session, user_id: int, store_id: int, limit: int = 5) -> List[Dict]:
    """
    取得用戶在特定店家的最近點過的品項
    """
    # 取得最近的不重複品項
    subquery = db.query(
        OrderItem.menu_item_id,
        func.max(OrderItem.created_at).label('last_ordered')
    ).join(
        Order, Order.id == OrderItem.order_id
    ).join(
        MenuItem, MenuItem.id == OrderItem.menu_item_id
    ).filter(
        Order.user_id == user_id,
        Order.status == OrderStatus.SUBMITTED,
    ).group_by(
        OrderItem.menu_item_id
    ).subquery()
    
    results = db.query(MenuItem).join(
        subquery, MenuItem.id == subquery.c.menu_item_id
    ).order_by(
        desc(subquery.c.last_ordered)
    ).limit(limit).all()
    
    return results


def get_store_hot_items(db: Session, store_id: int, days: int = 30, limit: int = 5) -> List[Dict]:
    """
    取得店家熱門品項（全站統計）
    """
    since = datetime.utcnow() - timedelta(days=days)
    
    results = db.query(
        MenuItem,
        func.sum(OrderItem.quantity).label('total_qty')
    ).join(
        OrderItem, OrderItem.menu_item_id == MenuItem.id
    ).join(
        Order, Order.id == OrderItem.order_id
    ).filter(
        Order.status == OrderStatus.SUBMITTED,
        Order.created_at >= since,
    ).group_by(
        MenuItem.id
    ).order_by(
        desc('total_qty')
    ).limit(limit).all()
    
    return [{"menu_item": r[0], "count": r[1]} for r in results]


def get_global_hot_items(db: Session, days: int = 30, limit: int = 10) -> List[Dict]:
    """
    取得全站熱門品項（首頁超夯清單用）
    """
    since = datetime.utcnow() - timedelta(days=days)
    
    results = db.query(
        MenuItem,
        Store,
        func.sum(OrderItem.quantity).label('total_qty')
    ).join(
        OrderItem, OrderItem.menu_item_id == MenuItem.id
    ).join(
        Order, Order.id == OrderItem.order_id
    ).join(
        Store, Store.id == MenuItem.menu_id  # 這裡可能需要調整關聯
    ).filter(
        Order.status == OrderStatus.SUBMITTED,
        Order.created_at >= since,
    ).group_by(
        MenuItem.id, Store.id
    ).order_by(
        desc('total_qty')
    ).limit(limit).all()
    
    return [{"menu_item": r[0], "store": r[1], "count": r[2]} for r in results]


def get_user_last_order(db: Session, user_id: int, store_id: int) -> Order | None:
    """
    取得用戶在特定店家的上一筆訂單（用於一鍵複製）
    """
    from app.models.group import Group
    
    return db.query(Order).join(
        Group, Group.id == Order.group_id
    ).filter(
        Order.user_id == user_id,
        Order.status == OrderStatus.SUBMITTED,
        Group.store_id == store_id,
    ).order_by(
        Order.created_at.desc()
    ).first()
