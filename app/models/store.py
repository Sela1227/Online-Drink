from datetime import datetime
from typing import TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Enum, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum

if TYPE_CHECKING:
    from app.models.menu import Menu
    from app.models.group import Group


class CategoryType(str, enum.Enum):
    DRINK = "drink"
    MEAL = "meal"
    GROUP_BUY = "group_buy"


class OptionType(str, enum.Enum):
    SUGAR = "sugar"
    ICE = "ice"


class Store(Base):
    __tablename__ = "stores"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[CategoryType] = mapped_column(Enum(CategoryType))
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    options: Mapped[list["StoreOption"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    toppings: Mapped[list["StoreTopping"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    menus: Mapped[list["Menu"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    groups: Mapped[list["Group"]] = relationship(back_populates="store")
    branches: Mapped[list["StoreBranch"]] = relationship(back_populates="store", cascade="all, delete-orphan")


class StoreBranch(Base):
    """店家分店"""
    __tablename__ = "store_branches"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(100))  # 分店名稱
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="branches")


class StoreTopping(Base):
    """店家加料選項（飲料用）"""
    __tablename__ = "store_toppings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(50))  # 珍珠、椰果、布丁
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)  # 加價
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="toppings")


class StoreOption(Base):
    __tablename__ = "store_options"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    option_type: Mapped[OptionType] = mapped_column(Enum(OptionType))
    option_value: Mapped[str] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="options")
