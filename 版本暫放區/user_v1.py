from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.group import Group
    from app.models.order import Order


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    line_user_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    preset: Mapped["UserPreset | None"] = relationship(back_populates="user", uselist=False)
    groups: Mapped[list["Group"]] = relationship(back_populates="owner")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class UserPreset(Base):
    __tablename__ = "user_presets"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    time_presets: Mapped[list] = mapped_column(JSON, default=list)
    # 預設: ["30分鐘後", "1小時後", "今天 12:00", "今天 17:00", "明天 12:00"]
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="preset")
