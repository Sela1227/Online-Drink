"""菜單差異（V2.13.1）

匯入預覽時把新 JSON 跟店家「使用中版本」比對，列出新增／變更／移除／不變，
讓管理員在按「確認匯入」前看得到這一版會改掉什麼。

純比較，不碰資料庫；兩邊都先攤平成同一種 dict 再比。

比對規則（與畫面稿一致）：
- 以**品名**為鍵、全菜單範圍。同名品項兩邊都只有一個 → 直接配對，分類不同就標「分類改了」
- 品名在任一邊重複（跨分類同名）→ 那個名字退回用「分類＋品名」配對
- 「變更」= price / price_l / options / 時價 / 停售 / 說明 任一不同，或分類改了（V2.14.0 加後三項）
- 「疑似只貼了部分菜單」= 移除數 ≥ 使用中品項數的一半，且使用中品項 ≥ 6
"""
from decimal import Decimal

PARTIAL_MIN_EXISTING = 6     # 使用中品項少於這個數就不判斷部分菜單（小菜單大改很正常）
PARTIAL_REMOVED_RATIO = 0.5  # 移除比例達到這個值就提醒


def _d(v):
    """價格正規化：None 保持 None，其餘轉 Decimal 再去掉尾零，讓 10 與 10.00 相等"""
    if v is None:
        return None
    return Decimal(str(v)).normalize()


def _flatten_existing(menu) -> list[dict]:
    """ORM Menu → [{name, category, price, price_l, options}]（含已下架，整份比）"""
    out = []
    cat_names = {c.id: c.name for c in (menu.categories or [])}
    for it in sorted(menu.items or [], key=lambda i: (i.sort_order or 0, i.id or 0)):
        out.append({
            "name": (it.name or "").strip(),
            "category": cat_names.get(it.category_id, "") if it.category_id else "",
            "price": _d(it.price),
            "price_l": _d(it.price_l),
            "tbd": bool(getattr(it, "price_tbd", False)),
            "available": getattr(it, "is_available", True) is not False,
            "note": (getattr(it, "description", None) or "").strip(),
            "options": tuple(sorted(
                ((o.name or "").strip(), _d(o.price_diff)) for o in (it.options or [])
            )),
        })
    return out


def _flatten_new(content) -> list[dict]:
    """Pydantic MenuContent → 同上"""
    out = []
    for cat in (content.categories or []):
        for it in cat.items:
            out.append(_new_item(it, cat.name))
    for it in (content.items or []):
        out.append(_new_item(it, ""))
    return out


def _new_item(it, category):
    return {
        "name": (it.name or "").strip(),
        "category": (category or "").strip(),
        "price": _d(it.price),
        "price_l": _d(it.price_l),
        "tbd": bool(getattr(it, "price_tbd", False)),
        "available": getattr(it, "is_available", True) is not False,
        "note": (getattr(it, "note", None) or "").strip(),
        "options": tuple(sorted(
            ((o.name or "").strip(), _d(o.price_diff)) for o in (it.options or [])
        )),
    }


def _key_of(item, dup_names: set) -> tuple:
    """重複的品名用（分類，品名），其餘只用品名"""
    if item["name"] in dup_names:
        return (item["category"], item["name"])
    return ("", item["name"])


def _dup_names(items) -> set:
    seen, dup = set(), set()
    for it in items:
        if it["name"] in seen:
            dup.add(it["name"])
        seen.add(it["name"])
    return dup


def _fmt_price(p, pl, tbd=False) -> str:
    if tbd:
        return "時價"
    if p is None:
        return ""
    s = f"${p:f}"
    if pl is not None:
        s += f"/${pl:f}"
    return s


def diff_menu(existing_menu, new_content) -> dict:
    """比對使用中版本與新 JSON。

    回傳：
      added:    [{name, category, price_text}]
      changed:  [{name, category, old_category, old_price_text, new_price_text,
                  price_changed, category_changed, options_changed, note}]
      removed:  [{name, category, price_text}]
      unchanged_count, existing_count, new_count
      partial_suspect: bool（疑似只貼了部分菜單）
    """
    old_items = _flatten_existing(existing_menu)
    new_items = _flatten_new(new_content)

    # 任一邊有重複的名字，那個名字兩邊都退回「分類＋品名」配對
    dup = _dup_names(old_items) | _dup_names(new_items)
    old_map = {}
    for it in old_items:
        old_map.setdefault(_key_of(it, dup), it)
    new_map = {}
    for it in new_items:
        new_map.setdefault(_key_of(it, dup), it)

    added, changed, removed = [], [], []
    unchanged = 0

    for key, nit in new_map.items():
        oit = old_map.get(key)
        if oit is None:
            added.append({
                "name": nit["name"], "category": nit["category"],
                "price_text": _fmt_price(nit["price"], nit["price_l"], nit["tbd"]),
                "unavailable": not nit["available"],
            })
            continue
        price_changed = (oit["tbd"] != nit["tbd"]) or (
            not nit["tbd"] and ((oit["price"] != nit["price"]) or (oit["price_l"] != nit["price_l"]))
        )
        category_changed = oit["category"] != nit["category"]
        options_changed = oit["options"] != nit["options"]
        availability_changed = oit["available"] != nit["available"]
        note_changed = oit["note"] != nit["note"]
        if not (price_changed or category_changed or options_changed or availability_changed or note_changed):
            unchanged += 1
            continue
        notes = []
        if not price_changed:
            notes.append("價格不變")
        if availability_changed:
            notes.append("改為停售" if not nit["available"] else "恢復供應")
        if category_changed:
            notes.append("分類改了")
        if options_changed:
            notes.append("選項改了")
        if note_changed:
            notes.append("說明改了")
        changed.append({
            "name": nit["name"],
            "category": nit["category"],
            "old_category": oit["category"],
            "old_price_text": _fmt_price(oit["price"], oit["price_l"], oit["tbd"]),
            "new_price_text": _fmt_price(nit["price"], nit["price_l"], nit["tbd"]),
            "price_changed": price_changed,
            "category_changed": category_changed,
            "options_changed": options_changed,
            "availability_changed": availability_changed,
            "note_changed": note_changed,
            "note": "，".join(notes),
        })

    for key, oit in old_map.items():
        if key not in new_map:
            removed.append({
                "name": oit["name"], "category": oit["category"],
                "price_text": _fmt_price(oit["price"], oit["price_l"], oit["tbd"]),
            })

    existing_count = len(old_map)
    partial_suspect = (
        existing_count >= PARTIAL_MIN_EXISTING
        and len(removed) >= existing_count * PARTIAL_REMOVED_RATIO
    )
    return {
        "added": added,
        "changed": changed,
        "removed": removed,
        "unchanged_count": unchanged,
        "existing_count": existing_count,
        "new_count": len(new_map),
        "partial_suspect": partial_suspect,
    }
