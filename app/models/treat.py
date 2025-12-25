from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TreatRecord(Base):
    """請客記錄"""
    __tablename__ = "treat_records"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    treat_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 請客者
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # 請客金額
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 備註
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    group: Mapped["Group"] = relationship()
    treat_user: Mapped["User"] = relationship()


# Avoid circular import
from app.models.group import Group
from app.models.user import User
