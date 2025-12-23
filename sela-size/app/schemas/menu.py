from pydantic import BaseModel
from typing import Literal
from decimal import Decimal


class ItemOptionImport(BaseModel):
    name: str
    price_diff: Decimal = Decimal("0")


class MenuItemImport(BaseModel):
    name: str
    price: Decimal
    price_l: Decimal | None = None  # L 尺寸價格
    options: list[ItemOptionImport] | None = None


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
