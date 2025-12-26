from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, JSON, ForeignKey, Integer
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
    
    def is_leader_of(self, department_id: int, db) -> bool:
        """檢查是否為該部門的小組長"""
        from app.models.department import UserDepartment, DeptRole
        ud = db.query(UserDepartment).filter(
            UserDepartment.user_id == self.id,
            UserDepartment.department_id == department_id
        ).first()
        return ud and ud.role == DeptRole.LEADER


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
