from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Vote(Base):
    """投票活動"""
    __tablename__ = "votes"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))  # 投票標題
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 說明
    deadline: Mapped[datetime] = mapped_column(DateTime)  # 投票截止時間
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_multiple: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否可多選
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)  # 公開或限定部門
    winner_store_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 勝出店家
    created_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 建立的團單
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    creator: Mapped["User"] = relationship()
    options: Mapped[list["VoteOption"]] = relationship(back_populates="vote", cascade="all, delete-orphan")
    departments: Mapped[list["VoteDepartment"]] = relationship(back_populates="vote", cascade="all, delete-orphan")
    
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
    def total_votes(self) -> int:
        return sum(len(opt.voters) for opt in self.options)


class VoteOption(Base):
    """投票選項（店家）"""
    __tablename__ = "vote_options"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    vote_id: Mapped[int] = mapped_column(ForeignKey("votes.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    added_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 誰提議的
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    vote: Mapped["Vote"] = relationship(back_populates="options")
    store: Mapped["Store"] = relationship()
    added_by: Mapped["User"] = relationship()
    voters: Mapped[list["VoteRecord"]] = relationship(back_populates="option", cascade="all, delete-orphan")
    
    @property
    def vote_count(self) -> int:
        return len(self.voters)


class VoteRecord(Base):
    """投票紀錄"""
    __tablename__ = "vote_records"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("vote_options.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    option: Mapped["VoteOption"] = relationship(back_populates="voters")
    user: Mapped["User"] = relationship()


# Avoid circular import
from app.models.user import User
from app.models.store import Store


class VoteDepartment(Base):
    """投票限定部門"""
    __tablename__ = "vote_departments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    vote_id: Mapped[int] = mapped_column(ForeignKey("votes.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    
    vote: Mapped["Vote"] = relationship(back_populates="departments")
    department: Mapped["Department"] = relationship()


from app.models.department import Department
