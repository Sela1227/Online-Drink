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
    
    # 缺貨候補對照（誰的哪個品項 → 候補什麼）
    backup_lines = []
    for order in orders:
        for item in order.items:
            if item.backups:
                specs = []
                for b in item.backups:
                    spec = b.item_name
                    if b.size:
                        spec += f"({b.size})"
                    if b.sugar or b.ice:
                        spec += f" {b.sugar or ''}/{b.ice or ''}"
                    if b.extras_text:
                        spec += f" {b.extras_text}"
                    specs.append(f"候補{b.priority} {spec} ${int(b.unit_price)}")
                backup_lines.append(f"- {order.user.show_name} {item.item_name}{f'({item.size})' if item.size else ''} x{item.quantity}：{'、'.join(specs)}")
    if backup_lines:
        lines.append("【缺貨候補對照】沒貨時依順位改買，數量同主品項")
        lines.extend(backup_lines)
        lines.append("")
    
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
    """產生收款文字（個人結帳明細：自動計算折扣、公司補助、個人自付）"""
    from decimal import Decimal

    lines = []

    orders = db.query(Order).filter(Order.group_id == group.id).all()

    subtotal = Decimal("0")        # 原價小計
    final_total = Decimal("0")     # 折後小計
    company_total = Decimal("0")   # 公司補助合計
    self_total = Decimal("0")      # 個人自付合計
    submitted_orders = []
    pending_users = []

    for order in orders:
        if order.status == OrderStatus.SUBMITTED:
            submitted_orders.append(order)
            subtotal += order.total_amount
            final_total += order.final_amount
            company_total += order.company_pay
            self_total += order.self_pay
        else:
            pending_users.append(order.user.show_name)

    # 外送費分攤（V2.4.1 修：餘數分配，總和恰等於外送費；依姓名排序前 r 位 +1 元，固定可重現）
    delivery_fee = group.delivery_fee or Decimal("0")
    sorted_orders = sorted(submitted_orders, key=lambda x: x.user.show_name)
    delivery_share = {}
    if delivery_fee > 0 and sorted_orders:
        n = len(sorted_orders)
        base = int(delivery_fee) // n
        r = int(delivery_fee) - base * n
        for i, o in enumerate(sorted_orders):
            delivery_share[o.id] = Decimal(base + (1 if i < r else 0))

    has_discount = bool(group.discount_percent and Decimal("0") < group.discount_percent < Decimal("100"))
    has_limit = bool(group.order_limit)

    # ── 標題與總覽 ──
    lines.append(f"【{group.name}】收款明細")
    lines.append(f"店家：{group.store.name}")
    docs = []
    if group.store.provides_invoice: docs.append("發票")
    if group.store.provides_receipt: docs.append("收據")
    if docs:
        lines.append(f"單據：可開{('、'.join(docs))}")
    lines.append("")
    lines.append(f"餐點小計：${subtotal}")
    if has_discount:
        lines.append(f"整單折扣：{int(group.discount_percent)}%（付原價的 {int(group.discount_percent)}%）→ 折後 ${final_total}")
    if has_limit:
        lines.append(f"公司補助：每單上限 ${int(group.order_limit)}，合計 ${company_total}")
    if delivery_fee > 0:
        _shares = sorted(set(int(v) for v in delivery_share.values()))
        _share_txt = f"${_shares[0]}" if len(_shares) == 1 else f"${_shares[0]}~{_shares[-1]}"
        lines.append(f"外送費：${delivery_fee}（每人 {_share_txt}，依名單分攤、總和不差）")
    lines.append(f"應向個人收：${self_total + delivery_fee}")
    lines.append(f"{len(submitted_orders)} 人已送出")
    lines.append("")
    lines.append("=" * 30)
    lines.append("")

    # ── 每人明細 ──
    for order in sorted_orders:
        user_name = order.user.show_name
        _dp = delivery_share.get(order.id, Decimal("0"))
        pay = order.self_pay + _dp

        lines.append(f"☐ {user_name}：${pay}")

        for item in order.items:
            item_desc = item.item_name
            if item.size:
                item_desc += f"({item.size})"
            if item.sugar or item.ice:
                item_desc += f" {item.sugar or ''}/{item.ice or ''}"
            if item.quantity > 1:
                item_desc += f" x{item.quantity}"
            lines.append(f"   - {item_desc} ${item.subtotal}")
            # 缺貨候補（含價差提醒）
            for b in item.backups:
                unit_total = item.subtotal / item.quantity
                diff = b.unit_price - unit_total
                spec = b.item_name
                if b.size:
                    spec += f"({b.size})"
                if b.sugar or b.ice:
                    spec += f" {b.sugar or ''}/{b.ice or ''}"
                if b.extras_text:
                    spec += f" {b.extras_text}"
                if diff > 0:
                    diff_txt = f"（價差 +${int(diff)}/份 需補）"
                elif diff < 0:
                    diff_txt = f"（價差 -${int(-diff)}/份 需退）"
                else:
                    diff_txt = "（同價）"
                lines.append(f"     候補{b.priority}: {spec} ${int(b.unit_price)}/份 {diff_txt}")
        if order.discount_amount and order.discount_amount > 0:
            note = f"（{order.discount_note}）" if order.discount_note else ""
            lines.append(f"   - 折扣{note} -${order.discount_amount}")
        # 結算行（有折扣或補助才逐項顯示計算過程）
        if has_discount:
            lines.append(f"   原價 ${order.total_amount} → 折後 ${order.final_amount}")
        if has_limit:
            if order.company_pay > 0:
                lines.append(f"   公司補助 -${order.company_pay}")
            lines.append(f"   應自付 ${order.self_pay}" + (f" + 運 ${_dp}" if _dp > 0 else ""))
        elif _dp > 0:
            lines.append(f"   餐 ${order.final_amount} + 運 ${_dp}")
        # 缺貨換貨結果（V2.5.0）
        if order.has_fulfillment_changes:
            for it in order.items:
                if it.fulfillment == "substituted" and it.fulfilled_backup:
                    lines.append(f"   ✕ {it.item_name} → 已換候補{it.fulfilled_backup.priority} {it.fulfilled_backup.item_name}")
                elif it.fulfillment == "unavailable":
                    lines.append(f"   ✕ {it.item_name} 缺貨未出（不收費）")
            sd = order.settle_diff
            settled = all(it.diff_settled for it in order.items if it.fulfillment)
            mark = "（已結清）" if settled else "（未結清）"
            if sd > 0:
                lines.append(f"   換貨後應付 ${order.actual_self_pay + _dp}，需向本人補收 ${int(sd)} {mark}")
            elif sd < 0:
                lines.append(f"   換貨後應付 ${order.actual_self_pay + _dp}，需退還本人 ${int(-sd)} {mark}")
            else:
                lines.append(f"   換貨後應付不變（補退 $0）")
        lines.append("")

    changed_orders = [o for o in submitted_orders if o.has_fulfillment_changes]
    if changed_orders:
        collect = sum((o.settle_diff for o in changed_orders if o.settle_diff > 0), Decimal("0"))
        refund = sum((-o.settle_diff for o in changed_orders if o.settle_diff < 0), Decimal("0"))
        unsettled = sum(1 for o in changed_orders if not all(it.diff_settled for it in o.items if it.fulfillment))
        lines.append(f"【換貨統計】{len(changed_orders)} 人有換貨：補收合計 ${int(collect)}／退還合計 ${int(refund)}" + (f"，{unsettled} 人未結清" if unsettled else "，全數結清"))
        lines.append("")

    has_any_backup = any(b for o in submitted_orders for it in o.items for b in it.backups)
    if has_any_backup:
        lines.append("※ 若以候補出貨，請依價差向該員補收/退還")
        lines.append("")

    if pending_users:
        lines.append("【未送出】")
        for user_name in sorted(pending_users):
            lines.append(f"- {user_name}")

    return "\n".join(lines)
