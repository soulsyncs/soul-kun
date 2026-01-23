"""
Phase 2 進化版 A1: パターン検出 - PatternDetector

このモジュールは、ソウルくんへの質問を分析し、
頻出パターンを検出する機能を提供します。

検出ロジック:
1. 会話ログから質問を抽出
2. 質問を正規化（挨拶除去、表記ゆれ統一）
3. カテゴリを分類（LLM使用またはキーワードベース）
4. 類似度ハッシュを生成
5. question_patternsテーブルを更新
6. 閾値を超えたらsoulkun_insightsに登録

設計書: docs/06_phase2_a1_pattern_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Version: 1.0
"""

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lib.detection.base import (
    BaseDetector,
    DetectionContext,
    DetectionResult,
    InsightData,
    truncate_text,
    validate_uuid,
)
from lib.detection.constants import (
    CATEGORY_KEYWORDS,
    Classification,
    DetectionParameters,
    Importance,
    InsightType,
    LogMessages,
    PatternStatus,
    QuestionCategory,
    SourceType,
)
from lib.detection.exceptions import (
    DetectionError,
    PatternSaveError,
    wrap_database_error,
    wrap_detection_error,
)


# ================================================================
# データクラス
# ================================================================

@dataclass
class PatternData:
    """
    質問パターンのデータクラス

    question_patternsテーブルのレコードを表現

    Attributes:
        id: パターンID
        organization_id: 組織ID
        department_id: 部署ID（オプション）
        question_category: カテゴリ
        question_hash: 類似度判定用ハッシュ
        normalized_question: 正規化された質問文
        occurrence_count: 発生回数（全期間）
        occurrence_timestamps: 各発生日時のリスト（ウィンドウ期間内のみ）
        first_asked_at: 最初に質問された日時
        last_asked_at: 最後に質問された日時
        asked_by_user_ids: 質問した人のリスト
        sample_questions: サンプル質問
        status: ステータス
    """

    id: UUID
    organization_id: UUID
    department_id: Optional[UUID]
    question_category: QuestionCategory
    question_hash: str
    normalized_question: str
    occurrence_count: int
    occurrence_timestamps: list[datetime]
    first_asked_at: datetime
    last_asked_at: datetime
    asked_by_user_ids: list[UUID]
    sample_questions: list[str]
    status: PatternStatus

    @property
    def window_occurrence_count(self) -> int:
        """
        ウィンドウ期間内の発生回数を取得

        occurrence_timestampsの要素数を返す
        （DBで既にウィンドウ期間外のタイムスタンプは除去済み）
        """
        return len(self.occurrence_timestamps)

    def get_window_occurrence_count(self, window_days: int = 30) -> int:
        """
        指定したウィンドウ期間内の発生回数を取得

        Args:
            window_days: ウィンドウ期間（日数）

        Returns:
            ウィンドウ期間内の発生回数
        """
        from datetime import timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        return sum(1 for ts in self.occurrence_timestamps if ts >= cutoff)

    @classmethod
    def from_row(cls, row: tuple) -> "PatternData":
        """
        データベースの行からPatternDataを作成

        Args:
            row: データベースの行（タプル）
                列順: id, organization_id, department_id, question_category,
                      question_hash, normalized_question, occurrence_count,
                      occurrence_timestamps, first_asked_at, last_asked_at,
                      asked_by_user_ids, sample_questions, status

        Returns:
            PatternData: パターンデータ
        """
        # occurrence_timestampsの処理
        raw_timestamps = row[7] or []
        occurrence_timestamps = []
        for ts in raw_timestamps:
            if isinstance(ts, datetime):
                occurrence_timestamps.append(ts)
            elif isinstance(ts, str):
                # ISO形式の文字列から変換
                try:
                    occurrence_timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
                except (ValueError, AttributeError):
                    pass

        return cls(
            id=UUID(str(row[0])),
            organization_id=UUID(str(row[1])),
            department_id=UUID(str(row[2])) if row[2] else None,
            question_category=QuestionCategory.from_string(row[3]),
            question_hash=row[4],
            normalized_question=row[5],
            occurrence_count=row[6],
            occurrence_timestamps=occurrence_timestamps,
            first_asked_at=row[8],
            last_asked_at=row[9],
            asked_by_user_ids=[UUID(str(uid)) for uid in (row[10] or [])],
            sample_questions=row[11] or [],
            status=PatternStatus(row[12]),
        )


