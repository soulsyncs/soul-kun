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
    """役職マスタ"""

    __tablename__ = "roles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id"),
        nullable=False,
    )
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
