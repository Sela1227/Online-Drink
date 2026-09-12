from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, Integer, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.store import CategoryType


def taipei_now():
    """現在的台北牆上時間（naive），用來跟 `Group.deadline` 比對。

    V2.10.1：`groups.deadline` 存的是台北牆上時間的 naive datetime，不是 UTC。
    拿 `datetime.utcnow()` 去比會差 8 小時 —— V2.10.0 的清除測試團與飲料選項
    團數統計就是這樣錯的（坑 #25）。**凡是比對 deadline 一律用這個函式。**

    注意：`announcements.expires_at`、`orders.created_at` 等欄位存的是 UTC，
    那些場合要用 `datetime.utcnow()`，不要用這個。兩套慣例並存是已知的結構
    問題，V2.11 的「時間單一真相」會處理。
    """
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


def taipei_to_utc(dt):
    """台北牆上時間的 naive datetime → UTC 的 naive datetime。

    V2.10.2：用於「使用者心智模型是台北日曆邊界，但要比對 UTC 欄位」的場合，
    例如統計頁的「本月」＝台北 9/1 00:00，換算後要拿 UTC 8/31 16:00 去比對
    `Group.created_at`。

    注意這**不是**把所有台北計算都改成 `utcnow()` 就好 —— 日曆邊界仍然要用
    台北算（那才是使用者要的月份），算完再用這個函式轉。至於滾動窗（近 30 天）
    則直接從 `utcnow()` 起算即可，不需要經過這裡。
    """
    if dt is None:
        return None
    from datetime import timezone, timedelta
    return dt.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(
        timezone.utc
    ).replace(tzinfo=None)


class Group(Base):
    __tablename__ = "groups"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    store_name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 店名快照（店家刪除後保留顯示）
    menu_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 分店 ID
    name: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 團主備註
    category: Mapped[CategoryType] = mapped_column(Enum(CategoryType))
    deadline: Mapped[datetime] = mapped_column(DateTime)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否公開（所有人可見）
    
    # 外送費
    delivery_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    
    # 每單金額上限（V2.1.0）
    order_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)  # 每單上限，NULL=不限
    allow_over_limit: Mapped[bool] = mapped_column(Boolean, default=False)  # 可否超過（超過部分自行貼補）
    
    # 整單折扣（V2.3.0）例：95 = 全單 95 折，NULL/100 = 無折扣
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    
    # 缺貨候補（V2.4.0）
    enable_backup: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否開啟候補
    backup_count: Mapped[int] = mapped_column(Integer, default=2)  # 每品項候補上限 1-3
    
    # 飲料團設定
    default_sugar: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_ice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lock_sugar: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_ice: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Phase 3：趣味功能
    is_blind_mode: Mapped[bool] = mapped_column(Boolean, default=False)  # 盲點模式
    enable_lucky_draw: Mapped[bool] = mapped_column(Boolean, default=False)  # 啟用隨機免單
    lucky_draw_count: Mapped[int] = mapped_column(Integer, default=1)  # 免單人數
    lucky_winner_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # 中獎者 ID（逗號分隔）
    treat_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 請客者 ID
    
    # 湊團制
    min_members: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 最少成團人數
    auto_extend: Mapped[bool] = mapped_column(Boolean, default=False)  # 未達人數是否自動延長
    
    # Phase 5：自動催單
    auto_remind_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 截止前 N 分鐘催單
    last_remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 上次催單時間
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    store: Mapped["Store"] = relationship(back_populates="groups")
    menu: Mapped["Menu"] = relationship(back_populates="groups")
    owner: Mapped["User"] = relationship(back_populates="groups")
    orders: Mapped[list["Order"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    
    @property
    def is_expired(self) -> bool:
        return taipei_now() > self.deadline
    
    @property
    def is_open(self) -> bool:
        return not self.is_closed and not self.is_expired
    
    @property
    def submitted_count(self) -> int:
        """已結單的人數"""
        from app.models.order import OrderStatus
        return len([o for o in self.orders if o.status == OrderStatus.SUBMITTED])
    
    @property
    def has_enough_members(self) -> bool:
        """是否達到最低成團人數"""
        if not self.min_members:
            return True
        return self.submitted_count >= self.min_members
    
    @property
    def members_needed(self) -> int:
        """還差幾人成團"""
        if not self.min_members:
            return 0
        return max(0, self.min_members - self.submitted_count)
    
    @property
    def pending_count(self) -> int:
        """正在點餐的人數（購物車有東西但未結單）"""
        from app.models.order import OrderStatus
        return len([o for o in self.orders if o.status in (OrderStatus.DRAFT, OrderStatus.EDITING) and len(o.items) > 0])
    
    @property
    def delivery_fee_per_person(self) -> Decimal:
        """每人分攤的外送費（約略值，收款明細採餘數精確分配）"""
        if not self.delivery_fee or self.submitted_count == 0:
            return Decimal("0")
        return (self.delivery_fee / self.submitted_count).quantize(Decimal("1"))  # 四捨五入到整數
    
    @property
    def total_amount(self) -> Decimal:
        """團單總金額（含外送費）。V2.4.1 修：改用折後金額，與收款明細/請客紀錄一致"""
        from app.models.order import OrderStatus
        subtotal = sum(
            o.final_amount for o in self.orders 
            if o.status == OrderStatus.SUBMITTED
        )
        return subtotal + (self.delivery_fee or Decimal("0"))
    
    @property
    def store_display_name(self) -> str:
        """店家顯示名稱：店家還在用關聯名稱，店家已刪除則用快照名稱"""
        if self.store is not None:
            return self.store.name
        return self.store_name or "（店家已移除）"

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
    
    def get_departments(self, db):
        """取得團單顯示給哪些部門"""
        from app.models.department import GroupDepartment
        return db.query(GroupDepartment).filter(GroupDepartment.group_id == self.id).all()
    
    def is_visible_to(self, user, db) -> bool:
        """檢查用戶是否可以看到此團單"""
        # 公開團，所有人可見
        if self.is_public:
            return True
        
        # 團主自己可見
        if self.owner_id == user.id:
            return True
        
        # 管理員可見
        if user.is_admin:
            return True
        
        # 檢查部門是否交集
        from app.models.department import GroupDepartment, UserDepartment
        group_dept_ids = {gd.department_id for gd in db.query(GroupDepartment).filter(GroupDepartment.group_id == self.id).all()}
        user_dept_ids = {ud.department_id for ud in db.query(UserDepartment).filter(UserDepartment.user_id == user.id).all()}
        
        return bool(group_dept_ids & user_dept_ids)


# Avoid circular import
from app.models.store import Store
from app.models.menu import Menu
from app.models.user import User
from app.models.order import Order