# ================================================================
# PatternDetector クラス
# ================================================================

class PatternDetector(BaseDetector):
    """
    パターン検出器（A1）

    ソウルくんへの質問を分析し、頻出パターンを検出する

    使用例:
        >>> from lib.detection.pattern_detector import PatternDetector
        >>>
        >>> # 検出器を初期化
        >>> detector = PatternDetector(conn, org_id)
        >>>
        >>> # 質問を分析
        >>> result = await detector.detect(
        ...     question="週報の出し方を教えてください",
        ...     user_id=user_id,
        ...     department_id=department_id  # オプション
        ... )
        >>>
        >>> # 結果を確認
        >>> if result.success:
        ...     print(f"Detected: {result.detected_count} patterns")
        ...     if result.insight_created:
        ...         print(f"Insight created: {result.insight_id}")

    Attributes:
        pattern_threshold: パターン検出の閾値
        pattern_window_days: 検出対象期間（日数）
        max_sample_questions: 保存するサンプル質問の最大数
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        pattern_threshold: int = DetectionParameters.PATTERN_THRESHOLD,
        pattern_window_days: int = DetectionParameters.PATTERN_WINDOW_DAYS,
        max_sample_questions: int = DetectionParameters.MAX_SAMPLE_QUESTIONS,
    ) -> None:
        """
        PatternDetectorを初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            pattern_threshold: パターン検出の閾値（デフォルト: 5）
            pattern_window_days: 検出対象期間（デフォルト: 30日）
            max_sample_questions: サンプル質問の最大数（デフォルト: 5）
        """
        super().__init__(
            conn=conn,
            org_id=org_id,
            detector_type=SourceType.A1_PATTERN,
            insight_type=InsightType.PATTERN_DETECTED,
        )

        self._pattern_threshold = pattern_threshold
        self._pattern_window_days = pattern_window_days
        self._max_sample_questions = max_sample_questions

    # ================================================================
    # プロパティ
    # ================================================================

    @property
    def pattern_threshold(self) -> int:
        """パターン検出の閾値を取得"""
        return self._pattern_threshold

    @property
    def pattern_window_days(self) -> int:
        """検出対象期間を取得"""
        return self._pattern_window_days

    @property
    def max_sample_questions(self) -> int:
        """サンプル質問の最大数を取得"""
        return self._max_sample_questions

    # ================================================================
    # メイン検出メソッド
    # ================================================================

    async def detect(
        self,
        question: str,
        user_id: UUID,
        department_id: Optional[UUID] = None,
        context: Optional[DetectionContext] = None
    ) -> DetectionResult:
        """
        質問を分析し、パターンを検出

        このメソッドは以下の処理を実行する:
        1. 質問を正規化（挨拶除去、表記ゆれ統一）
        2. カテゴリを分類
        3. 類似度ハッシュを生成
        4. 既存パターンを検索
        5. パターンを更新または作成
        6. 閾値を超えたらインサイトを作成

        Args:
            question: ユーザーからの質問
            user_id: 質問したユーザーのID
            department_id: ユーザーの所属部署ID（オプション）
            context: 検出コンテキスト（オプション）

        Returns:
            DetectionResult: 検出結果

        Raises:
            DetectionError: 検出処理に失敗した場合
        """
        start_time = time.time()
        self.log_detection_start(context)

        try:
            # バリデーション
            user_id = validate_uuid(user_id, "user_id")
            if department_id is not None:
                department_id = validate_uuid(department_id, "department_id")

            # 1. 質問を正規化
            normalized = self._normalize_question(question)
            if not normalized:
                self._logger.debug("Question normalized to empty, skipping")
                return DetectionResult(
                    success=True,
                    detected_count=0,
                    details={"reason": "empty_after_normalization"}
                )

            # 2. カテゴリを分類
            category = await self._classify_category(normalized)

            # 3. 類似度ハッシュを生成
            question_hash = self._generate_hash(normalized)

            # 4. 既存パターンを検索（部署別: Codex HIGH1指摘対応）
            existing_pattern = await self._find_existing_pattern(
                question_hash=question_hash,
                department_id=department_id
            )

            pattern_data: Optional[PatternData] = None
            insight_created = False
            insight_id: Optional[UUID] = None

            if existing_pattern:
                # 5a. 既存パターンを更新（再活性化含む: Codex MEDIUM1指摘対応）
                # dry_runモードではDBを更新しない（Codex MEDIUM指摘対応）
                if context is None or not context.dry_run:
                    pattern_data = await self._update_pattern(
                        pattern_id=existing_pattern.id,
                        user_id=user_id,
                        sample_question=question,
                        reactivate=(existing_pattern.status != PatternStatus.ACTIVE)
                    )
                else:
                    # dry_runモードでは既存パターンをそのまま使用
                    pattern_data = existing_pattern

                # 6. 閾値チェック & インサイト作成
                # ウィンドウ期間内の発生回数で判定（Codex MEDIUM2指摘対応）
                window_count = pattern_data.window_occurrence_count
                if window_count >= self._pattern_threshold:
                    if not await self.insight_exists_for_source(pattern_data.id):
                        if context is None or not context.dry_run:
                            insight_data = self._create_insight_data(
                                self._pattern_to_dict(pattern_data)
                            )
                            insight_id = await self.save_insight(insight_data)
                            insight_created = True

                            self._logger.info(
                                LogMessages.PATTERN_THRESHOLD_REACHED,
                                extra={
                                    "pattern_id": str(pattern_data.id),
                                    "window_occurrence_count": window_count,
                                    "total_occurrence_count": pattern_data.occurrence_count,
                                    "insight_id": str(insight_id),
                                }
                            )
            else:
                # 5b. 新規パターンを作成
                if context is None or not context.dry_run:
                    pattern_id = await self._create_pattern(
                        category=category,
                        question_hash=question_hash,
                        normalized_question=normalized,
                        user_id=user_id,
                        department_id=department_id,
                        sample_question=question
                    )

                    self._logger.info(
                        LogMessages.PATTERN_CREATED,
                        extra={
                            "pattern_id": str(pattern_id),
                            "category": category.value,
                        }
                    )

                    # 閾値=1の場合、新規パターン作成時に即座にインサイト生成
                    # （Codex MEDIUM指摘対応: 境界値での検出漏れ防止）
                    if self._pattern_threshold <= 1:
                        # 作成したパターンを取得してインサイト生成
                        pattern_data = await self._find_existing_pattern(
                            question_hash=question_hash,
                            department_id=department_id
                        )
                        if pattern_data and not await self.insight_exists_for_source(pattern_data.id):
                            insight_data = self._create_insight_data(
                                self._pattern_to_dict(pattern_data)
                            )
                            insight_id = await self.save_insight(insight_data)
                            insight_created = True

                            self._logger.info(
                                LogMessages.PATTERN_THRESHOLD_REACHED,
                                extra={
                                    "pattern_id": str(pattern_data.id),
                                    "window_occurrence_count": 1,
                                    "total_occurrence_count": 1,
                                    "insight_id": str(insight_id),
                                }
                            )

            # 結果を作成
            duration_ms = (time.time() - start_time) * 1000
            result = DetectionResult(
                success=True,
                detected_count=1,
                insight_created=insight_created,
                insight_id=insight_id,
                details={
                    "category": category.value,
                    "is_new_pattern": existing_pattern is None,
                    "occurrence_count": pattern_data.occurrence_count if pattern_data else 1,
                    "window_occurrence_count": pattern_data.window_occurrence_count if pattern_data else 1,
                }
            )

            self.log_detection_complete(result, duration_ms)
            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.log_error("Detection failed", e)

            # セキュリティ: 例外メッセージをサニタイズ（機密情報漏洩防止）
            # 詳細は log_error() でログに記録済み
            return DetectionResult(
                success=False,
                error_message="パターン検出中に内部エラーが発生しました",
                details={"duration_ms": duration_ms}
            )

    # ================================================================
    # 正規化
    # ================================================================

    def _normalize_question(self, question: str) -> str:
        """
        質問を正規化

        以下の処理を実行:
        - 挨拶除去（「お疲れ様です」等）
        - 表記ゆれ統一（全角/半角等）
        - 空白正規化
        - 改行除去

        Args:
            question: 元の質問

        Returns:
            正規化された質問
        """
        if not question:
            return ""

        text = question

        # 1. 既存のtext_utilsを活用（利用可能な場合）
        try:
            from lib.text_utils import remove_greetings
            text = remove_greetings(text)
        except ImportError:
            # text_utilsが利用できない場合は簡易的な除去
            text = self._remove_greetings_simple(text)

        # 2. 改行を空白に変換
        text = re.sub(r'\n+', ' ', text)

        # 3. 連続する空白を1つに
        text = re.sub(r'\s+', ' ', text)

        # 4. 全角英数字を半角に
        text = self._normalize_width(text)

        # 5. 前後の空白を除去
        text = text.strip()

        # 6. メンション除去（[To:xxxxx]形式）
        text = re.sub(r'\[To:\d+\]', '', text)

        # 7. メンション除去後の空白再正規化（Codex LOW指摘対応）
        # メンション除去で生じる余分な空白を1つに
        text = re.sub(r'\s+', ' ', text).strip()

        # 8. 絵文字の除去（オプション - 現在は保持）
        # text = self._remove_emojis(text)

        return text

    def _remove_greetings_simple(self, text: str) -> str:
        """
        簡易的な挨拶除去

        text_utilsが利用できない場合のフォールバック

        Args:
            text: 元のテキスト

        Returns:
            挨拶を除去したテキスト
        """
        greetings = [
            r'お疲れ様です[。．、,]?\s*',
            r'お疲れさまです[。．、,]?\s*',
            r'おつかれさまです[。．、,]?\s*',
            r'お世話になっております[。．、,]?\s*',
            r'こんにちは[。．、,]?\s*',
            r'こんばんは[。．、,]?\s*',
            r'おはようございます[。．、,]?\s*',
            r'いつもありがとうございます[。．、,]?\s*',
        ]

        for pattern in greetings:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        return text

    def _normalize_width(self, text: str) -> str:
        """
        全角英数字を半角に変換

        Args:
            text: 元のテキスト

        Returns:
            半角に変換されたテキスト
        """
        # 全角英数字を半角に変換
        result = []
        for char in text:
            code = ord(char)
            # 全角英数字 (０-９, Ａ-Ｚ, ａ-ｚ)
            if 0xFF10 <= code <= 0xFF19:  # ０-９
                result.append(chr(code - 0xFF10 + ord('0')))
            elif 0xFF21 <= code <= 0xFF3A:  # Ａ-Ｚ
                result.append(chr(code - 0xFF21 + ord('A')))
            elif 0xFF41 <= code <= 0xFF5A:  # ａ-ｚ
                result.append(chr(code - 0xFF41 + ord('a')))
            else:
                result.append(char)

        return ''.join(result)

    # ================================================================
    # カテゴリ分類
    # ================================================================

    async def _classify_category(self, question: str) -> QuestionCategory:
        """
        質問のカテゴリを分類

        現在はキーワードベースで分類
        将来的にはLLM APIを使用する予定

        Args:
            question: 正規化された質問

        Returns:
            QuestionCategory: 判定されたカテゴリ
        """
        # TODO: LLM APIを使用したカテゴリ分類を実装
        # 現在はキーワードベースで分類

        question_lower = question.lower()

        for category, keywords in CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in question_lower:
                    return category

        return QuestionCategory.OTHER

    # ================================================================
    # ハッシュ生成
    # ================================================================

    def _generate_hash(self, normalized_question: str) -> str:
        """
        類似度判定用のハッシュを生成

        現在はSHA256ハッシュを使用
        将来的にはEmbeddingベースの類似度判定に移行予定

        Args:
            normalized_question: 正規化された質問

        Returns:
            ハッシュ文字列（64文字）
        """
        # SHA256ハッシュを生成
        hash_bytes = hashlib.sha256(normalized_question.encode('utf-8')).digest()
        return hash_bytes.hex()[:64]

    # ================================================================
    # パターン操作
    # ================================================================

    async def _find_existing_pattern(
        self,
        question_hash: str,
        department_id: Optional[UUID] = None
    ) -> Optional[PatternData]:
        """
        既存パターンを検索

        部署別でパターンを検索する（Codex HIGH1指摘対応）
        対応済み/無視済みのパターンも検索対象とする（Codex MEDIUM1指摘対応）

        Args:
            question_hash: 質問のハッシュ
            department_id: 部署ID（NULLの場合は部署未指定パターンを検索）

        Returns:
            PatternData: 既存パターン（存在しない場合はNone）
        """
        # センチネル値: 部署未指定を表すUUID
        SENTINEL_UUID = "00000000-0000-0000-0000-000000000000"

        try:
            # 部署IDのCOALESCE処理（DBのユニークインデックスと同じロジック）
            dept_id_for_query = str(department_id) if department_id else SENTINEL_UUID

            result = self.conn.execute(text("""
                SELECT
                    id,
                    organization_id,
                    department_id,
                    question_category,
                    question_hash,
                    normalized_question,
                    occurrence_count,
                    occurrence_timestamps,
                    first_asked_at,
                    last_asked_at,
                    asked_by_user_ids,
                    sample_questions,
                    status
                FROM question_patterns
                WHERE organization_id = :org_id
                  AND COALESCE(department_id, :sentinel::uuid) = :dept_id::uuid
                  AND question_hash = :hash
                LIMIT 1
            """), {
                "org_id": str(self.org_id),
                "dept_id": dept_id_for_query,
                "sentinel": SENTINEL_UUID,
                "hash": question_hash,
            })

            row = result.fetchone()
            if row:
                return PatternData.from_row(row)
            return None

        except Exception as e:
            raise wrap_database_error(e, "find existing pattern")

    async def _update_pattern(
        self,
        pattern_id: UUID,
        user_id: UUID,
        sample_question: str,
        reactivate: bool = False
    ) -> PatternData:
        """
        既存パターンを更新

        - occurrence_count をインクリメント
        - occurrence_timestamps に現在時刻を追加し、ウィンドウ期間外のものを削除
          （Codex MEDIUM2指摘対応: 30日間ウィンドウの実装）
        - last_asked_at を更新
        - asked_by_user_ids にユーザーを追加（重複なし）
        - sample_questions にサンプルを追加（最大数まで）
        - reactivate=Trueの場合、ステータスをactiveに戻し関連フィールドをリセット
          （Codex MEDIUM1指摘対応: 対応済み/無視済みパターンの再活性化）

        Args:
            pattern_id: パターンID
            user_id: 質問したユーザーID
            sample_question: 元の質問文
            reactivate: 再活性化フラグ（対応済み/無視済みパターンを復活させる）

        Returns:
            PatternData: 更新後のパターンデータ
        """
        try:
            # 再活性化時はステータスと関連フィールドをリセット
            if reactivate:
                result = self.conn.execute(text("""
                    UPDATE question_patterns
                    SET
                        occurrence_count = occurrence_count + 1,
                        -- ウィンドウ期間内のタイムスタンプのみ保持し、新しいタイムスタンプを追加
                        occurrence_timestamps = (
                            SELECT COALESCE(array_agg(ts ORDER BY ts), ARRAY[]::timestamptz[])
                            FROM unnest(
                                array_append(occurrence_timestamps, CURRENT_TIMESTAMP)
                            ) AS ts
                            WHERE ts > (CURRENT_TIMESTAMP - :window_days * interval '1 day')
                        ),
                        last_asked_at = CURRENT_TIMESTAMP,
                        asked_by_user_ids = CASE
                            WHEN :user_id::uuid = ANY(asked_by_user_ids)
                            THEN asked_by_user_ids
                            ELSE array_append(asked_by_user_ids, :user_id::uuid)
                        END,
                        sample_questions = CASE
                            WHEN array_length(sample_questions, 1) >= :max_samples
                            THEN sample_questions
                            ELSE array_append(sample_questions, :sample)
                        END,
                        -- 再活性化: ステータスと関連フィールドをリセット
                        status = :active_status,
                        addressed_at = NULL,
                        addressed_action = NULL,
                        dismissed_reason = NULL,
                        updated_by = :user_id,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :pattern_id
                      AND organization_id = :org_id
                    RETURNING
                        id,
                        organization_id,
                        department_id,
                        question_category,
                        question_hash,
                        normalized_question,
                        occurrence_count,
                        occurrence_timestamps,
                        first_asked_at,
                        last_asked_at,
                        asked_by_user_ids,
                        sample_questions,
                        status
                """), {
                    "pattern_id": str(pattern_id),
                    "org_id": str(self.org_id),
                    "user_id": str(user_id),
                    "sample": sample_question[:500],  # 500文字に制限
                    "max_samples": self._max_sample_questions,
                    "active_status": PatternStatus.ACTIVE.value,
                    "window_days": self._pattern_window_days,
                })

                self._logger.info(
                    "Pattern reactivated",
                    extra={
                        "pattern_id": str(pattern_id),
                        "reason": "same_question_asked_again",
                    }
                )
            else:
                result = self.conn.execute(text("""
                    UPDATE question_patterns
                    SET
                        occurrence_count = occurrence_count + 1,
                        -- ウィンドウ期間内のタイムスタンプのみ保持し、新しいタイムスタンプを追加
                        occurrence_timestamps = (
                            SELECT COALESCE(array_agg(ts ORDER BY ts), ARRAY[]::timestamptz[])
                            FROM unnest(
                                array_append(occurrence_timestamps, CURRENT_TIMESTAMP)
                            ) AS ts
                            WHERE ts > (CURRENT_TIMESTAMP - :window_days * interval '1 day')
                        ),
                        last_asked_at = CURRENT_TIMESTAMP,
                        asked_by_user_ids = CASE
                            WHEN :user_id::uuid = ANY(asked_by_user_ids)
                            THEN asked_by_user_ids
                            ELSE array_append(asked_by_user_ids, :user_id::uuid)
                        END,
                        sample_questions = CASE
                            WHEN array_length(sample_questions, 1) >= :max_samples
                            THEN sample_questions
                            ELSE array_append(sample_questions, :sample)
                        END,
                        updated_by = :user_id,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :pattern_id
                      AND organization_id = :org_id
                    RETURNING
                        id,
                        organization_id,
                        department_id,
                        question_category,
                        question_hash,
                        normalized_question,
                        occurrence_count,
                        occurrence_timestamps,
                        first_asked_at,
                        last_asked_at,
                        asked_by_user_ids,
                        sample_questions,
                        status
                """), {
                    "pattern_id": str(pattern_id),
                    "org_id": str(self.org_id),
                    "user_id": str(user_id),
                    "sample": sample_question[:500],  # 500文字に制限
                    "max_samples": self._max_sample_questions,
                    "window_days": self._pattern_window_days,
                })

            row = result.fetchone()
            if row is None:
                raise PatternSaveError(
                    message="Failed to update pattern - pattern not found",
                    details={"pattern_id": str(pattern_id)}
                )

            self._logger.debug(
                LogMessages.PATTERN_UPDATED,
                extra={
                    "pattern_id": str(pattern_id),
                    "occurrence_count": row[6],
                }
            )

            return PatternData.from_row(row)

        except PatternSaveError:
            raise
        except Exception as e:
            raise wrap_database_error(e, "update pattern")

    async def _create_pattern(
        self,
        category: QuestionCategory,
        question_hash: str,
        normalized_question: str,
        user_id: UUID,
        department_id: Optional[UUID],
        sample_question: str
    ) -> UUID:
        """
        新規パターンを作成

        部署別のユニーク制約に対応（Codex HIGH1指摘対応）
        レース条件が発生した場合は既存パターンを更新する

        Args:
            category: カテゴリ
            question_hash: 類似度判定用ハッシュ
            normalized_question: 正規化された質問
            user_id: 質問したユーザーID
            department_id: 部署ID（オプション）
            sample_question: 元の質問文

        Returns:
            UUID: 作成または更新されたパターンのID
        """
        try:
            # INSERT ... ON CONFLICT DO NOTHING を使用
            # 部署別のユニーク制約（COALESCE式）にはON CONFLICT(columns) DO UPDATE
            # が直接使えないため、競合時は別途更新処理を行う
            result = self.conn.execute(text("""
                INSERT INTO question_patterns (
                    organization_id,
                    department_id,
                    question_category,
                    question_hash,
                    normalized_question,
                    occurrence_count,
                    occurrence_timestamps,
                    first_asked_at,
                    last_asked_at,
                    asked_by_user_ids,
                    sample_questions,
                    status,
                    classification,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (
                    :org_id,
                    :dept_id,
                    :category,
                    :hash,
                    :normalized,
                    1,
                    ARRAY[CURRENT_TIMESTAMP],
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    ARRAY[:user_id::uuid],
                    ARRAY[:sample],
                    :status,
                    :classification,
                    :user_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT DO NOTHING
                RETURNING id
            """), {
                "org_id": str(self.org_id),
                "dept_id": str(department_id) if department_id else None,
                "category": category.value,
                "hash": question_hash,
                "normalized": normalized_question[:1000],  # 1000文字に制限
                "user_id": str(user_id),
                "sample": sample_question[:500],  # 500文字に制限
                "status": PatternStatus.ACTIVE.value,
                "classification": Classification.INTERNAL.value,
            })

            row = result.fetchone()

            if row is not None:
                # 正常に挿入された
                return UUID(str(row[0]))

            # 競合が発生した場合（レース条件）
            # 既存パターンを取得して更新する
            self._logger.debug(
                "Pattern insert conflict, finding existing pattern",
                extra={
                    "question_hash": question_hash[:16],
                    "department_id": str(department_id) if department_id else None,
                }
            )

            existing_pattern = await self._find_existing_pattern(
                question_hash=question_hash,
                department_id=department_id
            )

            if existing_pattern is None:
                # 競合したはずなのに見つからない（理論上ありえない）
                raise PatternSaveError(
                    message="Pattern conflict occurred but existing pattern not found",
                    details={
                        "question_hash": question_hash[:16],
                        "department_id": str(department_id) if department_id else None,
                    }
                )

            # 既存パターンを更新
            updated_pattern = await self._update_pattern(
                pattern_id=existing_pattern.id,
                user_id=user_id,
                sample_question=sample_question,
                reactivate=(existing_pattern.status != PatternStatus.ACTIVE)
            )

            return updated_pattern.id

        except PatternSaveError:
            raise
        except Exception as e:
            raise wrap_database_error(e, "create pattern")

    # ================================================================
    # インサイト生成
    # ================================================================

    def _create_insight_data(
        self,
        detection_data: dict[str, Any]
    ) -> InsightData:
        """
        検出結果からInsightDataを生成

        Args:
            detection_data: 検出データ（パターン情報）

        Returns:
            InsightData: インサイトデータ
        """
        # ウィンドウ期間内の発生回数を使用（Codex MEDIUM2指摘対応）
        window_occurrence_count = detection_data.get("window_occurrence_count", 0)
        total_occurrence_count = detection_data.get("occurrence_count", 0)
        unique_users = len(detection_data.get("asked_by_user_ids", []))
        normalized_question = detection_data.get("normalized_question", "")
        sample_questions = detection_data.get("sample_questions", [])
        category = detection_data.get("question_category", "other")

        # 重要度を判定（ウィンドウ内の発生回数で判定）
        importance = Importance.from_occurrence_count(
            occurrence_count=window_occurrence_count,
            unique_users=unique_users
        )

        # タイトルを生成（30文字 + "..."）
        title = f"「{truncate_text(normalized_question, 30)}」の質問が頻出しています"

        # 説明を生成
        description = (
            f"過去{self._pattern_window_days}日間で{window_occurrence_count}回、"
            f"{unique_users}人の社員から同じ質問がありました。\n\n"
            f"**カテゴリ**: {category}\n\n"
            f"**サンプル質問**:\n"
        )
        for i, sample in enumerate(sample_questions[:3], 1):
            description += f"{i}. {truncate_text(sample, 100)}\n"

        description += "\n全社周知またはナレッジ化を検討してください。"

        # 推奨アクションを生成
        recommended_action = (
            "1. この質問に対するマニュアルを作成\n"
            "2. 全社メールまたはSlackで周知\n"
            "3. ナレッジベースに登録（Phase 3）"
        )

        # 根拠データを生成
        evidence = {
            "window_occurrence_count": window_occurrence_count,
            "total_occurrence_count": total_occurrence_count,
            "unique_users": unique_users,
            "sample_questions": sample_questions[:5],
            "category": category,
            "pattern_id": str(detection_data.get("id", "")),
            "first_asked_at": str(detection_data.get("first_asked_at", "")),
            "last_asked_at": str(detection_data.get("last_asked_at", "")),
        }

        return InsightData(
            organization_id=self.org_id,
            insight_type=self.insight_type,
            source_type=self.detector_type,
            source_id=detection_data.get("id"),
            department_id=detection_data.get("department_id"),
            importance=importance,
            title=title,
            description=description,
            recommended_action=recommended_action,
            evidence=evidence,
            classification=Classification.INTERNAL,
        )

    def _pattern_to_dict(self, pattern: PatternData) -> dict[str, Any]:
        """
        PatternDataを辞書に変換

        Args:
            pattern: パターンデータ

        Returns:
            辞書形式のパターンデータ
        """
        return {
            "id": pattern.id,
            "organization_id": pattern.organization_id,
            "department_id": pattern.department_id,
            "question_category": pattern.question_category.value,
            "question_hash": pattern.question_hash,
            "normalized_question": pattern.normalized_question,
            "occurrence_count": pattern.occurrence_count,
            "window_occurrence_count": pattern.window_occurrence_count,
            "occurrence_timestamps": pattern.occurrence_timestamps,
            "first_asked_at": pattern.first_asked_at,
            "last_asked_at": pattern.last_asked_at,
            "asked_by_user_ids": pattern.asked_by_user_ids,
            "sample_questions": pattern.sample_questions,
            "status": pattern.status.value,
        }

    # ================================================================
    # バッチ処理
    # ================================================================

    async def detect_batch(
        self,
        questions: list[dict[str, Any]],
        context: Optional[DetectionContext] = None
    ) -> list[DetectionResult]:
        """
        複数の質問をバッチ処理

        Args:
            questions: 質問のリスト
                各要素は {"question": str, "user_id": UUID, "department_id": Optional[UUID]}
            context: 検出コンテキスト（オプション）

        Returns:
            DetectionResult のリスト
        """
        results = []

        for q in questions:
            try:
                result = await self.detect(
                    question=q.get("question", ""),
                    user_id=q.get("user_id"),
                    department_id=q.get("department_id"),
                    context=context
                )
                results.append(result)
            except Exception as e:
                self.log_error("Batch detection failed for question", e)
                # セキュリティ: 例外メッセージをサニタイズ（機密情報漏洩防止）
                # 詳細は log_error() でログに記録済み
                results.append(DetectionResult(
                    success=False,
                    error_message="バッチ検出中に内部エラーが発生しました"
                ))

        return results

    # ================================================================
    # 分析・レポート
    # ================================================================

    async def get_top_patterns(
        self,
        limit: int = 10,
        min_occurrence: int = 1,
        category: Optional[QuestionCategory] = None
    ) -> list[PatternData]:
        """
        頻出パターンのTop Nを取得

        Args:
            limit: 取得件数（デフォルト: 10、最大: 1000）
            min_occurrence: 最小発生回数（デフォルト: 1）
            category: カテゴリフィルタ（オプション）

        Returns:
            PatternData のリスト
        """
        # API経由での過剰取得を防止（Codex LOW指摘対応）
        MAX_LIMIT = 1000
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT

        try:
            query = """
                SELECT
                    id,
                    organization_id,
                    department_id,
                    question_category,
                    question_hash,
                    normalized_question,
                    occurrence_count,
                    occurrence_timestamps,
                    first_asked_at,
                    last_asked_at,
                    asked_by_user_ids,
                    sample_questions,
                    status
                FROM question_patterns
                WHERE organization_id = :org_id
                  AND status = :status
                  AND occurrence_count >= :min_occurrence
            """
            params: dict[str, Any] = {
                "org_id": str(self.org_id),
                "status": PatternStatus.ACTIVE.value,
                "min_occurrence": min_occurrence,
            }

            if category:
                query += " AND question_category = :category"
                params["category"] = category.value

            query += " ORDER BY occurrence_count DESC LIMIT :limit"
            params["limit"] = limit

            result = self.conn.execute(text(query), params)

            patterns = []
            for row in result.fetchall():
                patterns.append(PatternData.from_row(row))

            return patterns

        except Exception as e:
            raise wrap_database_error(e, "get top patterns")

    async def get_patterns_summary(self) -> dict[str, Any]:
        """
        パターンのサマリーを取得

        Returns:
            サマリー情報（カテゴリ別件数、発生回数合計等）
        """
        try:
            result = self.conn.execute(text("""
                SELECT
                    question_category,
                    COUNT(*) as pattern_count,
                    SUM(occurrence_count) as total_occurrences,
                    AVG(array_length(asked_by_user_ids, 1)) as avg_unique_users
                FROM question_patterns
                WHERE organization_id = :org_id
                  AND status = :status
                GROUP BY question_category
                ORDER BY total_occurrences DESC
            """), {
                "org_id": str(self.org_id),
                "status": PatternStatus.ACTIVE.value,
            })

            categories = {}
            total_patterns = 0
            total_occurrences = 0

            for row in result.fetchall():
                category = row[0]
                count = row[1]
                occurrences = row[2]

                categories[category] = {
                    "pattern_count": count,
                    "total_occurrences": occurrences,
                    "avg_unique_users": float(row[3]) if row[3] else 0,
                }

                total_patterns += count
                total_occurrences += occurrences

            return {
                "total_patterns": total_patterns,
                "total_occurrences": total_occurrences,
                "by_category": categories,
            }

        except Exception as e:
            raise wrap_database_error(e, "get patterns summary")
