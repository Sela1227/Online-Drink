from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum


class FeedbackType(str, enum.Enum):
    BUG = "bug"              # 功能異常
    SUGGESTION = "suggestion" # 建議功能
    OTHER = "other"          # 其他


class FeedbackStatus(str, enum.Enum):
    OPEN = "open"            # 待處理
    IN_PROGRESS = "in_progress"  # 處理中
    RESOLVED = "resolved"    # 已解決
    CLOSED = "closed"        # 已關閉


class Feedback(Base):
    __tablename__ = "feedbacks"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[FeedbackType] = mapped_column(Enum(FeedbackType), default=FeedbackType.BUG)
    status: Mapped[FeedbackStatus] = mapped_column(Enum(FeedbackStatus), default=FeedbackStatus.OPEN)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="feedbacks")
