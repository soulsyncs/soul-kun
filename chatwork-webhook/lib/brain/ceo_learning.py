# lib/brain/ceo_learning.py
"""
CEO学習層（CEO Learning Layer）

CEOとの対話から「教え」を抽出・蓄積し、スタッフへの応答に活用するための層。

設計書: docs/15_phase2d_ceo_learning.md

【動作原理】
1. CEOのメッセージを検出
2. 会話から「教え」を抽出（LLM使用）
3. ガーディアン層で検証
4. 検証済みの教えをDBに保存
5. スタッフへの応答時に関連する教えを取得

【重要な設計原則】
- CEOの言葉を尊重する
- 普遍的な形式に整理する
- 確信度0.7未満の教えは抽出しない
- 「会社の教えとして伝える」（CEOの名前は出さない）
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import (
    BrainContext,
    CEOTeaching,
    TeachingCategory,
    ValidationStatus,
    CEOTeachingContext,
    TeachingUsageContext,
)
from .ceo_teaching_repository import (
    CEOTeachingRepository,
    ConflictRepository,
    GuardianAlertRepository,
    TeachingUsageRepository,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================


# CEO判定用のアカウントIDリスト（Phase 4AではDBから取得）
CEO_ACCOUNT_IDS = [
    "1728974",  # 菊地雅克（カズさん）
]

# 教え抽出の確信度閾値
TEACHING_CONFIDENCE_THRESHOLD = 0.7

# 検索時に返す教えの最大件数
DEFAULT_TEACHING_LIMIT = 5

# 教え抽出プロンプト
# 注意: str.format()で使用するため、JSONサンプル内の{}は{{}}でエスケープ
TEACHING_EXTRACTION_PROMPT = """
あなたはソウルシンクスのCEO菊地雅克さんとの会話から「教え」を抽出するエージェントです。

以下の会話から、菊地さんが伝えようとしている「教え」を抽出してください。
「教え」とは、会社の方針、価値観、判断基準、行動指針などを含む、組織全体に適用できる知恵です。

【会話内容】
{conversation}

【抽出ルール】
1. 単なる事実の確認や質問は「教え」ではない
2. 個人的な感想や一時的な判断は「教え」ではない
3. 普遍的に適用できる原則・方針・判断基準を抽出する
4. 教えが複数ある場合は分けて抽出する
5. 曖昧な表現は含めない
6. 菊地さんの言葉を尊重しつつ、普遍的な形式に整理する

【出力フォーマット】
以下のJSON形式で出力してください。教えがない場合は空配列を返してください。

```json
{{
  "teachings": [
    {{
      "statement": "主張（何を言っているか）",
      "reasoning": "理由（なぜそう言っているか）",
      "context": "文脈（どんな状況で）",
      "target": "対象（誰に向けて：全員/マネージャー/特定部署など）",
      "category": "カテゴリ",
      "keywords": ["キーワード1", "キーワード2"],
      "confidence": 0.0-1.0
    }}
  ]
}}
```

【カテゴリ一覧】
- mvv_mission: ミッション「可能性の解放」の解釈
- mvv_vision: ビジョンの具体化
- mvv_values: バリューの実践方法
- choice_theory: 選択理論の適用
- sdt: 自己決定理論の適用
- servant: サーバントリーダーシップ
- psych_safety: 心理的安全性
- biz_sales: 営業
- biz_hr: 人事
- biz_accounting: 経理
- biz_general: その他業務
- culture: 会社文化
- communication: コミュニケーション
- staff_guidance: スタッフ指導
- other: その他

