from pydantic import BaseModel
from typing import Literal


class StoreCreate(BaseModel):
    name: str
    category: Literal["drink", "meal"]
    logo_url: str | None = None
    sugar_options: list[str] | None = None
    ice_options: list[str] | None = None


class StoreImport(BaseModel):
    """完整匯入格式中的 store 欄位"""
    name: str
    category: Literal["drink", "meal"]
    logo_url: str | None = None
    sugar_options: list[str] | None = None
    ice_options: list[str] | None = None
