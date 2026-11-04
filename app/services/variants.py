"""杯型／規格（V2.31.0，菜單匯入回饋 2026-11-04）

一個品項可以有多個規格，每個規格一個標籤與價格：
  中杯／大杯／特大杯、Solo／Doppio、L杯／瓶裝、碗裝／分享號……標籤由菜單資料決定，不寫死。

資料來源有三種，統一成 [(label, price), ...]：
  1. 有 menu_item_variants 列 → 照列（V2.31.0 起匯入給 variants 的品項）
  2. 舊菜單只有 price／price_l → [("M", price), ("L", price_l)]（Sela 選：舊菜單維持 M／L，舊訂單、複製、統計都對得起來）
  3. 只有 price → [(None, price)]（單一價、沒有標籤，跟以前一樣）

不變式：有 variants 的品項，MenuItem.price = 第一個規格的價格、price_l = None——
所以只讀 price 的地方（時價、統計、最低價）不用改。
"""
from decimal import Decimal

LABEL_MAX = 30


def choices_from(price, price_l, variants) -> list[tuple[str | None, Decimal]]:
    """variants：[(label, price)] 或 None；price／price_l：舊欄位"""
    if variants:
        return [(lb, Decimal(str(p))) for lb, p in variants]
    if price_l is not None:
        return [("M", Decimal(str(price or 0))), ("L", Decimal(str(price_l)))]
    return [(None, Decimal(str(price or 0)))]


def item_choices(item) -> list[tuple[str | None, Decimal]]:
    """ORM MenuItem → 規格清單"""
    vs = getattr(item, "variants", None) or []
    return choices_from(item.price, item.price_l, [(v.label, v.price) for v in vs])


def resolve(item, label):
    """點餐送來的規格標籤 → (label, price)。

    找得到就用；送空的、品項只有一種規格 → 用那一種（單一規格也保留標籤，核對單印得出「大杯」）；
    多規格卻送了不存在的標籤 → None（呼叫端回 400）。
    """
    chs = item_choices(item)
    label = (label or "").strip() or None
    for lb, p in chs:
        if lb == label:
            return lb, p
    if len(chs) == 1:
        return chs[0]
    if label is None:
        return chs[0]  # 沒選 → 第一個（跟以前沒選尺寸就算 M 一樣）
    return None


def carry_over(item, old_label):
    """複製訂單／開團：舊規格標籤套到新版本品項——同名就沿用，找不到就用第一個規格。"""
    chs = item_choices(item)
    for lb, p in chs:
        if lb == old_label:
            return lb, p
    return chs[0]


def fmt(chs, money=lambda d: f"{d.normalize():f}") -> str:
    """[("中杯",125),("大杯",140)] → 「中杯 $125／大杯 $140」；單一無標籤 → 「$85」"""
    return "／".join((f"{lb} " if lb else "") + f"${money(p)}" for lb, p in chs)
