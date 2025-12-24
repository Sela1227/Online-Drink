from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, Enum, JSON, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from decimal import Decimal
import enum


class OrderStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    EDITING = "editing"


class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.DRAFT)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 修改時保留原訂單
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    group: Mapped["Group"] = relationship(back_populates="orders")
    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    
    @property
    def total_amount(self) -> Decimal:
        return sum(item.subtotal for item in self.items)
    
    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)


class OrderItem(Base):
    __tablename__ = "order_items"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    item_name: Mapped[str] = mapped_column(String(100))  # 冗餘存儲
    size: Mapped[str | None] = mapped_column(String(10), nullable=True)  # M 或 L
    sugar: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    order: Mapped["Order"] = relationship(back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship(back_populates="order_items")
    selected_options: Mapped[list["OrderItemOption"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")
    selected_toppings: Mapped[list["OrderItemTopping"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")
    
    @property
    def options_total(self) -> Decimal:
        """加購選項總價"""
        return sum(opt.price_diff for opt in self.selected_options)
    
    @property
    def toppings_total(self) -> Decimal:
        """加料總價"""
        return sum(t.price for t in self.selected_toppings)
    
    @property
    def subtotal(self) -> Decimal:
        return (self.unit_price + self.options_total + self.toppings_total) * self.quantity


class OrderItemOption(Base):
    __tablename__ = "order_item_options"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"))
    item_option_id: Mapped[int] = mapped_column(ForeignKey("item_options.id"))
    option_name: Mapped[str] = mapped_column(String(100))  # 冗餘存儲
    price_diff: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # 冗餘存儲
    
    # Relationships
    order_item: Mapped["OrderItem"] = relationship(back_populates="selected_options")


class OrderItemTopping(Base):
    """訂單品項的加料選擇"""
    __tablename__ = "order_item_toppings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"))
    store_topping_id: Mapped[int | None] = mapped_column(ForeignKey("store_toppings.id"), nullable=True)
    topping_name: Mapped[str] = mapped_column(String(100))  # 冗餘存儲
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # 冗餘存儲
    
    # Relationships
    order_item: Mapped["OrderItem"] = relationship(back_populates="selected_toppings")


# Avoid circular import
from app.models.group import Group
from app.models.user import User
from app.models.menu import MenuItem
