"""
Goal Models

目標達成支援用のモデル定義（Phase 2.5）

設計書: docs/05_phase2-5_goal_achievement.md (v1.5)
"""

from datetime import date, time
from decimal import Decimal
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Text,
    Date,
    Time,
    ForeignKey,
    DateTime,
    Index,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import DECIMAL
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Goal(Base, TimestampMixin):
    """目標管理テーブル

    目標の種類:
        - individual: 個人目標（スタッフ各自が設定）
        - department: 部署目標（部署責任者が設定）
        - company: 会社目標（経営陣が設定）

    目標タイプ:
        - numeric: 数値目標（粗利300万円、獲得10件など）
        - deadline: 期限目標（○月○日までに完了）
        - action: 行動目標（毎日○○をする）

    機密区分（4段階）:
        - public: 公開
        - internal: 社内限定（デフォルト）
        - confidential: 機密
        - restricted: 極秘
    """

    __tablename__ = "goals"

    # 主キー
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)

    # テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 目標の所有者
    user_id = Column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id"),
        nullable=True,  # 部署目標の場合に設定
    )

    # 目標の階層
    parent_goal_id = Column(
        UUID(as_uuid=False),
        ForeignKey("goals.id"),
        nullable=True,  # 親目標（部署目標など）
    )
    goal_level = Column(
        String(20),
        nullable=False,
        default="individual",  # 'company', 'department', 'individual'
    )

    # 目標内容
    title = Column(String(500), nullable=False)  # 「粗利300万円」
    description = Column(Text, nullable=True)  # 詳細説明
    goal_type = Column(
        String(50),
        nullable=False,  # 'numeric', 'deadline', 'action'
    )

    # 数値目標の場合
    target_value = Column(DECIMAL(15, 2), nullable=True)  # 目標値（300万 → 3000000）
    current_value = Column(DECIMAL(15, 2), default=0)  # 現在値
    unit = Column(String(50), nullable=True)  # '円', '件', '人'

    # 期限目標の場合
    deadline = Column(Date, nullable=True)

    # 期間
    period_type = Column(
        String(20),
        nullable=False,
        default="monthly",  # 'yearly', 'quarterly', 'monthly', 'weekly'
    )
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)

    # ステータス
    status = Column(
        String(20),
        nullable=False,
        default="active",  # 'active', 'completed', 'cancelled'
    )

    # 機密区分（4段階）
    classification = Column(
        String(20),
        nullable=False,
        default="internal",
    )

    # 作成者・更新者
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    updated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)

    # Relationships
    organization = relationship("Organization")
    user = relationship("User", foreign_keys=[user_id])
    department = relationship("Department")
    parent_goal = relationship("Goal", remote_side=[id], backref="child_goals")
    progress_records = relationship(
        "GoalProgress",
        back_populates="goal",
        cascade="all, delete-orphan",
    )
    reminders = relationship(
        "GoalReminder",
        back_populates="goal",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # インデックス
        Index("idx_goals_org", "organization_id"),
        Index("idx_goals_user", "user_id"),
        Index("idx_goals_dept", "department_id"),
        Index("idx_goals_parent", "parent_goal_id"),
        Index("idx_goals_period", "period_start", "period_end"),
        Index("idx_goals_status", "status", postgresql_where=(status == "active")),
        Index("idx_goals_level", "goal_level"),
        Index("idx_goals_type", "goal_type"),
        Index("idx_goals_classification", "classification"),
        # CHECK制約
        CheckConstraint(
            "goal_level IN ('company', 'department', 'individual')",
            name="check_goal_level",
        ),
        CheckConstraint(
            "goal_type IN ('numeric', 'deadline', 'action')",
            name="check_goal_type",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="check_goal_status",
        ),
        CheckConstraint(
            "period_type IN ('yearly', 'quarterly', 'monthly', 'weekly')",
            name="check_period_type",
        ),
        CheckConstraint(
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="check_goal_classification",
        ),
        CheckConstraint(
            "period_start <= period_end",
            name="check_period_range",
        ),
    )

    def __repr__(self):
        return f"<Goal(id={self.id}, title={self.title}, user_id={self.user_id})>"

    @property
    def achievement_rate(self) -> float:
        """達成率を計算（数値目標の場合）"""
        if self.goal_type != "numeric" or not self.target_value:
            return 0.0
        if self.target_value == 0:
            return 0.0
        return float((self.current_value or 0) / self.target_value * 100)


