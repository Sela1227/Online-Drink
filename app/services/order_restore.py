# -*- coding: utf-8 -*-
"""修改中訂單的快照還原與截止結算（V2.11.1 P0-08）。

背景：團員按「修改訂單」後，訂單進入 EDITING 並存下快照。若他離開沒回來
（午餐時間很常見），截止時訂單就停在 EDITING。而所有匯出與統計都只算
SUBMITTED，於是這筆訂單：

  - 不在點餐文字、核對單、Excel 裡 → **店家不會做這份餐**
  - 不在收款明細裡 → 收不到錢
  - 不計入成團人數，也不參加抽獎

`cancel_edit` 本身允許截止後執行，但沒有人會想到要去按。
所以改成：團一截止就自動把 EDITING 還原成 SUBMITTED（等同他沒改過）。
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.order import (
    Order,
    OrderItem,
    OrderItemBackup,
    OrderItemOption,
    OrderItemTopping,
    OrderStatus,
)


def restore_snapshot(db: Session, order: Order) -> bool:
    """把 EDITING 訂單依快照還原成 SUBMITTED。

    不做 is_open 檢查，也不重驗庫存 —— EDITING 本來就佔用著庫存
    （V2.8 定義佔用＝SUBMITTED＋EDITING），還原回自己原本的量不會超賣。
    需要重驗庫存的互動式情境（使用者主動按「取消修改」）由呼叫端負責。

    回傳是否真的做了還原。
    """
    if order.status != OrderStatus.EDITING or not order.snapshot:
        return False

    snapshot = order.snapshot

    for item in list(order.items):
        db.delete(item)
    db.flush()

    for item_data in snapshot.get("items", []):
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

        for opt_data in item_data.get("options", []):
            db.add(OrderItemOption(
                order_item_id=order_item.id,
                item_option_id=opt_data["item_option_id"],
                option_name=opt_data["option_name"],
                price_diff=Decimal(opt_data["price_diff"]),
            ))

        for t_data in item_data.get("toppings", []):
            db.add(OrderItemTopping(
                order_item_id=order_item.id,
                store_topping_id=t_data["store_topping_id"],
                topping_name=t_data["topping_name"],
                price=Decimal(t_data["price"]),
            ))

        # 候補與出貨狀態（快照要涵蓋品項的所有子結構，這是 V2.4.1／V2.8.0 的教訓）
        new_backups = {}
        for b_data in item_data.get("backups", []):
            nb = OrderItemBackup(
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
            db.add(nb)
            new_backups[b_data["priority"]] = nb

        if item_data.get("fulfillment"):
            order_item.fulfillment = item_data["fulfillment"]
            order_item.diff_settled = bool(item_data.get("diff_settled"))
            fp = item_data.get("fulfilled_backup_priority")
            if fp is not None and fp in new_backups:
                db.flush()
                order_item.fulfilled_backup_id = new_backups[fp].id

    order.status = OrderStatus.SUBMITTED
    order.snapshot = None
    return True


def settle_editing_orders(db: Session, group) -> int:
    """團截止後，把所有還停在 EDITING 的訂單還原成 SUBMITTED。

    冪等：沒有 EDITING 訂單時什麼都不做，可以在每個進入點安全呼叫。
    回傳還原了幾筆。
    """
    if group is None or group.is_open:
        return 0

    editing = db.query(Order).filter(
        Order.group_id == group.id,
        Order.status == OrderStatus.EDITING,
    ).with_for_update().all()
    if not editing:
        return 0

    restored = 0
    for order in editing:
        if restore_snapshot(db, order):
            restored += 1
        else:
            # 沒有快照可還原（理論上不該發生）。留在 EDITING 只會讓這筆訂單
            # 從所有匯出消失，不如當成已送出，至少店家會做、團主收得到錢。
            order.status = OrderStatus.SUBMITTED
            restored += 1
    db.commit()
    return restored
