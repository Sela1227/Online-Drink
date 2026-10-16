from pydantic import BaseModel, field_validator
from typing import Literal
from decimal import Decimal


def _store_name(v):
    v = (v or "").strip() if isinstance(v, str) else v
    if not isinstance(v, str) or not v:
        raise ValueError("店名不能是空白")
    if len(v) > 100:
        raise ValueError(f"店名最多 100 字（目前 {len(v)} 字）")
    return v


def _clean_options(v, what):
    """V2.15.1 審核 P2-5：甜冰選項去空白、去空字串、去重、每個最多 50 字（資料表 String(50)）"""
    if v is None:
        return None
    if not isinstance(v, (list, tuple)):
        raise ValueError(f"{what}應該是清單")
    out = []
    for item in v:
        t = str(item).strip() if item is not None else ""
        if not t:
            continue
        if len(t) > 50:
            raise ValueError(f"{what}「{t[:10]}…」超過 50 字")
        if t not in out:
            out.append(t)
    return out or None


def _clean_logo_url(v):
    if v is None:
        return None
    t = str(v).strip()
    if not t or not t.lower().startswith(("http://", "https://")) or len(t) > 500:
        return None  # 不是網址就當沒有（AI 常填 "無"、"N/A"）
    return t


class ToppingImport(BaseModel):
    """加料匯入格式"""
    name: str
    price: Decimal = Decimal("0")

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        from app.schemas.menu import _check_name
        v = _check_name(v, "加料名稱")
        if len(v) > 50:  # V2.15.1 審核 P2-5：資料表 String(50)，預覽放行確認才 500
            raise ValueError(f"加料名稱最多 50 字（目前 {len(v)} 字）")
        return v

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, v):
        # V2.14.1 P2-3：共用匯入端的價格容錯，並擋負數與超大
        from app.schemas.menu import parse_price_input, TBD, _check_price_range
        r = parse_price_input(v)
        if r is TBD:
            raise ValueError("加料價格不能是時價")
        return _check_price_range(Decimal("0") if r is None else r, "加料價格")


class StoreCreate(BaseModel):
    name: str
    category: Literal["drink", "meal", "group_buy"]
    logo_url: str | None = None
    sugar_options: list[str] | None = None
    ice_options: list[str] | None = None
    toppings: list[ToppingImport] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _store_name(v)

    @field_validator("sugar_options", "ice_options", mode="before")
    @classmethod
    def _opts(cls, v, info):
        return _clean_options(v, "甜度選項" if info.field_name == "sugar_options" else "冰塊選項")

    @field_validator("logo_url", mode="before")
    @classmethod
    def _logo(cls, v):
        return _clean_logo_url(v)


class StoreImport(BaseModel):
    """完整匯入格式中的 store 欄位"""
    name: str
    category: Literal["drink", "meal", "group_buy"]
    logo_url: str | None = None
    sugar_options: list[str] | None = None
    ice_options: list[str] | None = None
    toppings: list[ToppingImport] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _store_name(v)

    @field_validator("sugar_options", "ice_options", mode="before")
    @classmethod
    def _opts(cls, v, info):
        return _clean_options(v, "甜度選項" if info.field_name == "sugar_options" else "冰塊選項")

    @field_validator("logo_url", mode="before")
    @classmethod
    def _logo(cls, v):
        return _clean_logo_url(v)
