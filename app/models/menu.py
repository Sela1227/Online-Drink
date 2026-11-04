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
    # V2.15.1 審核 P2-1：模板直接迭代 relationship，順序只靠這裡的 order_by。
    # 沒寫的話 PostgreSQL 回的是實體儲存順序——代購團主一改價，那個品項就跳到最後（坑 #40）
    categories: Mapped[list["MenuCategory"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan",
        order_by=lambda: (MenuCategory.sort_order, MenuCategory.id))
    items: Mapped[list["MenuItem"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan",
        order_by=lambda: (MenuItem.sort_order, MenuItem.id))
    groups: Mapped[list["Group"]] = relationship(back_populates="menu")


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    menu: Mapped["Menu"] = relationship(back_populates="categories")
    # V2.31.1：selectin——團頁逐分類讀品項，lazy 時每個分類各查一次（再各觸發一次規格／選項的 selectin）
    items: Mapped[list["MenuItem"]] = relationship(
        back_populates="category", lazy="selectin", order_by=lambda: (MenuItem.sort_order, MenuItem.id))


class MenuItem(Base):
    __tablename__ = "menu_items"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("menu_categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_l: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)  # L 尺寸價格
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 說明（V2.7.0 代購）
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 品項圖（V2.7.0，Cloudinary）
    stock_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 數量上限（NULL=不限，已送出佔用）
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)  # 上/下架
    price_tbd: Mapped[bool] = mapped_column(Boolean, default=False)  # 價格未訂（V2.9.0 代購：定價後回寫訂單）
    # V2.31.0（菜單匯入回饋 3-2）：false＝這個品項不提供店家加料（星巴克純茶「不提供客製化」）
    allow_toppings: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    
    # Relationships
    menu: Mapped["Menu"] = relationship(back_populates="items")
    category: Mapped["MenuCategory | None"] = relationship(back_populates="items")
    # V2.31.1（內部審核 V-2）：selectin——團頁／工作台每個品項都讀，預設 lazy 是每項各查一次（60 項＝60 條）
    options: Mapped[list["ItemOption"]] = relationship(
        back_populates="menu_item", cascade="all, delete-orphan", lazy="selectin",
        order_by=lambda: (ItemOption.sort_order, ItemOption.id))
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="menu_item")
    # V2.31.0：杯型／規格。沒有列的舊品項用 price／price_l（app/services/variants.py）
    variants: Mapped[list["MenuItemVariant"]] = relationship(
        back_populates="menu_item", cascade="all, delete-orphan", lazy="selectin",
        order_by=lambda: (MenuItemVariant.sort_order, MenuItemVariant.id))

    @property
    def size_choices(self):
        """[(label, price)]——模板與計價都只看這個"""
        from app.services.variants import item_choices
        return item_choices(self)


class MenuItemVariant(Base):
    """V2.31.0：品項規格（中杯／大杯／特大杯、Solo／Doppio、L杯／瓶裝…），標籤由匯入資料決定"""
    __tablename__ = "menu_item_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), index=True)
    label: Mapped[str] = mapped_column(String(30))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    menu_item: Mapped["MenuItem"] = relationship(back_populates="variants")


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
