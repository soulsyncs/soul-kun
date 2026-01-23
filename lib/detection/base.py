"""
Phase 2 進化版: 検出基盤 - BaseDetector 抽象クラス

このモジュールは、全ての検出機能（A1, A2, A3, A4）の共通基盤となる
抽象クラスを定義します。

継承クラス:
- PatternDetector (A1): 頻出質問パターンの検出
- PersonalizationDetector (A2): 属人化リスクの検出（将来）
- BottleneckDetector (A3): ボトルネックの検出（将来）
- EmotionDetector (A4): 感情変化の検出（将来）

設計書: docs/06_phase2_a1_pattern_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Version: 1.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lib.detection.constants import (
    Classification,
    Importance,
    InsightStatus,
    InsightType,
    SourceType,
)
from lib.detection.exceptions import (
    DatabaseError,
    InsightCreateError,
    wrap_database_error,
)


# ================================================================
# 型変数
# ================================================================

# 検出結果の型
DetectionResultT = TypeVar("DetectionResultT")

# インサイトデータの型
InsightDataT = TypeVar("InsightDataT")


# ================================================================
# データクラス
# ================================================================

@dataclass
class InsightData:
    """
    インサイト（気づき）のデータクラス

    soulkun_insightsテーブルに保存するデータを表現

    Attributes:
        organization_id: 組織ID
        insight_type: 気づきの種類
        source_type: ソースの種類（検出元）
        importance: 重要度
        title: タイトル
        description: 詳細説明
        source_id: ソースデータのID（オプション）
        department_id: 部署ID（オプション）
        recommended_action: 推奨アクション（オプション）
        evidence: 根拠データ（オプション）
        classification: 機密区分
    """

    organization_id: UUID
    insight_type: InsightType
    source_type: SourceType
    importance: Importance
    title: str
    description: str
    source_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    recommended_action: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    classification: Classification = Classification.INTERNAL

    def to_dict(self) -> dict[str, Any]:
        """
        辞書形式に変換

        Returns:
            インサイトデータの辞書
        """
        return {
            "organization_id": str(self.organization_id),
            "insight_type": self.insight_type.value,
            "source_type": self.source_type.value,
            "importance": self.importance.value,
            "title": self.title,
            "description": self.description,
            "source_id": str(self.source_id) if self.source_id else None,
            "department_id": str(self.department_id) if self.department_id else None,
            "recommended_action": self.recommended_action,
            "evidence": self.evidence,
            "classification": self.classification.value,
        }


@dataclass
class DetectionContext:
    """
    検出処理のコンテキスト

    検出処理に必要な共通情報を保持

    Attributes:
        organization_id: 組織ID
        user_id: 実行ユーザーID（オプション）
        department_id: 部署ID（オプション）
        dry_run: ドライラン（実際にはDBに保存しない）
        debug: デバッグモード
    """

    organization_id: UUID
    user_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    dry_run: bool = False
    debug: bool = False


@dataclass
class DetectionResult:
    """
    検出処理の結果

    Attributes:
        success: 処理が成功したか
        detected_count: 検出されたパターン数
        insight_created: インサイトが作成されたか
        insight_id: 作成されたインサイトのID（作成された場合）
        details: 追加の詳細情報
        error_message: エラーメッセージ（失敗した場合）
    """

    success: bool
    detected_count: int = 0
    insight_created: bool = False
    insight_id: Optional[UUID] = None
    details: dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


# ================================================================
# BaseDetector 抽象クラス
# ================================================================

class BaseDetector(ABC, Generic[DetectionResultT]):
    """
    検出機能の基底クラス

    全ての検出機能（A1, A2, A3, A4）はこのクラスを継承し、
    以下のメソッドを実装する必要がある:

    - detect(): 検出処理を実行
    - _create_insight_data(): 検出結果からInsightDataを生成

    使用例:
        >>> detector = PatternDetector(conn, org_id)
        >>> result = await detector.detect(
        ...     question="週報の出し方を教えてください",
        ...     user_id=user_id
        ... )
        >>> if result.insight_created:
        ...     print(f"Insight created: {result.insight_id}")

    Attributes:
        conn: データベース接続
        org_id: 組織ID
        detector_type: 検出器の種類（SourceType）
        insight_type: 生成するインサイトの種類（InsightType）
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        detector_type: SourceType,
        insight_type: InsightType
    ) -> None:
        """
        BaseDetectorを初期化

        Args:
            conn: データベース接続（SQLAlchemy Connection）
            org_id: 組織ID（UUID）
            detector_type: 検出器の種類
            insight_type: 生成するインサイトの種類
        """
        self._conn = conn
        self._org_id = org_id
        self._detector_type = detector_type
        self._insight_type = insight_type

        # ロガーの初期化（lib/logging.pyを使用）
        try:
            from lib.logging import get_logger
            self._logger = get_logger(f"detection.{detector_type.value}")
        except ImportError:
            import logging
            self._logger = logging.getLogger(f"detection.{detector_type.value}")

    # ================================================================
    # プロパティ
    # ================================================================

    @property
    def conn(self) -> Connection:
        """データベース接続を取得"""
        return self._conn

    @property
    def org_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    @property
    def detector_type(self) -> SourceType:
        """検出器の種類を取得"""
        return self._detector_type

    @property
    def insight_type(self) -> InsightType:
        """インサイトの種類を取得"""
        return self._insight_type

    # ================================================================
    # 抽象メソッド（継承クラスで実装必須）
    # ================================================================

    @abstractmethod
    async def detect(self, **kwargs: Any) -> DetectionResult:
        """
        検出処理を実行

        継承クラスで実装する必要がある

        Args:
            **kwargs: 検出に必要なパラメータ

        Returns:
            DetectionResult: 検出結果
        """
        pass

    @abstractmethod
    def _create_insight_data(
        self,
        detection_data: dict[str, Any]
    ) -> InsightData:
        """
        検出結果からInsightDataを生成

        継承クラスで実装する必要がある

        Args:
            detection_data: 検出データ

        Returns:
            InsightData: インサイトデータ
        """
        pass

    # ================================================================
    # 共通メソッド
    # ================================================================

    async def save_insight(self, insight_data: InsightData) -> UUID:
        """
        インサイトをデータベースに保存

        soulkun_insightsテーブルにINSERTし、IDを返す

        Args:
            insight_data: 保存するインサイトデータ

        Returns:
            UUID: 作成されたインサイトのID

        Raises:
            InsightCreateError: 保存に失敗した場合
        """
        self._logger.info(
            "Saving insight",
            extra={
                "organization_id": str(self._org_id),
                "insight_type": insight_data.insight_type.value,
                "importance": insight_data.importance.value,
            }
        )

        try:
            # ON CONFLICT DO NOTHINGで重複時は挿入をスキップ（Codex MEDIUM指摘対応）
            # uq_soulkun_insights_source制約で並行実行の重複を防止
            result = self._conn.execute(text("""
                INSERT INTO soulkun_insights (
                    organization_id,
                    department_id,
                    insight_type,
                    source_type,
                    source_id,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    classification,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (
                    :organization_id,
                    :department_id,
                    :insight_type,
                    :source_type,
                    :source_id,
                    :importance,
                    :title,
                    :description,
                    :recommended_action,
                    :evidence,
                    :status,
                    :classification,
                    :created_by,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT ON CONSTRAINT uq_soulkun_insights_source
                DO NOTHING
                RETURNING id
            """), {
                "organization_id": str(insight_data.organization_id),
                "department_id": str(insight_data.department_id) if insight_data.department_id else None,
                "insight_type": insight_data.insight_type.value,
                "source_type": insight_data.source_type.value,
                "source_id": str(insight_data.source_id) if insight_data.source_id else None,
                "importance": insight_data.importance.value,
                "title": insight_data.title[:200],  # タイトルは200文字以内
                "description": insight_data.description,
                "recommended_action": insight_data.recommended_action,
                "evidence": json.dumps(insight_data.evidence) if insight_data.evidence else "{}",
                "status": InsightStatus.NEW.value,
                "classification": insight_data.classification.value,
                "created_by": None,  # システム生成
            })

            row = result.fetchone()

            if row is not None:
                # 新規挿入成功
                insight_id = UUID(str(row[0]))
            elif insight_data.source_id is not None:
                # 重複検出 - 既存のインサイトを取得
                self._logger.debug(
                    "Insight already exists, fetching existing",
                    extra={
                        "organization_id": str(self._org_id),
                        "source_id": str(insight_data.source_id),
                    }
                )
                existing = self._conn.execute(text("""
                    SELECT id FROM soulkun_insights
                    WHERE organization_id = :org_id
                      AND source_type = :source_type
                      AND source_id = :source_id
                """), {
                    "org_id": str(insight_data.organization_id),
                    "source_type": insight_data.source_type.value,
                    "source_id": str(insight_data.source_id),
                })
                existing_row = existing.fetchone()
                if existing_row is None:
                    raise InsightCreateError(
                        message="Conflict occurred but existing insight not found",
                        details={"insight_type": insight_data.insight_type.value}
                    )
                insight_id = UUID(str(existing_row[0]))
            else:
                raise InsightCreateError(
                    message="Failed to get inserted insight ID",
                    details={"insight_type": insight_data.insight_type.value}
                )

            self._logger.info(
                "Insight saved successfully",
                extra={
                    "organization_id": str(self._org_id),
                    "insight_id": str(insight_id),
                }
            )

            return insight_id

        except InsightCreateError:
            raise
        except Exception as e:
            self._logger.error(
                "Failed to save insight",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise InsightCreateError(
                message="Failed to save insight to database",
                details={"insight_type": insight_data.insight_type.value},
                original_exception=e
            )

    async def insight_exists_for_source(self, source_id: UUID) -> bool:
        """
        指定したソースIDに対するインサイトが既に存在するか確認

        重複インサイトの作成を防ぐために使用

        Args:
            source_id: ソースデータのID

        Returns:
            bool: インサイトが存在する場合True
        """
        try:
            result = self._conn.execute(text("""
                SELECT 1 FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND source_type = :source_type
                  AND source_id = :source_id
                LIMIT 1
            """), {
                "org_id": str(self._org_id),
                "source_type": self._detector_type.value,
                "source_id": str(source_id),
            })

            return result.fetchone() is not None

        except Exception as e:
            raise wrap_database_error(e, "check insight existence")

    async def get_insight_by_source(
        self,
        source_id: UUID
    ) -> Optional[dict[str, Any]]:
        """
        ソースIDに対応するインサイトを取得

        Args:
            source_id: ソースデータのID

        Returns:
            インサイトデータ（存在しない場合はNone）
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    insight_type,
                    source_type,
                    importance,
                    title,
                    description,
                    status,
                    created_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND source_type = :source_type
                  AND source_id = :source_id
                LIMIT 1
            """), {
                "org_id": str(self._org_id),
                "source_type": self._detector_type.value,
                "source_id": str(source_id),
            })

            row = result.fetchone()
            if row is None:
                return None

            return {
                "id": UUID(str(row[0])),
                "insight_type": row[1],
                "source_type": row[2],
                "importance": row[3],
                "title": row[4],
                "description": row[5],
                "status": row[6],
                "created_at": row[7],
            }

        except Exception as e:
            raise wrap_database_error(e, "get insight by source")

    # ================================================================
    # ログ出力ヘルパー
    # ================================================================

    def log_detection_start(self, context: Optional[DetectionContext] = None) -> None:
        """
        検出処理開始のログを出力

        Args:
            context: 検出コンテキスト（オプション）
        """
        extra = {
            "organization_id": str(self._org_id),
            "detector_type": self._detector_type.value,
        }
        if context:
            extra["dry_run"] = context.dry_run
            extra["debug"] = context.debug

        self._logger.info("Detection started", extra=extra)

    def log_detection_complete(
        self,
        result: DetectionResult,
        duration_ms: Optional[float] = None
    ) -> None:
        """
        検出処理完了のログを出力

        Args:
            result: 検出結果
            duration_ms: 処理時間（ミリ秒、オプション）
        """
        extra = {
            "organization_id": str(self._org_id),
            "detector_type": self._detector_type.value,
            "success": result.success,
            "detected_count": result.detected_count,
            "insight_created": result.insight_created,
        }
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        if result.insight_id:
            extra["insight_id"] = str(result.insight_id)

        if result.success:
            self._logger.info("Detection completed", extra=extra)
        else:
            extra["error_message"] = result.error_message
            self._logger.error("Detection failed", extra=extra)

    def log_error(self, message: str, error: Exception) -> None:
        """
        エラーログを出力

        Args:
            message: エラーメッセージ
            error: 例外オブジェクト
        """
        self._logger.error(
            message,
            extra={
                "organization_id": str(self._org_id),
                "detector_type": self._detector_type.value,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
            exc_info=True
        )


# ================================================================
# ユーティリティ関数
# ================================================================

def validate_uuid(value: Any, field_name: str) -> UUID:
    """
    UUIDのバリデーション

    Args:
        value: バリデーション対象の値
        field_name: フィールド名（エラーメッセージ用）

    Returns:
        UUID: バリデーション済みのUUID

    Raises:
        ValidationError: バリデーションに失敗した場合
    """
    from lib.detection.exceptions import ValidationError

    if value is None:
        raise ValidationError(
            message=f"{field_name} is required",
            details={"field": field_name}
        )

    if isinstance(value, UUID):
        return value

    try:
        return UUID(str(value))
    except (TypeError, ValueError) as e:
        raise ValidationError(
            message=f"Invalid {field_name} format",
            details={"field": field_name, "value": str(value)[:50]},
            original_exception=e
        )


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    テキストを指定した長さに切り詰め

    Args:
        text: 元のテキスト
        max_length: 最大長（suffixを含む）
        suffix: 切り詰め時に追加する接尾辞

    Returns:
        切り詰められたテキスト
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix
