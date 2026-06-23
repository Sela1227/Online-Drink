from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

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
            for top in item.selected_toppings:
                key_parts.append(f"+{top.topping_name}")
            if item.note:
                key_parts.append(f"備註:{item.note}")
            
            key = " / ".join(key_parts)
            item_summary[key]["quantity"] += item.quantity
            # 單項價 = 單價 + 選項加價 + 加料加價（與 OrderItem.subtotal 一致，先前漏了加料）
            item_summary[key]["price"] = item.unit_price + item.options_total + item.toppings_total
    
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
    # 店家優惠（所有人折扣加總）
    total_discount = sum(
        (o.discount_amount or Decimal("0"))
        for o in group.orders
        if o.status == OrderStatus.SUBMITTED
    )
    if total_discount > 0:
        lines.append(f"原價：${total_amount}")
        lines.append(f"店家優惠：-${total_discount}")
        lines.append(f"實收：${total_amount - total_discount}")
    else:
        lines.append(f"總金額：${total_amount}")
    
    return "\n".join(lines)


def generate_payment_text(db: Session, group: Group) -> str:
    """產生收款文字（個人點餐明細）"""
    from decimal import Decimal
    
    lines = []
    
    # 取得所有訂單
    orders = db.query(Order).filter(Order.group_id == group.id).all()
    
    subtotal = Decimal("0")
    submitted_orders = []
    pending_users = []
    
    for order in orders:
        if order.status == OrderStatus.SUBMITTED:
            submitted_orders.append(order)
            subtotal += order.total_amount
        else:
            pending_users.append(order.user.show_name)
    
    # 外送費分攤計算
    delivery_fee = group.delivery_fee or Decimal("0")
    delivery_per_person = Decimal("0")
    if delivery_fee > 0 and len(submitted_orders) > 0:
        delivery_per_person = (delivery_fee / len(submitted_orders)).quantize(Decimal("1"))
    
    total_amount = subtotal + delivery_fee
    
    # 標題和總金額（先顯示）
    lines.append(f"【{group.name}】收款明細")
    lines.append(f"店家：{group.store.name}")
    lines.append("")
    lines.append(f"💰 餐點小計：${subtotal}")
    if delivery_fee > 0:
        lines.append(f"🚗 外送費：${delivery_fee}（每人 ${delivery_per_person}）")
        lines.append(f"💰 總金額：${total_amount}")
    lines.append(f"👥 {len(submitted_orders)} 人已結單")
    lines.append("")
    lines.append("=" * 30)
    lines.append("")
    
    # 每個人的細項
    for order in sorted(submitted_orders, key=lambda x: x.user.show_name):
        user_name = order.user.show_name
        order_amount = order.total_amount
        total_with_delivery = order_amount + delivery_per_person
        
        if delivery_fee > 0:
            lines.append(f"☐ {user_name}：${total_with_delivery}（餐 ${order_amount} + 運 ${delivery_per_person}）")
        else:
            lines.append(f"☐ {user_name}：${order_amount}")
        
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
        # 折扣行（有折扣才顯示）
        if order.discount_amount and order.discount_amount > 0:
            note = f"（{order.discount_note}）" if order.discount_note else ""
            lines.append(f"   - 折扣{note} -${order.discount_amount}")
        lines.append("")
    
    # 未結單
    if pending_users:
        lines.append("【尚未結單】")
        for user_name in sorted(pending_users):
            lines.append(f"⚠️ {user_name}")
    
    return "\n".join(lines)
