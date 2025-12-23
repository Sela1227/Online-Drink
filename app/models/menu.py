from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from decimal import Decimal


class Menu(Base):
    __tablename__ = "menus"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="menus")
    categories: Mapped[list["MenuCategory"]] = relationship(back_populates="menu", cascade="all, delete-orphan")
    items: Mapped[list["MenuItem"]] = relationship(back_populates="menu", cascade="all, delete-orphan")
    groups: Mapped[list["Group"]] = relationship(back_populates="menu")


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    menu: Mapped["Menu"] = relationship(back_populates="categories")
    items: Mapped[list["MenuItem"]] = relationship(back_populates="category")


class MenuItem(Base):
    __tablename__ = "menu_items"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("menu_categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_l: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)  # L 尺寸價格
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    menu: Mapped["Menu"] = relationship(back_populates="items")
    category: Mapped["MenuCategory | None"] = relationship(back_populates="items")
    options: Mapped[list["ItemOption"]] = relationship(back_populates="menu_item", cascade="all, delete-orphan")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="menu_item")


class ItemOption(Base):
    __tablename__ = "item_options"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    name: Mapped[str] = mapped_column(String(100))
    price_diff: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    menu_item: Mapped["MenuItem"] = relationship(back_populates="options")


# Avoid circular import
from app.models.store import Store
from app.models.group import Group
from app.models.order import OrderItem
