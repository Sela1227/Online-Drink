from pydantic import BaseModel, model_validator, field_validator
from typing import Literal
from decimal import Decimal, InvalidOperation
import re


# ===== 價格容錯（V2.14.0）=====
# AI 從菜單照片轉出來的價格常常不是純數字：「$30」「30元」「NT$30」「３０」「時價」。
# 能解析的自動轉，寫「時價」的轉成 price_tbd，其他文字才報錯並說明。
TBD_WORDS = ("時價", "市價", "依時價", "依市價", "未定", "未訂", "待定", "tbd", "market price")
_FULLWIDTH = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
_PRICE_RE = re.compile(r"^(?:nt\$?|ntd|twd|\$|＄|元)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:元|塊|圓|nt|ntd|twd|\$)?$", re.I)

TBD = object()  # parse_price_input 的哨兵：這個價格是「時價」


def parse_price_input(v):
    """把各種寫法的價格轉成 Decimal；時價回 TBD 哨兵；None 原樣回；解析不了拋 ValueError。"""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("價格不能是 true/false")
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    if not isinstance(v, str):
        raise ValueError("價格格式不正確")
    t = v.strip().translate(_FULLWIDTH)
    if t == "":
        return None
    if t.lower() in TBD_WORDS or t.replace(" ", "") in TBD_WORDS:
        return TBD
    t2 = t.replace(",", "").replace(" ", "")
    m = _PRICE_RE.match(t2)
    if m:
        try:
            return Decimal(m.group(1))
        except InvalidOperation:
            pass
    raise ValueError(f"看不懂的價格「{v}」——請改成純數字，時價請填 \"時價\"")


class ItemOptionImport(BaseModel):
    name: str
    price_diff: Decimal = Decimal("0")

    @field_validator("price_diff", mode="before")
    @classmethod
    def _parse_diff(cls, v):
        r = parse_price_input(v)
        if r is TBD:
            raise ValueError("加購價差不能是時價")
        return Decimal("0") if r is None else r


class MenuItemImport(BaseModel):
    name: str
    price: Decimal
    price_l: Decimal | None = None  # L 尺寸價格
    price_tbd: bool = False  # V2.14.0：時價（price 以 0 佔位，截止後團主定價回寫本團）
    is_available: bool = True  # V2.14.0：停售（團員看不到，但品項保留）
    note: str | None = None  # V2.14.0：品項說明（存 MenuItem.description，≤200 字）
    options: list[ItemOptionImport] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # description 當 note 的別名
        if data.get("note") is None and data.get("description") is not None:
            data["note"] = data.pop("description")
        else:
            data.pop("description", None)
        # 價格容錯
        for key in ("price", "price_l"):
            if key in data:
                r = parse_price_input(data[key])
                if r is TBD:
                    data[key] = Decimal("0")
                    data["price_tbd"] = True
                else:
                    data[key] = r
        if data.get("price_tbd"):
            data["price"] = Decimal("0")
            data["price_l"] = None
        return data

    @field_validator("note")
    @classmethod
    def _note_len(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            return None
        if len(v) > 200:
            raise ValueError("品項說明最多 200 字")
        return v


class MenuCategoryImport(BaseModel):
    name: str
    items: list[MenuItemImport]


class MenuContent(BaseModel):
    """菜單內容"""
    categories: list[MenuCategoryImport] | None = None
    items: list[MenuItemImport] | None = None  # 無分類品項


class MenuImport(BaseModel):
    """僅匯入菜單"""
    store_id: int
    mode: Literal["new", "replace"] = "new"
    menu: MenuContent


class FullImport(BaseModel):
    """完整匯入（店家 + 菜單）"""
    store: "StoreImport"
    menu: MenuContent


# Avoid circular import
from app.schemas.store import StoreImport
FullImport.model_rebuild()
