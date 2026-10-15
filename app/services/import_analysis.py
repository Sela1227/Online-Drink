# -*- coding: utf-8 -*-
"""匯入菜單的品質分析與錯誤定位（V2.12.0）。

「蘭花干是不是有兩個」這種問題應該由系統回答，不該靠人逐條核對。
"""
from decimal import Decimal


def analyze_menu_content(content) -> dict:
    """回傳 {"blockers": [...], "warnings": [...]}。

    blockers：一定是錯的，擋下不讓確認。
    warnings：可能是刻意的（例如魯味的「米血」在不同價格區各出現一次），提醒但放行。
    """
    blockers: list[str] = []
    warnings: list[str] = []

    categories = list(content.categories or [])
    loose = list(content.items or [])

    # 分類層級
    seen_cat: dict[str, int] = {}
    for idx, cat in enumerate(categories, 1):
        cname = (cat.name or "").strip()
        if not cat.items:
            warnings.append(f"分類「{cname}」（第 {idx} 個）是空的，沒有任何品項")
        if cname in seen_cat:
            blockers.append(f"分類「{cname}」出現兩次（第 {seen_cat[cname]} 與第 {idx} 個），請合併")
        else:
            seen_cat[cname] = idx

    # 品項層級：同分類同名擋下、跨分類同名警告
    name_locations: dict[str, list[str]] = {}
    unavailable: list[str] = []

    def _check_item(item, where: str, key: str):
        iname = (item.name or "").strip()
        if not iname:
            blockers.append(f"{where}有品項名稱是空白的")
            return
        name_locations.setdefault(iname, []).append(key)

        # V2.14.0：停售品項另外彙整一條提醒；時價品項不做價格檢查
        if getattr(item, "is_available", True) is False:
            unavailable.append(iname)
        price = item.price if item.price is not None else Decimal("0")
        if getattr(item, "price_tbd", False):
            return
        if price < 0:
            blockers.append(f"{where}「{iname}」價格是負數（{price}）")
        elif price == 0:
            warnings.append(f"{where}「{iname}」價格是 0——會當成免費；若是時價請改填 \"時價\"")
        if item.price_l is not None:
            if item.price_l < price:
                warnings.append(f"{where}「{iname}」L 尺寸價（{item.price_l}）低於 M 尺寸價（{price}），請確認沒填反")
            elif item.price_l == price:
                warnings.append(f"{where}「{iname}」L 尺寸價與 M 尺寸價相同（{price}），可考慮只填 price")
        for opt in (item.options or []):
            if opt.price_diff is not None and opt.price_diff < 0:
                warnings.append(f"{where}「{iname}」的選項「{opt.name}」價差為負（{opt.price_diff}），請確認是否為折扣")

    for cat in categories:
        cname = (cat.name or "").strip()
        local: dict[str, int] = {}
        for item in cat.items or []:
            iname = (item.name or "").strip()
            if iname:
                local[iname] = local.get(iname, 0) + 1
            _check_item(item, f"分類「{cname}」的", f"分類「{cname}」")
        for iname, cnt in local.items():
            if cnt > 1:
                blockers.append(f"分類「{cname}」內「{iname}」重複出現 {cnt} 次，請刪除重複的")

    loose_local: dict[str, int] = {}
    for item in loose:
        iname = (item.name or "").strip()
        if iname:
            loose_local[iname] = loose_local.get(iname, 0) + 1
        _check_item(item, "無分類的", "無分類")
    for iname, cnt in loose_local.items():
        if cnt > 1:
            blockers.append(f"無分類品項「{iname}」重複出現 {cnt} 次，請刪除重複的")

    for iname, locs in name_locations.items():
        distinct = list(dict.fromkeys(locs))
        if len(distinct) > 1:
            warnings.append(f"「{iname}」同時出現在 {'、'.join(distinct)}（跨分類同名，若是刻意的可忽略）")

    if unavailable:
        shown = "、".join(unavailable[:6]) + ("…" if len(unavailable) > 6 else "")
        warnings.append(f"{len(unavailable)} 個品項標記停售（is_available: false），團員點餐時看不到：{shown}")

    return {"blockers": blockers, "warnings": warnings}


# ── 錯誤定位：把 Pydantic 的 loc 翻成帶名稱的路徑 ──

_FIELD = {
    "menu": "菜單", "categories": "分類", "items": "品項", "name": "名稱",
    "price": "價格", "price_l": "L 尺寸價格", "options": "選項", "price_diff": "價差",
    "store": "店家", "store_id": "店家編號", "category": "類別", "mode": "模式",
    "logo_url": "商標網址", "sugar_options": "甜度選項", "ice_options": "冰塊選項",
    "toppings": "加料",
}


def describe_loc(loc: tuple, raw: dict) -> str:
    """把 ('menu','categories',2,'items',5,'price') 翻成
    「分類[3]『小菜』→ 品項[6]『黃金泡菜』→ 價格」。

    原本只翻成「第 3 個分類的第 6 個品項的價格」，使用者要自己去數。
    這裡順著 loc 走進原始資料把名稱撈出來。
    """
    parts = []
    node = raw
    i = 0
    while i < len(loc):
        key = loc[i]
        nxt = loc[i + 1] if i + 1 < len(loc) else None
        if isinstance(key, str):
            label = _FIELD.get(key, key)
            child = node.get(key) if isinstance(node, dict) else None
            if isinstance(nxt, int):
                elem = child[nxt] if isinstance(child, list) and nxt < len(child) else None
                nm = elem.get("name") if isinstance(elem, dict) else None
                parts.append(f"{label}[{nxt + 1}]" + (f"「{nm}」" if nm else ""))
                node = elem
                i += 2
                continue
            parts.append(label)
            node = child
        i += 1
    return " → ".join(parts) if parts else "資料"


def json_error_context(text: str, lineno: int, radius: int = 3) -> list[str]:
    """JSON 解析失敗時，回傳出錯行前後幾行原文（含行號，出錯行標記）。"""
    lines = text.split("\n")
    lo = max(1, lineno - radius)
    hi = min(len(lines), lineno + radius)
    out = []
    for n in range(lo, hi + 1):
        marker = "▶" if n == lineno else " "
        out.append(f"{marker} {n:>4} | {lines[n - 1][:120]}")
    return out
