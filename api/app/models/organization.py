"""
Organization Models

組織階層連携用のモデル定義（Phase 3.5）
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Text,
    ForeignKey,
    DateTime,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Organization(Base, TimestampMixin):
    """組織（テナント）マスタ"""

    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=True)
    plan = Column(String(50), default="starter")
    is_active = Column(Boolean, default=True)

    # Relationships
    departments = relationship(
        "Department",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    users = relationship(
        "User",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    roles = relationship(
        "Role",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    sync_logs = relationship(
        "OrgChartSyncLog",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class Department(Base, TimestampMixin):
    """部署マスタ"""

    __tablename__ = "departments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=True)
    parent_department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    level = Column(Integer, default=1, nullable=False)
    path = Column(Text, nullable=False)  # LTREE型として使用
    display_order = Column(Integer, default=0)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = Column(UUID(as_uuid=False), nullable=True)
    updated_by = Column(UUID(as_uuid=False), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="departments")
    parent = relationship(
        "Department",
        remote_side=[id],
        backref="children",
    )
    user_departments = relationship(
        "UserDepartment",
        back_populates="department",
        cascade="all, delete-orphan",
    )
    access_scope = relationship(
        "DepartmentAccessScope",
        back_populates="department",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_departments_org", "organization_id"),
        Index("idx_departments_parent", "parent_department_id"),
    )


class UserDepartment(Base, TimestampMixin):
    """ユーザー所属部署"""

    __tablename__ = "user_departments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id = Column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_primary = Column(Boolean, default=True)
    role_in_dept = Column(String(100), nullable=True)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="departments")
    department = relationship("Department", back_populates="user_departments")

    __table_args__ = (
        Index("idx_user_departments_user", "user_id"),
        Index("idx_user_departments_dept", "department_id"),
    )


class DepartmentAccessScope(Base, TimestampMixin):
    """部署アクセススコープ"""

    __tablename__ = "department_access_scopes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    can_view_child_departments = Column(Boolean, default=True)
    can_view_sibling_departments = Column(Boolean, default=False)
    can_view_parent_departments = Column(Boolean, default=False)
    max_depth = Column(Integer, default=99)
    override_confidential_access = Column(Boolean, default=False)
    override_restricted_access = Column(Boolean, default=False)

    # Relationships
    department = relationship("Department", back_populates="access_scope")


class DepartmentHierarchy(Base):
    """部署階層（閉包テーブル）"""

    __tablename__ = "department_hierarchies"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ancestor_department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    descendant_department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    depth = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_hierarchy_ancestor",
            "ancestor_department_id",
        ),
        Index(
            "idx_hierarchy_descendant",
            "descendant_department_id",
        ),
    )


class OrgChartSyncLog(Base):
    """組織図同期ログ"""

    __tablename__ = "org_chart_sync_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sync_type = Column(String(50), nullable=False)  # full, incremental
    status = Column(String(50), nullable=False)  # in_progress, success, failed
    departments_added = Column(Integer, default=0)
    departments_updated = Column(Integer, default=0)
    departments_deleted = Column(Integer, default=0)
    users_added = Column(Integer, default=0)
    users_updated = Column(Integer, default=0)
    users_deleted = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    error_details = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    triggered_by = Column(UUID(as_uuid=False), nullable=True)
    source_system = Column(String(100), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    organization = relationship("Organization", back_populates="sync_logs")

    __table_args__ = (
        Index("idx_sync_logs_org", "organization_id"),
        Index("idx_sync_logs_status", "status"),
    )
