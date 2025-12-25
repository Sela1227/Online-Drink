from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class GroupTemplate(Base):
    """開團模板"""
    __tablename__ = "group_templates"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100))  # 模板名稱
    
    # 店家設定
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # 團單設定
    group_name: Mapped[str] = mapped_column(String(100))  # 預設團名
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)  # 預設開放時間（分鐘）
    
    # 飲料設定
    default_sugar: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_ice: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lock_sugar: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_ice: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # 趣味功能
    is_blind_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_lucky_draw: Mapped[bool] = mapped_column(Boolean, default=False)
    lucky_draw_count: Mapped[int] = mapped_column(Integer, default=1)
    min_members: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_extend: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # 可見範圍
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # 使用次數
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship()
    store: Mapped["Store"] = relationship()


# Avoid circular import
from app.models.user import User
from app.models.store import Store
