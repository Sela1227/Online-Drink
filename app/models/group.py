from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, Integer, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.store import CategoryType


class Group(Base):
    __tablename__ = "groups"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 分店 ID
    name: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 團主備註
    category: Mapped[CategoryType] = mapped_column(Enum(CategoryType))
    deadline: Mapped[datetime] = mapped_column(DateTime)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # 外送費
    delivery_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    
    # 飲料團設定
    default_sugar: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_ice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lock_sugar: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_ice: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="groups")
    menu: Mapped["Menu"] = relationship(back_populates="groups")
    owner: Mapped["User"] = relationship(back_populates="groups")
    orders: Mapped[list["Order"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    
    @property
    def is_expired(self) -> bool:
        from datetime import timezone, timedelta
        taipei_tz = timezone(timedelta(hours=8))
        now = datetime.now(taipei_tz).replace(tzinfo=None)
        return now > self.deadline
    
    @property
    def is_open(self) -> bool:
        return not self.is_closed and not self.is_expired
    
    @property
    def submitted_count(self) -> int:
        """已結單的人數"""
        from app.models.order import OrderStatus
        return len([o for o in self.orders if o.status == OrderStatus.SUBMITTED])
    
    @property
    def pending_count(self) -> int:
        """正在點餐的人數（購物車有東西但未結單）"""
        from app.models.order import OrderStatus
        return len([o for o in self.orders if o.status in (OrderStatus.DRAFT, OrderStatus.EDITING) and len(o.items) > 0])
    
    @property
    def delivery_fee_per_person(self) -> Decimal:
        """每人分攤的外送費"""
        if not self.delivery_fee or self.submitted_count == 0:
            return Decimal("0")
        return (self.delivery_fee / self.submitted_count).quantize(Decimal("1"))  # 四捨五入到整數
    
    @property
    def total_amount(self) -> Decimal:
        """團單總金額（含外送費）"""
        from app.models.order import OrderStatus
        subtotal = sum(
            o.total_amount for o in self.orders 
            if o.status == OrderStatus.SUBMITTED
        )
        return subtotal + (self.delivery_fee or Decimal("0"))
    
    @property
    def category_icon(self) -> str:
        """分類圖示"""
        if self.category == CategoryType.DRINK:
            return "🧋"
        elif self.category == CategoryType.MEAL:
            return "🍱"
        else:
            return "🛒"
    
    @property
    def category_name(self) -> str:
        """分類名稱"""
        if self.category == CategoryType.DRINK:
            return "飲料"
        elif self.category == CategoryType.MEAL:
            return "餐點"
        else:
            return "團購"


# Avoid circular import
from app.models.store import Store
from app.models.menu import Menu
from app.models.user import User
from app.models.order import Order