class GoalProgress(Base, TimestampMixin):
    """目標の日次進捗記録

    17時の振り返り回答と、翌朝8時のAIフィードバックを保存。
    同日に複数回返信があった場合はUPSERTで最新で上書き。

    機密区分:
        - internal: 通常の進捗記録
        - confidential: AIフィードバック含む場合（昇格）
    """

    __tablename__ = "goal_progress"

    # 主キー
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)

    # リレーション
    goal_id = Column(
        UUID(as_uuid=False),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 進捗データ
    progress_date = Column(Date, nullable=False)  # 記録日
    value = Column(DECIMAL(15, 2), nullable=True)  # 数値目標の場合の実績値
    cumulative_value = Column(DECIMAL(15, 2), nullable=True)  # 累計値

    # 振り返り
    daily_note = Column(Text, nullable=True)  # 「今日何やった？」の回答
    daily_choice = Column(Text, nullable=True)  # 「今日何を選んだ？」の回答

    # AIフィードバック
    ai_feedback = Column(Text, nullable=True)  # ソウルくんからのフィードバック
    ai_feedback_sent_at = Column(DateTime(timezone=True), nullable=True)

    # 機密区分（AIフィードバック含む場合はconfidentialに昇格）
    classification = Column(
        String(20),
        nullable=False,
        default="internal",
    )

    # 作成者・更新者
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    updated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)

    # Relationships
    goal = relationship("Goal", back_populates="progress_records")
    organization = relationship("Organization")

    __table_args__ = (
        # 冪等性: 1日1回のみ記録
        UniqueConstraint("goal_id", "progress_date", name="unique_goal_progress"),
        # インデックス
        Index("idx_goal_progress_goal", "goal_id"),
        Index("idx_goal_progress_org", "organization_id"),
        Index("idx_goal_progress_date", "progress_date"),
        Index("idx_goal_progress_classification", "classification"),
        # CHECK制約
        CheckConstraint(
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="check_goal_progress_classification",
        ),
    )

    def __repr__(self):
        return f"<GoalProgress(id={self.id}, goal_id={self.goal_id}, date={self.progress_date})>"


class GoalReminder(Base, TimestampMixin):
    """目標リマインド設定

    リマインドタイプ:
        - daily_check: 17時進捗確認
        - daily_reminder: 18時未回答リマインド
        - morning_feedback: 8時個人フィードバック
        - team_summary: 8時チームサマリー
    """

    __tablename__ = "goal_reminders"

    # 主キー
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)

    # テナント分離
    organization_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # リレーション
    goal_id = Column(
        UUID(as_uuid=False),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
    )

    # リマインド設定
    reminder_type = Column(
        String(50),
        nullable=False,  # 'daily_check', 'morning_feedback', 'team_summary', 'daily_reminder'
    )
    reminder_time = Column(Time, nullable=False)  # 17:00, 08:00, 18:00
    is_enabled = Column(Boolean, default=True)

    # ChatWork設定
    chatwork_room_id = Column(String(20), nullable=True)  # NULLの場合はDM

    # 作成者・更新者
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    updated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)

    # Relationships
    goal = relationship("Goal", back_populates="reminders")
    organization = relationship("Organization")

    __table_args__ = (
        # インデックス
        Index("idx_goal_reminders_org", "organization_id"),
        Index("idx_goal_reminders_goal", "goal_id"),
        Index(
            "idx_goal_reminders_enabled",
            "is_enabled",
            postgresql_where=(is_enabled == True),  # noqa: E712
        ),
        Index("idx_goal_reminders_type", "reminder_type"),
        Index("idx_goal_reminders_time", "reminder_time"),
        # CHECK制約
        CheckConstraint(
            "reminder_type IN ('daily_check', 'morning_feedback', 'team_summary', 'daily_reminder')",
            name="check_reminder_type",
        ),
    )

    def __repr__(self):
        return f"<GoalReminder(id={self.id}, goal_id={self.goal_id}, type={self.reminder_type})>"


class AuditLog(Base):
    """監査ログ

    confidential以上の操作を記録（鉄則遵守）。
    Phase 2.5の目標閲覧・更新、Phase 4A以降のテナント分離でも使用。
    """

    __tablename__ = "audit_logs"

    # 主キー
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)

    # テナント分離（既存形式に合わせてVARCHAR）
    organization_id = Column(String(100), nullable=True)

    # 実行者情報
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    user_email = Column(String(255), nullable=True)  # 冗長だがログ検索用

    # アクション情報
    action = Column(
        String(50),
        nullable=False,  # 'create', 'read', 'update', 'delete', 'view', 'sync', 'regenerate'
    )
    resource_type = Column(
        String(100),
        nullable=False,  # 'goal', 'goal_progress', 'goal_summary', 'document', etc.
    )
    resource_id = Column(String(255), nullable=True)  # UUIDまたはその他のID
    resource_name = Column(String(500), nullable=True)  # リソース名（検索用）

    # 関連情報
    department_id = Column(
        UUID(as_uuid=False),
        ForeignKey("departments.id"),
        nullable=True,
    )

    # 機密区分
    classification = Column(String(20), nullable=True)

    # 詳細データ
    details = Column(Text, nullable=True)  # JSON文字列として保存

    # アクセス元情報
    ip_address = Column(String(45), nullable=True)  # IPv6対応
    user_agent = Column(Text, nullable=True)

    # タイムスタンプ
    created_at = Column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
        nullable=False,
    )

    __table_args__ = (
        # インデックス
        Index("idx_audit_logs_org", "organization_id"),
        Index("idx_audit_logs_user", "user_id"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_resource_type", "resource_type"),
        Index("idx_audit_logs_resource_id", "resource_id"),
        Index("idx_audit_logs_classification", "classification"),
        Index("idx_audit_logs_created", "created_at"),
        Index("idx_audit_logs_dept", "department_id"),
        # CHECK制約
        CheckConstraint(
            "classification IS NULL OR classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="check_audit_log_classification",
        ),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, resource={self.resource_type})>"
