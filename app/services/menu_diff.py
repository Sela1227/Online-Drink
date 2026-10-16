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
            "options_seq": tuple(((o.name or "").strip(), _d(o.price_diff)) for o in (it.options or [])),
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
        "options_seq": tuple(((o.name or "").strip(), _d(o.price_diff)) for o in (it.options or [])),
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
            notes.append("選項：" + _describe_options(dict(oit["options"]), dict(nit["options"])))
        if note_changed:
            notes.append(f"說明：「{oit['note'] or '（無）'}」→「{nit['note'] or '（無）'}」")
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

    # V2.16.1 B-9：分類改名合併成一行。舊分類整個消失＋新分類整個出現＋兩邊品名重疊 ≥ 80% → 視為改名；
    # 只因分類改了而進「變更」的品項抽掉（算回不變），其他有真的變更的保留但不再標「分類改了」
    renamed = _detect_renamed_categories(old_items, new_items, dup)
    if renamed:
        pairs = {(r["old"], r["new"]) for r in renamed}
        kept = []
        for it in changed:
            if it["category_changed"] and (it["old_category"], it["category"]) in pairs:
                only_cat = not (it["price_changed"] or it["options_changed"] or it["availability_changed"] or it["note_changed"])
                if only_cat:
                    unchanged += 1
                    continue
                it["category_changed"] = False
                it["note"] = "，".join(n for n in it["note"].split("，") if n != "分類改了")
            kept.append(it)
        changed = kept

    existing_count = len(old_map)
    partial_suspect = (
        existing_count >= PARTIAL_MIN_EXISTING
        and len(removed) >= existing_count * PARTIAL_REMOVED_RATIO
    )

    # V2.15.1 審核 P2-3：只調整排序也是變更（「把招牌移到最前面」是最常見的需求）。
    # 比：分類順序、品項整體順序（含跨分類）、每個品項的選項順序
    old_cats = []
    for c in sorted(existing_menu.categories or [], key=lambda c: (c.sort_order or 0, c.id or 0)):
        old_cats.append((c.name or "").strip())
    new_cats = [(c.name or "").strip() for c in (new_content.categories or [])]
    old_seq = [_key_of(it, dup) for it in old_items]
    new_seq = [_key_of(it, dup) for it in new_items]
    common = set(old_map) & set(new_map)
    old_seq_c = [k for k in old_seq if k in common]
    new_seq_c = [k for k in new_seq if k in common]
    opt_order_changed = any(
        old_map[k]["options"] == new_map[k]["options"] and old_map[k]["options_seq"] != new_map[k]["options_seq"]
        for k in common
    )
    order_changed = (old_cats != new_cats and set(old_cats) == set(new_cats)) or old_seq_c != new_seq_c or opt_order_changed

    return {
        "added": added,
        "changed": changed,
        "removed": removed,
        "unchanged_count": unchanged,
        "existing_count": existing_count,
        "new_count": len(new_map),
        "partial_suspect": partial_suspect,
        "order_changed": order_changed,
        "renamed_categories": renamed,
        "identical": not added and not changed and not removed and not order_changed and not renamed,
    }


RENAME_OVERLAP_RATIO = 0.8


def _detect_renamed_categories(old_items, new_items, dup) -> list[dict]:
    """回傳 [{old, new, count, unchanged}]。count=新分類品項數；unchanged=其中內容完全沒變的數量（由呼叫端的 changed 推不出，這裡直接比）"""
    old_by_cat, new_by_cat = {}, {}
    for it in old_items:
        if it["category"]:
            old_by_cat.setdefault(it["category"], {})[_key_of(it, dup)] = it
    for it in new_items:
        if it["category"]:
            new_by_cat.setdefault(it["category"], {})[_key_of(it, dup)] = it
    gone = [c for c in old_by_cat if c not in new_by_cat]
    fresh = [c for c in new_by_cat if c not in old_by_cat]
    result, used = [], set()
    for oc in gone:
        okeys = set(old_by_cat[oc])
        best, best_ratio = None, 0.0
        for nc in fresh:
            if nc in used:
                continue
            nkeys = set(new_by_cat[nc])
            denom = max(len(okeys), len(nkeys))
            ratio = (len(okeys & nkeys) / denom) if denom else 0.0
            if ratio > best_ratio:
                best, best_ratio = nc, ratio
        if best and best_ratio >= RENAME_OVERLAP_RATIO:
            used.add(best)
            same = 0
            for k in set(old_by_cat[oc]) & set(new_by_cat[best]):
                o, n = old_by_cat[oc][k], new_by_cat[best][k]
                if (o["tbd"], o["price"], o["price_l"], o["options"], o["available"], o["note"]) == \
                   (n["tbd"], n["price"], n["price_l"], n["options"], n["available"], n["note"]):
                    same += 1
            result.append({"old": oc, "new": best, "count": len(new_by_cat[best]), "unchanged": same})
    return result


def _describe_options(old: dict, new: dict) -> str:
    """加購選項的差異文字：「加蛋 +10 → +15、新增 加飯 +10、移除 加麵」"""
    parts = []
    for name in list(old) + [n for n in new if n not in old]:
        o, n = old.get(name), new.get(name)
        if o is not None and n is not None:
            if o != n:
                parts.append(f"{name} {_fmt_diff(o)} → {_fmt_diff(n)}")
        elif o is None:
            parts.append(f"新增 {name} {_fmt_diff(n)}")
        else:
            parts.append(f"移除 {name}")
    return "、".join(parts) if parts else "順序改了"


def _fmt_diff(d) -> str:
    if d is None:
        return ""
    return f"+{d:f}" if d >= 0 else f"{d:f}"
