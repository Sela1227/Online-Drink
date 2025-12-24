"""
menu.py - 菜單模型
"""
from datetime import datetime
from typing import TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.store import Store


class Menu(Base):
    __tablename__ = "menus"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="menus")
    categories: Mapped[list["MenuCategory"]] = relationship(back_populates="menu", cascade="all, delete-orphan")


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    menu: Mapped["Menu"] = relationship(back_populates="categories")
    items: Mapped[list["MenuItem"]] = relationship(back_populates="category", cascade="all, delete-orphan")


class MenuItem(Base):
    __tablename__ = "menu_items"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("menu_categories.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_l: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    category: Mapped["MenuCategory"] = relationship(back_populates="items")
    options: Mapped[list["ItemOption"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class ItemOption(Base):
    """品項選項（加價項目）"""
    __tablename__ = "item_options"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    name: Mapped[str] = mapped_column(String(50))
    price_diff: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    item: Mapped["MenuItem"] = relationship(back_populates="options")
