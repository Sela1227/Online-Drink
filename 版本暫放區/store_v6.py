from pydantic import BaseModel
from typing import Literal
from decimal import Decimal


class ToppingImport(BaseModel):
    """加料匯入格式"""
    name: str
    price: Decimal = Decimal("0")


class StoreCreate(BaseModel):
    name: str
    category: Literal["drink", "meal"]
    logo_url: str | None = None
    sugar_options: list[str] | None = None
    ice_options: list[str] | None = None
    toppings: list[ToppingImport] | None = None


class StoreImport(BaseModel):
    """完整匯入格式中的 store 欄位"""
    name: str
    category: Literal["drink", "meal"]
    logo_url: str | None = None
    sugar_options: list[str] | None = None
    ice_options: list[str] | None = None
    toppings: list[ToppingImport] | None = None
