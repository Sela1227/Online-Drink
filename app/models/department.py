"""部門/群組模型"""
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.group import Group


class DeptRole(str, enum.Enum):
    """部門角色"""
    MEMBER = "member"      # 一般成員
    LEADER = "leader"      # 小組長（可管理成員）


class Department(Base):
    """部門/群組"""
    __tablename__ = "departments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)  # 公開群組，所有人可見
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    members: Mapped[list["UserDepartment"]] = relationship(back_populates="department", cascade="all, delete-orphan")
    groups: Mapped[list["GroupDepartment"]] = relationship(back_populates="department", cascade="all, delete-orphan")
    
    @property
    def member_count(self) -> int:
        return len(self.members)
    
    @property
    def leader_count(self) -> int:
        return len([m for m in self.members if m.role == DeptRole.LEADER])


class UserDepartment(Base):
    """用戶-部門關聯"""
    __tablename__ = "user_departments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    role: Mapped[DeptRole] = mapped_column(SQLEnum(DeptRole), default=DeptRole.MEMBER)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship()
    department: Mapped["Department"] = relationship(back_populates="members")


class GroupDepartment(Base):
    """團單-部門關聯（團單顯示給哪些部門）"""
    __tablename__ = "group_departments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    
    # Relationships
    group: Mapped["Group"] = relationship()
    department: Mapped["Department"] = relationship(back_populates="groups")


class StoreDepartment(Base):
    """店家-部門關聯（店家顯示給哪些部門）"""
    __tablename__ = "store_departments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    
    # Relationships
    department: Mapped["Department"] = relationship()
