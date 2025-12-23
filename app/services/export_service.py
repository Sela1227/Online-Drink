from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime

from app.models.group import Group
from app.models.order import Order, OrderItem, OrderStatus


def generate_order_text(db: Session, group: Group) -> str:
    """產生點餐文字（給店家）"""
    lines = []
    
    # 標題
    lines.append(f"【{group.name}】")
    lines.append(f"店家：{group.store.name}")
    lines.append(f"截止：{group.deadline.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"團主：{group.owner.display_name}")
    lines.append("")
    lines.append("=" * 30)
    lines.append("")
    
    # 彙總品項
    item_summary = defaultdict(lambda: {"quantity": 0, "price": 0})
    
    orders = db.query(Order).filter(
        Order.group_id == group.id,
        Order.status == OrderStatus.SUBMITTED,
    ).all()
    
    for order in orders:
        for item in order.items:
            # 產生品項 key（品名 + 尺寸 + 客製化）
            key_parts = [item.item_name]
            if item.size:
                key_parts[0] = f"{item.item_name}({item.size})"
            if item.sugar:
                key_parts.append(item.sugar)
            if item.ice:
                key_parts.append(item.ice)
            for opt in item.selected_options:
                key_parts.append(opt.option_name)
            if item.note:
                key_parts.append(f"備註:{item.note}")
            
            key = " / ".join(key_parts)
            item_summary[key]["quantity"] += item.quantity
            item_summary[key]["price"] = item.unit_price + item.options_total
    
    # 輸出品項
    total_quantity = 0
    total_amount = 0
    
    for key, data in sorted(item_summary.items()):
        qty = data["quantity"]
        price = data["price"]
        subtotal = qty * price
        lines.append(f"{key}")
        lines.append(f"  x{qty} = ${subtotal}")
        lines.append("")
        total_quantity += qty
        total_amount += subtotal
    
    lines.append("=" * 30)
    lines.append(f"總杯數：{total_quantity}")
    lines.append(f"總金額：${total_amount}")
    
    return "\n".join(lines)


def generate_payment_text(db: Session, group: Group) -> str:
    """產生收款文字"""
    lines = []
    
    # 標題
    lines.append(f"【{group.name}】收款")
    lines.append(f"店家：{group.store.name}")
    lines.append("")
    
    # 取得所有訂單
    orders = db.query(Order).filter(Order.group_id == group.id).all()
    
    total_amount = 0
    submitted_users = []
    pending_users = []
    
    for order in orders:
        user_name = order.user.display_name
        amount = order.total_amount
        
        if order.status == OrderStatus.SUBMITTED:
            submitted_users.append((user_name, amount))
            total_amount += amount
        else:
            pending_users.append(user_name)
    
    # 已結單
    for user_name, amount in sorted(submitted_users, key=lambda x: x[0]):
        lines.append(f"☐ {user_name}：${amount}")
    
    # 未結單
    if pending_users:
        lines.append("")
        lines.append("【尚未結單】")
        for user_name in sorted(pending_users):
            lines.append(f"⚠️ {user_name}")
    
    lines.append("")
    lines.append("=" * 30)
    lines.append(f"總金額：${total_amount}")
    
    return "\n".join(lines)
