from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.group import Group
    from app.models.order import Order


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    line_user_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))  # LINE 原始名稱
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 自訂暱稱
    picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
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
