from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime

from app.models.group import Group
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import StoreBranch


def generate_order_text(db: Session, group: Group) -> str:
    """產生點餐文字（給店家）"""
    lines = []
    
    # 標題
    lines.append(f"【{group.name}】")
    
    # 店家資訊（含分店電話）
    store_info = group.store.name
    branch_phone = None
    
    if group.branch_id:
        branch = db.query(StoreBranch).filter(StoreBranch.id == group.branch_id).first()
        if branch:
            store_info = f"{group.store.name} {branch.name}"
            branch_phone = branch.phone
    elif group.store.branch:
        store_info = f"{group.store.name} {group.store.branch}"
        branch_phone = group.store.phone
    else:
        branch_phone = group.store.phone
    
    lines.append(f"店家：{store_info}")
    if branch_phone:
        lines.append(f"電話：{branch_phone}")
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
            # 產生品項 key（品名 + 客製化）
            key_parts = [item.item_name]
            if item.size:
                key_parts.append(f"({item.size})")
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
    """產生收款文字（個人點餐明細）"""
    lines = []
    
    # 取得所有訂單
    orders = db.query(Order).filter(Order.group_id == group.id).all()
    
    total_amount = 0
    submitted_orders = []
    pending_users = []
    
    for order in orders:
        if order.status == OrderStatus.SUBMITTED:
            submitted_orders.append(order)
            total_amount += order.total_amount
        else:
            pending_users.append(order.user.display_name)
    
    # 標題和總金額（先顯示）
    lines.append(f"【{group.name}】收款明細")
    lines.append(f"店家：{group.store.name}")
    lines.append("")
    lines.append(f"💰 總金額：${total_amount}")
    lines.append(f"👥 {len(submitted_orders)} 人已結單")
    lines.append("")
    lines.append("=" * 30)
    lines.append("")
    
    # 每個人的細項
    for order in sorted(submitted_orders, key=lambda x: x.user.display_name):
        user_name = order.user.display_name
        amount = order.total_amount
        lines.append(f"☐ {user_name}：${amount}")
        
        # 顯示點餐細項
        for item in order.items:
            item_desc = item.item_name
            if item.size:
                item_desc += f"({item.size})"
            if item.sugar or item.ice:
                item_desc += f" {item.sugar or ''}/{item.ice or ''}"
            if item.quantity > 1:
                item_desc += f" x{item.quantity}"
            lines.append(f"   - {item_desc} ${item.subtotal}")
        lines.append("")
    
    # 未結單
    if pending_users:
        lines.append("【尚未結單】")
        for user_name in sorted(pending_users):
            lines.append(f"⚠️ {user_name}")
    
    return "\n".join(lines)
