"""
User & Role Models

ユーザーと役職のモデル定義
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.app.models.base import Base, TimestampMixin, generate_uuid


class Role(Base, TimestampMixin):
    """役職マスタ

    権限レベル（level）:
        1 = 業務委託（自部署のみ、制限あり）
        2 = 一般社員（自部署のみ）
        3 = リーダー/課長（自部署＋直下部署）
        4 = 幹部/部長（自部署＋配下全部署）
        5 = 管理部（全組織、最高機密除く）
        6 = 代表/CFO（全組織、全情報）
    """

    __tablename__ = "roles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id"),
        nullable=False,
    )
    external_id = Column(String(100), unique=True, nullable=True)  # Supabase側のroles.id（同期用）
    name = Column(String(100), nullable=False)
    level = Column(Integer, default=1)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    organization = relationship("Organization", back_populates="roles")


class User(Base, TimestampMixin):
    """ユーザーマスタ"""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id"),
        nullable=False,
    )
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    chatwork_account_id = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    organization = relationship("Organization", back_populates="users")
    departments = relationship(
        "UserDepartment",
        back_populates="user",
        cascade="all, delete-orphan",
    )
