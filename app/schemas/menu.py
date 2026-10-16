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
UNCLEAR_PRICE_MSG = "AI 看不清這個價格（填了 ?），請對照照片改成數字或 \"時價\""  # V2.16.1 B-7；admin 用它分流


def _to_bool(v, default=False) -> bool:
    """布林容錯：true/false 以外也收 "true"/"false"/"1"/"0"/"yes"/"no"/"是"/"否"，None 用預設"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    t = str(v).strip().lower()
    if t in ("true", "1", "yes", "y", "是", "時價", "t"):
        return True
    if t in ("false", "0", "no", "n", "否", "f", ""):
        return False
    raise ValueError(f"看不懂的布林值「{v}」，請填 true 或 false")


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
    # V2.16.1 B-7：AI 指令要求「看不清填 ?」——這裡給專屬錯誤，預覽頁才能把它們集中成一張「請對照照片」卡，
    # 而不是悄悄變 0（0 代表免費）或混在一般格式錯誤裡
    if t.replace(" ", "").replace("？", "?").strip("?") == "" and "?" in t.replace("？", "?"):
        raise ValueError(UNCLEAR_PRICE_MSG)
    t2 = t.replace(" ", "")
    # V2.14.1 P2-1：逗號只接受標準千分位（1,200）。"30,50" 是 AI 寫 M/L 兩價的常見寫法，
    # 一律刪逗號會變 3050 而且分析器不會警告
    if "," in t2:
        core = re.sub(r"^(?:nt\$?|ntd|twd|\$|＄)", "", t2, flags=re.I)
        core = re.sub(r"(?:元|塊|圓|nt|ntd|twd|\$)$", "", core, flags=re.I)
        if not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", core):
            raise ValueError(f"看不懂的價格「{v}」——若是 M/L 兩種價格，請分別填 price 與 price_l")
        t2 = t2.replace(",", "")
    m = _PRICE_RE.match(t2)
    if m:
        try:
            return Decimal(m.group(1))
        except InvalidOperation:
            pass
    raise ValueError(f"看不懂的價格「{v}」——請改成純數字，時價請填 \"時價\"")


PRICE_MAX = Decimal("999999")


def _check_name(v, what="名稱"):
    v = (v or "").strip() if isinstance(v, str) else v
    if not isinstance(v, str) or not v:
        raise ValueError(f"{what}不能是空白")
    if len(v) > 100:
        raise ValueError(f"{what}最多 100 字（目前 {len(v)} 字）")
    return v


def _check_price_range(v, what="價格"):
    if v is None:
        return None
    if not v.is_finite():
        raise ValueError(f"{what}不是有效數字")
    if v < 0:
        raise ValueError(f"{what}不能是負數（{v}）")
    if v > PRICE_MAX:
        raise ValueError(f"{what}超過上限 {PRICE_MAX:,}（{v}）")
    return v


class ItemOptionImport(BaseModel):
    name: str
    price_diff: Decimal = Decimal("0")

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _check_name(v, "選項名稱")

    @field_validator("price_diff", mode="before")
    @classmethod
    def _parse_diff(cls, v):
        r = parse_price_input(v)
        if r is TBD:
            raise ValueError("加購價差不能是時價")
        r = Decimal("0") if r is None else r
        # 價差允許負（折扣，分析器會提醒），只擋非有限與超大
        if not r.is_finite() or abs(r) > PRICE_MAX:
            raise ValueError(f"加購價差不是有效金額（{v}）")
        return r


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
        if not data.get("note") and data.get("description") is not None:
            data["note"] = data.pop("description")
        else:
            data.pop("description", None)
        # V2.14.1 P1-5：price_tbd 可能是字串 "false"（AI 常把布林寫成字串），truthy 判斷會把價格清成 0
        data["price_tbd"] = _to_bool(data.get("price_tbd"))
        data["is_available"] = _to_bool(data.get("is_available"), default=True)
        # 價格容錯
        tbd_keys = []
        for key in ("price", "price_l"):
            if key in data:
                r = parse_price_input(data[key])
                if r is TBD:
                    data[key] = Decimal("0")
                    tbd_keys.append(key)
                else:
                    data[key] = r
        # V2.14.1 P2-2：只有 price_l 是時價、price 是數字 → 不支援（定價只有一個價），報錯而不是把整項變時價
        if "price_l" in tbd_keys and "price" not in tbd_keys and not data["price_tbd"]:
            raise ValueError("L 尺寸不支援單獨時價——整個品項是時價就把 price 填 \"時價\"，否則 price_l 填數字")
        if "price" in tbd_keys:
            data["price_tbd"] = True
        if data["price_tbd"]:
            data["price"] = Decimal("0")
            data["price_l"] = None
        return data

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _check_name(v, "品項名稱")

    @field_validator("price", "price_l")
    @classmethod
    def _price_range(cls, v, info):
        # V2.14.1 P2-3：負數原本靠分析器當 blocker、超大數到 PostgreSQL Numeric(10,2) 才爆 500
        return _check_price_range(v, "L 尺寸價格" if info.field_name == "price_l" else "價格")

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

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _check_name(v, "分類名稱")


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
