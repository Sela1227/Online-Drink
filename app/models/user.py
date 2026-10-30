from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, JSON, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.group import Group
    from app.models.order import Order
    from app.models.store import Store


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    line_user_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))  # LINE 原始名稱
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 自訂暱稱
    picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)  # 訪客模式
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cities: Mapped[str | None] = mapped_column(Text, nullable=True)  # V2.26.0：我會訂的縣市（JSON 陣列）；空＝全部
    
    # Relationships
    preset: Mapped["UserPreset | None"] = relationship(back_populates="user", uselist=False)
    groups: Mapped[list["Group"]] = relationship(back_populates="owner")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    
    @property
    def show_name(self) -> str:
        """顯示名稱（優先使用暱稱）"""
        return self.nickname or self.display_name
    
    @property
    def is_online(self) -> bool:
        """判斷用戶是否在線（30分鐘內有活動）"""
        if not self.last_active_at:
            return False
        from datetime import timedelta
        return (datetime.utcnow() - self.last_active_at) < timedelta(minutes=30)
    
    def get_departments(self, db):
        """取得用戶所屬的部門"""
        from app.models.department import UserDepartment
        return db.query(UserDepartment).filter(UserDepartment.user_id == self.id).all()


class UserPreset(Base):
    __tablename__ = "user_presets"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    time_presets: Mapped[list] = mapped_column(JSON, default=list)
    # 預設: ["30分鐘後", "1小時後", "今天 12:00", "今天 17:00", "明天 12:00"]
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="preset")


class SystemSetting(Base):
    """系統設定（單一 row）"""
    __tablename__ = "system_settings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    announcement: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Announcement(Base):
    """公告歷史紀錄"""
    __tablename__ = "announcements"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)  # 置頂
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 過期時間
    
    # Relationships
    created_by: Mapped["User"] = relationship()


class Feedback(Base):
    """問題回報"""
    __tablename__ = "feedbacks"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship()


class UserFavorite(Base):
    """用戶收藏店家"""
    __tablename__ = "user_favorites"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship()
    store: Mapped["Store"] = relationship()


class StoreRecommendation(Base):
    """使用者推薦店家"""
    __tablename__ = "store_recommendations"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    store_name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20))  # drink, meal, group_buy
    menu_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 菜單連結
    menu_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 菜單圖片（第一張，相容舊資料）
    menu_image_urls: Mapped[str | None] = mapped_column(Text, nullable=True)  # V2.16.2：多張，JSON 陣列
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 備註
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, rejected
    reject_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_store_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 審核通過後的店家ID
    
    # Relationships
    user: Mapped["User"] = relationship()

    @property
    def menu_images(self) -> list[str]:
        """V2.16.2：所有菜單照片。新欄位有就用新欄位，沒有退回單張（舊資料不用補）"""
        import json
        if self.menu_image_urls:
            try:
                urls = json.loads(self.menu_image_urls)
                if isinstance(urls, list):
                    return [u for u in urls if isinstance(u, str) and u]
            except (TypeError, ValueError):
                pass
        return [self.menu_image_url] if self.menu_image_url else []


class LoginAttempt(Base):
    """一次 LINE 登入嘗試的結果（V2.23.1）

    Android Chrome 從 LINE app 授權跳回來時，會把同一個 /auth/callback 連送兩次
    （第一次自己取消、第二次帶同一組一次性授權碼）。第一次在伺服器端照樣登入成功，
    但 cookie 被瀏覽器丟掉；第二次拿用過的授權碼去換，LINE 回 400 → 導回登入頁 → 無限迴圈。
    這張表讓第二次可以等第一次的結果並沿用，而不是再去跟 LINE 換一次。

    key 是 sha256(state + code)：要同時拿到這次登入的 state cookie 與授權碼才對得上。
    只存 user_id 與要導去的頁面，不存 token；超過 10 分鐘的列在每次登入時清掉。
    """
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending / done / failed
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