【注意】
- 確信度0.7未満の教えは含めない
- 曖昧な表現は含めない
"""

# カテゴリ推定のためのキーワードマップ
CATEGORY_KEYWORDS = {
    TeachingCategory.MVV_MISSION: [
        "可能性", "解放", "ミッション", "価値を確信",
        "信じる", "輝く", "伴走",
    ],
    TeachingCategory.MVV_VISION: [
        "ビジョン", "未来", "心で繋がる", "前を向く",
    ],
    TeachingCategory.MVV_VALUES: [
        "バリュー", "価値観", "行動指針", "感謝",
    ],
    TeachingCategory.CHOICE_THEORY: [
        "選択理論", "5つの欲求", "生存", "愛", "力", "自由", "楽しみ",
        "リードマネジメント", "ボスマネジメント", "内発的",
        "変えられるのは自分", "選択",
    ],
    TeachingCategory.SDT: [
        "自己決定", "自律性", "有能感", "関係性",
        "内発的動機", "モチベーション",
    ],
    TeachingCategory.SERVANT: [
        "サーバント", "支援", "傾聴", "リーダーシップ",
    ],
    TeachingCategory.PSYCH_SAFETY: [
        "心理的安全", "安心", "失敗を恐れない", "発言できる",
    ],
    TeachingCategory.BIZ_SALES: [
        "営業", "販売", "顧客", "商談", "受注",
    ],
    TeachingCategory.BIZ_HR: [
        "人事", "採用", "評価", "研修", "育成",
    ],
    TeachingCategory.BIZ_ACCOUNTING: [
        "経理", "財務", "決算", "予算", "コスト",
    ],
    TeachingCategory.BIZ_GENERAL: [
        "業務", "プロセス", "効率", "改善",
    ],
    TeachingCategory.CULTURE: [
        "文化", "カルチャー", "風土", "習慣",
    ],
    TeachingCategory.COMMUNICATION: [
        "コミュニケーション", "報連相", "伝える", "聞く",
    ],
    TeachingCategory.STAFF_GUIDANCE: [
        "指導", "育成", "フィードバック", "成長",
    ],
}


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class ExtractedTeaching:
    """抽出された教え（検証前）"""

    statement: str
    reasoning: Optional[str] = None
    context: Optional[str] = None
    target: Optional[str] = None
    category: str = "other"
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ProcessingResult:
    """CEO学習処理の結果"""

    success: bool
    teachings_extracted: int = 0
    teachings_saved: int = 0
    teachings_pending: int = 0  # アラート待ち
    message: str = ""
    extracted_teachings: List[CEOTeaching] = field(default_factory=list)


# =============================================================================
# CEO学習サービス
# =============================================================================


class CEOLearningService:
    """
    CEO学習サービス

    CEOのメッセージから教えを抽出し、保存・検索する機能を提供します。
    """

    def __init__(
        self,
        pool: Engine,
        organization_id: str,
        llm_caller: Optional[Any] = None,
    ):
        """
        初期化

        Args:
            pool: DB接続プール
            organization_id: 組織ID
            llm_caller: LLM呼び出し関数（テスト用にモック可能）
        """
        self._pool = pool
        self._organization_id = organization_id
        self._llm_caller = llm_caller

        # リポジトリ
        self._teaching_repo = CEOTeachingRepository(pool, organization_id)
        self._conflict_repo = ConflictRepository(pool, organization_id)
        self._alert_repo = GuardianAlertRepository(pool, organization_id)
        self._usage_repo = TeachingUsageRepository(pool, organization_id)

    # -------------------------------------------------------------------------
    # CEO判定
    # -------------------------------------------------------------------------

    def is_ceo_user(
        self,
        account_id: str,
        ceo_user_id: Optional[str] = None,
    ) -> bool:
        """
        CEOユーザーかどうかを判定

        Args:
            account_id: ChatWorkアカウントID
            ceo_user_id: Phase 4A用のCEOユーザーID（未実装）

        Returns:
            CEOならTrue
        """
        # Phase 4Aでは ceo_user_id を使用（未実装）
        if ceo_user_id:
            # TODO: DBから ceo_user_id を検索
            pass

        # 現在はハードコードされたリストで判定
        return account_id in CEO_ACCOUNT_IDS

    def get_ceo_name(self, account_id: str) -> str:
        """CEOの名前を取得（表示用ではなく内部用）"""
        # Phase 4Aではpersonsテーブルから取得
        return "菊地雅克"

    def _get_user_id_from_account_id(self, account_id: str) -> Optional[str]:
        """
        ChatWorkアカウントIDからユーザーID（UUID）を取得

        Args:
            account_id: ChatWorkアカウントID（例: "1728974"）

        Returns:
            ユーザーID（UUID文字列）、見つからない場合はNone
        """
        query = text("""
            SELECT id FROM users
            WHERE chatwork_account_id = :account_id
            AND organization_id = CAST(:org_id AS UUID)
            LIMIT 1
        """)

        try:
            with self._pool.connect() as conn:
                result = conn.execute(query, {
                    "account_id": account_id,
                    "org_id": self._organization_id,
                })
                row = result.fetchone()
                if row:
                    return str(row[0])
                return None
        except Exception as e:
            logger.error(f"Failed to get user_id from account_id: {e}")
            return None

    # -------------------------------------------------------------------------
    # 教え抽出
    # -------------------------------------------------------------------------

    async def process_ceo_message(
        self,
        message: str,
        room_id: str,
        account_id: str,
        message_id: Optional[str] = None,
        context: Optional[BrainContext] = None,
    ) -> ProcessingResult:
        """
        CEOのメッセージを処理し、教えを抽出

        Args:
            message: CEOのメッセージ
            room_id: ルームID
            account_id: CEOのアカウントID
            message_id: メッセージID（追跡用）
            context: 脳のコンテキスト

        Returns:
            処理結果
        """
        if not self.is_ceo_user(account_id):
            return ProcessingResult(
                success=False,
                message="CEOユーザーではありません",
            )

        try:
            # 1. 教えを抽出
            extracted = await self._extract_teachings(message, context)

            if not extracted:
                return ProcessingResult(
                    success=True,
                    message="教えは検出されませんでした",
                )

            # 2. ChatWorkアカウントIDからユーザーID（UUID）を取得
            user_id = self._get_user_id_from_account_id(account_id)
            if not user_id:
                logger.warning("User not found for account_id")
                return ProcessingResult(
                    success=False,
                    message=f"ユーザーが見つかりません: account_id={account_id}",
                )

            # 3. 各教えを処理
            saved_teachings: List[CEOTeaching] = []
            pending_teachings: List[CEOTeaching] = []

            for teaching_data in extracted:
                teaching = self._create_teaching_from_extracted(
                    teaching_data,
                    user_id,  # account_id ではなく user_id（UUID）を渡す
                    room_id,
                    message_id,
                )

                # TODO: Phase 2D-3でガーディアン層を実装
                # 現時点では検証をスキップして保存
                teaching.validation_status = ValidationStatus.VERIFIED

                saved = self._teaching_repo.create_teaching(teaching)
                saved_teachings.append(saved)

            return ProcessingResult(
                success=True,
                teachings_extracted=len(extracted),
                teachings_saved=len(saved_teachings),
                teachings_pending=len(pending_teachings),
                message=f"{len(saved_teachings)}件の教えを保存しました",
                extracted_teachings=saved_teachings,
            )

        except Exception as e:
            logger.error(f"CEO message processing failed: {e}")
            return ProcessingResult(
                success=False,
                message=f"処理中にエラーが発生しました: {str(e)}",
            )

    async def _extract_teachings(
        self,
        message: str,
        context: Optional[BrainContext] = None,
    ) -> List[ExtractedTeaching]:
        """
        メッセージから教えを抽出

        Args:
            message: CEOのメッセージ
            context: 脳のコンテキスト

        Returns:
            抽出された教えのリスト
        """
        # 会話コンテキストを構築
        conversation = message
        if context and context.recent_conversation:
            # 直近の会話も含める
            history = []
            for msg in context.recent_conversation[-5:]:
                role = "CEO" if msg.role == "user" else "ソウルくん"
                history.append(f"{role}: {msg.content}")
            history.append(f"CEO: {message}")
            conversation = "\n".join(history)

        # LLMを呼び出して教えを抽出
        prompt = TEACHING_EXTRACTION_PROMPT.format(conversation=conversation)

        try:
            if self._llm_caller:
                response = await self._llm_caller(prompt)
            else:
                # デフォルトのLLM呼び出し（未実装時はスキップ）
                logger.warning("LLM caller not configured, skipping extraction")
                return []

            # JSONを解析
            teachings = self._parse_extraction_response(response)

            # 確信度でフィルタ
            filtered = [
                t for t in teachings
                if t.confidence >= TEACHING_CONFIDENCE_THRESHOLD
            ]

            logger.info(
                f"Extracted {len(teachings)} teachings, "
                f"{len(filtered)} passed threshold"
            )

            return filtered

        except Exception as e:
            logger.error(f"Teaching extraction failed: {e}")
            return []

    def _parse_extraction_response(self, response: str) -> List[ExtractedTeaching]:
        """LLMのレスポンスを解析"""
        try:
            # JSONブロックを抽出
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # JSONブロックがない場合は全体をパース
                json_str = response

            data = json.loads(json_str)
            teachings_data = data.get("teachings", [])

            teachings = []
            for t in teachings_data:
                teachings.append(ExtractedTeaching(
                    statement=t.get("statement", ""),
                    reasoning=t.get("reasoning"),
                    context=t.get("context"),
                    target=t.get("target"),
                    category=t.get("category", "other"),
                    keywords=t.get("keywords", []),
                    confidence=float(t.get("confidence", 0.0)),
                ))

            return teachings

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return []

    def _create_teaching_from_extracted(
        self,
        extracted: ExtractedTeaching,
        user_id: str,
        room_id: str,
        message_id: Optional[str],
    ) -> CEOTeaching:
        """抽出された教えからCEOTeachingを作成

        Args:
            extracted: LLMで抽出された教えデータ
            user_id: CEOのユーザーID（UUID文字列）
            room_id: ルームID
            message_id: メッセージID
        """
        # カテゴリを変換
        try:
            category = TeachingCategory(extracted.category)
        except ValueError:
            category = TeachingCategory.OTHER

        return CEOTeaching(
            organization_id=self._organization_id,
            ceo_user_id=user_id,
            statement=extracted.statement,
            reasoning=extracted.reasoning,
            context=extracted.context,
            target=extracted.target,
            category=category,
            subcategory=None,
            keywords=extracted.keywords,
            validation_status=ValidationStatus.PENDING,
            priority=5,  # デフォルト優先度
            is_active=True,
            source_room_id=room_id,
            source_message_id=message_id,
        )

    # -------------------------------------------------------------------------
    # 教え検索
    # -------------------------------------------------------------------------

    def search_relevant_teachings(
        self,
        query: str,
        context: Optional[BrainContext] = None,
        limit: int = DEFAULT_TEACHING_LIMIT,
    ) -> List[CEOTeaching]:
        """
        クエリに関連する教えを検索

        Args:
            query: 検索クエリ（ユーザーメッセージ等）
            context: 脳のコンテキスト
            limit: 最大取得件数

        Returns:
            関連する教えのリスト（関連度順）
        """
        # 1. キーワード検索
        teachings = self._teaching_repo.search_teachings(query, limit=limit * 2)

        # 2. カテゴリ推定して追加検索
        estimated_categories = self._estimate_categories(query)
        if estimated_categories:
            category_teachings = self._teaching_repo.get_teachings_by_category(
                estimated_categories,
                limit=limit,
            )
            # 重複を除いて追加
            existing_ids = {t.id for t in teachings}
            for t in category_teachings:
                if t.id not in existing_ids:
                    teachings.append(t)

        # 3. 関連度でソート
        scored_teachings = []
        for teaching in teachings:
            score = self._calculate_relevance_score(teaching, query, context)
            scored_teachings.append((teaching, score))

        scored_teachings.sort(key=lambda x: x[1], reverse=True)

        return [t for t, _ in scored_teachings[:limit]]

    def get_teachings_for_topic(
        self,
        topic: str,
        category: Optional[TeachingCategory] = None,
        limit: int = DEFAULT_TEACHING_LIMIT,
    ) -> List[CEOTeaching]:
        """
        トピックに関連する教えを取得

        Args:
            topic: トピック
            category: カテゴリでフィルタ
            limit: 最大取得件数

        Returns:
            関連する教えのリスト
        """
        if category:
            result: List[CEOTeaching] = self._teaching_repo.get_teachings_by_category(
                [category],
                limit=limit,
            )
            return result
        else:
            search_result: List[CEOTeaching] = self._teaching_repo.search_teachings(topic, limit=limit)
            return search_result

    def get_all_active_teachings(
        self,
        category: Optional[TeachingCategory] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CEOTeaching]:
        """
        アクティブな教えを全て取得

        Args:
            category: カテゴリでフィルタ
            limit: 取得件数
            offset: オフセット

        Returns:
            教えのリスト
        """
        result: List[CEOTeaching] = self._teaching_repo.get_active_teachings(
            category=category,
            limit=limit,
            offset=offset,
        )
        return result

    def _estimate_categories(self, query: str) -> List[TeachingCategory]:
        """クエリからカテゴリを推定"""
        query_lower = query.lower()
        categories = []

        for category, keywords in CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in query_lower:
                    if category not in categories:
                        categories.append(category)
                    break

        return categories[:3]  # 最大3カテゴリ

    def _calculate_relevance_score(
        self,
        teaching: CEOTeaching,
        query: str,
        context: Optional[BrainContext] = None,
    ) -> float:
        """
        教えの関連度スコアを計算

        スコア構成:
        - キーワードマッチ: 40%
        - 優先度: 30%
        - 使用頻度: 20%
        - 役立ち度: 10%
        """
        score = 0.0

        # キーワードマッチ (0.0 - 0.4)
        query_words = set(query.lower().split())
        teaching_words = set(teaching.statement.lower().split())
        if teaching.keywords:
            teaching_words.update(k.lower() for k in teaching.keywords)

        if teaching_words:
            overlap = len(query_words & teaching_words)
            keyword_score = min(overlap / max(len(query_words), 1), 1.0) * 0.4
            score += keyword_score

        # 優先度 (0.0 - 0.3)
        priority_score = (teaching.priority / 10.0) * 0.3
        score += priority_score

        # 使用頻度 (0.0 - 0.2)
        usage_score = min(teaching.usage_count / 100.0, 1.0) * 0.2
        score += usage_score

        # 役立ち度 (0.0 - 0.1)
        if teaching.usage_count > 0:
            helpful_ratio = teaching.helpful_count / teaching.usage_count
            helpful_score = helpful_ratio * 0.1
            score += helpful_score

        return score

    # -------------------------------------------------------------------------
    # 教え使用ログ
    # -------------------------------------------------------------------------

    def log_teaching_usage(
        self,
        teaching: CEOTeaching,
        room_id: str,
        account_id: str,
        user_message: str,
        response_excerpt: Optional[str] = None,
        relevance_score: float = 0.0,
        selection_reasoning: Optional[str] = None,
    ) -> None:
        """
        教えの使用をログに記録

        Args:
            teaching: 使用した教え
            room_id: ルームID
            account_id: ユーザーのアカウントID
            user_message: ユーザーのメッセージ
            response_excerpt: 応答の抜粋
            relevance_score: 関連度スコア
            selection_reasoning: 選択理由
        """
        if not teaching.id:
            logger.warning("Teaching ID is required for usage logging, skipping")
            return

        teaching_id = teaching.id
        usage = TeachingUsageContext(
            teaching_id=teaching_id,
            organization_id=self._organization_id,
            room_id=room_id,
            account_id=account_id,
            user_message=user_message,
            response_excerpt=response_excerpt,
            relevance_score=relevance_score,
            selection_reasoning=selection_reasoning,
        )

        try:
            self._usage_repo.log_usage(usage)
            self._teaching_repo.increment_usage(teaching_id)
        except Exception as e:
            logger.error(f"Failed to log teaching usage: {e}")

    def update_teaching_feedback(
        self,
        teaching_id: str,
        room_id: str,
        was_helpful: bool,
        feedback: Optional[str] = None,
    ) -> None:
        """
        教えのフィードバックを更新

        Args:
            teaching_id: 教えのID
            room_id: ルームID
            was_helpful: 役に立ったか
            feedback: フィードバックコメント
        """
        try:
            self._usage_repo.update_feedback(
                teaching_id=teaching_id,
                room_id=room_id,
                was_helpful=was_helpful,
                feedback=feedback,
            )
            if was_helpful:
                self._teaching_repo.increment_usage(teaching_id, was_helpful=True)
        except Exception as e:
            logger.error(f"Failed to update teaching feedback: {e}")

    # -------------------------------------------------------------------------
    # コンテキスト生成
    # -------------------------------------------------------------------------

    def get_ceo_teaching_context(
        self,
        query: str,
        is_ceo: bool = False,
        context: Optional[BrainContext] = None,
    ) -> CEOTeachingContext:
        """
        CEOTeachingContextを生成

        BrainContextに追加するCEO教え関連の情報を取得します。

        Args:
            query: ユーザーのメッセージ
            is_ceo: CEOユーザーかどうか
            context: 脳のコンテキスト

        Returns:
            CEOTeachingContext
        """
        # 関連する教えを検索
        relevant_teachings = self.search_relevant_teachings(
            query,
            context=context,
            limit=DEFAULT_TEACHING_LIMIT,
        )

        # 未解決のアラートを取得
        pending_alerts = []
        if is_ceo:
            pending_alerts = self._alert_repo.get_pending_alerts()

        # 統計情報
        all_teachings = self._teaching_repo.get_active_teachings(limit=1000)

        return CEOTeachingContext(
            relevant_teachings=relevant_teachings,
            pending_alerts=pending_alerts,
            is_ceo_user=is_ceo,
            ceo_user_id=None,  # Phase 4Aで実装
            total_teachings_count=len(all_teachings),
            active_teachings_count=len([t for t in all_teachings if t.is_active]),
        )

    # -------------------------------------------------------------------------
    # 教え管理
    # -------------------------------------------------------------------------

    def get_teaching(self, teaching_id: str) -> Optional[CEOTeaching]:
        """教えを取得"""
        return self._teaching_repo.get_teaching_by_id(teaching_id)

    def update_teaching(
        self,
        teaching_id: str,
        updates: Dict[str, Any],
    ) -> Optional[CEOTeaching]:
        """教えを更新"""
        return self._teaching_repo.update_teaching(teaching_id, updates)

    def deactivate_teaching(
        self,
        teaching_id: str,
        superseded_by: Optional[str] = None,
    ) -> bool:
        """教えを無効化"""
        result: bool = self._teaching_repo.deactivate_teaching(
            teaching_id,
            superseded_by=superseded_by,
        )
        return result


# =============================================================================
# 応答生成への統合
# =============================================================================


def format_teachings_for_prompt(
    teachings: List[CEOTeaching],
    max_teachings: int = 3,
) -> str:
    """
    教えをLLMプロンプト用にフォーマット

    【重要】「会社の教えとして伝える」原則に従い、
    CEOの名前は出さず「ソウルシンクスとして大事にしていること」として表現する。

    Args:
        teachings: 教えのリスト
        max_teachings: 含める最大件数

    Returns:
        プロンプトに含める文字列
    """
    if not teachings:
        return ""

    lines = ["【ソウルシンクスとして大事にしていること】"]

    for i, teaching in enumerate(teachings[:max_teachings], 1):
        lines.append(f"{i}. {teaching.statement}")
        if teaching.reasoning:
            lines.append(f"   （理由: {teaching.reasoning}）")

    lines.append("")
    lines.append("上記を踏まえて、スタッフに伝えるときは「ソウルシンクスとして大事にしていることは〇〇ウル」のように伝えてください。")
    lines.append("「菊地さんが言っていた」「カズさんが〜」とは絶対に言わないでください。")

    return "\n".join(lines)


def should_include_teachings(
    context: Optional[BrainContext],
    account_id: str,
) -> bool:
    """
    教えを応答に含めるべきか判定

    Args:
        context: 脳のコンテキスト
        account_id: ユーザーのアカウントID

    Returns:
        含めるべきならTrue
    """
    # CEOには教えを表示しない（自分の言葉なので不要）
    if account_id in CEO_ACCOUNT_IDS:
        return False

    # 目標設定セッション中は含めない
    if context and context.has_active_session():
        return False

    return True
