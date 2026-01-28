# lib/brain/guardian.py
"""
ガーディアン層（Guardian Layer）

v10.42.0: アクション実行前の価値観評価機能を追加

【2つの役割】
1. CEO Teaching検証: CEOの教えがMVV・組織論と矛盾していないか検証
2. アクション評価: 実行前にユーザーメッセージを価値観で評価（P0: Soul OS Gate）

設計書: docs/15_phase2d_ceo_learning.md

【CEO Teaching検証の設計原則】
1. ガーディアンは「拒否」する権限を持たない
2. 矛盾を「指摘」するのみ
3. 最終判断はCEOに委ねる

【アクション評価の設計原則（v10.42.0 P0）】
1. 価値観違反は「ブロック」可能（強制力あり）
2. CRITICAL/HIGHリスクは即座にモード遷移
3. 代替案を提示して終了
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.engine import Engine

from .models import (
    CEOTeaching,
    TeachingCategory,
    ValidationStatus,
    ConflictInfo,
    ConflictType,
    GuardianAlert,
    AlertStatus,
    Severity,
    TeachingValidationResult,
)
from .ceo_teaching_repository import (
    CEOTeachingRepository,
    ConflictRepository,
    GuardianAlertRepository,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 検証基準定数
# =============================================================================


MVV_VALIDATION_CRITERIA = {
    "mission": {
        "statement": "可能性の解放",
        "core_concepts": [
            "人の可能性を信じる",
            "価値を確信させる",
            "輝ける状態を作る",
            "伴走する",
        ],
        "anti_patterns": [
            "可能性を否定する",
            "限界を決めつける",
            "信じないと伝える",
            "見捨てる・諦める",
        ],
    },
    "vision": {
        "statement": "前を向く全ての人の可能性を解放し続けることで、企業も人も心で繋がる未来",
        "core_concepts": [
            "前を向く人を対象とする",
            "継続的に解放し続ける",
            "心で繋がる",
        ],
        "anti_patterns": [
            "後ろ向きな人を切り捨てる",
            "一時的な支援で終わる",
            "利害関係だけで繋がる",
        ],
    },
    "values": {
        "slogan": "感謝で自分を満たし、満たした自分で相手を満たし、相手も自分で自分を満たせるように伴走する",
        "behavioral_guidelines": [
            "仕事は何のためにあるのか？をわかっている",
            "人と仕事に感謝・尊敬・愛を持って取り組む",
            "ついていきたいと思われる人になる",
            "お客さんに自信を持ってサービス・商品を勧めている",
            "自分達の仕事が社会にどのような良い影響を与えるかを知っている",
            "人の人生を豊かにするという自覚がある",
            "大変なことも笑顔に変えていける",
            "困難な時ほど、ユニークさとユーモアを忘れない",
            "誇りを持って仲間を紹介できる",
            "自分の意見を持ち、それを伝えることができる",
        ],
    },
}


CHOICE_THEORY_CRITERIA = {
    "five_basic_needs": {
        "survival": {
            "description": "生存の欲求（安全・安心・健康・経済的安定）",
            "valid_approaches": [
                "安心感を与える",
                "安定を提供する",
                "リスクを軽減する",
            ],
            "violations": [
                "不安を煽る",
                "脅す",
                "経済的な脅しを使う",
            ],
        },
        "love": {
            "description": "愛・所属の欲求（仲間・チーム・繋がり）",
            "valid_approaches": [
                "繋がりを感じさせる",
                "チームを意識させる",
                "仲間意識を高める",
            ],
            "violations": [
                "孤立させる",
                "仲間外れにする",
                "関係を断つ",
            ],
        },
        "power": {
            "description": "力の欲求（達成感・成長・認められる）",
            "valid_approaches": [
                "小さな成功を認める",
                "成長を可視化する",
                "貢献を伝える",
            ],
            "violations": [
                "成長を否定する",
                "貢献を無視する",
                "比較で落とす",
            ],
        },
        "freedom": {
            "description": "自由の欲求（自律・自己決定・選択）",
            "valid_approaches": [
                "選択肢を与える",
                "自分で決めさせる",
                "裁量を持たせる",
            ],
            "violations": [
                "選択肢を奪う",
                "強制する",
                "命令する",
            ],
        },
        "fun": {
            "description": "楽しみの欲求（やりがい・興味・喜び）",
            "valid_approaches": [
                "興味を探る",
                "やりがいを見つける",
                "楽しさを伝える",
            ],
            "violations": [
                "楽しさを否定する",
                "退屈を強制する",
                "興味を無視する",
            ],
        },
    },
    "lead_management": {
        "description": "リードマネジメント（支援・問いかけ・傾聴）",
        "valid_approaches": [
            "支援する",
            "問いかける",
            "傾聴する",
            "一緒に考える",
        ],
        "violations": [
            "ボスマネジメント（指示・命令・監視）",
            "外発的コントロール",
            "罰と報酬で動かす",
        ],
    },
    "core_principle": {
        "description": "変えられるのは自分だけ。相手を変えようとしない。",
        "valid_approaches": [
            "自分の関わり方を変える",
            "相手の選択を尊重する",
            "質問で気づきを促す",
        ],
        "violations": [
            "相手を変えようとする",
            "強制する",
            "コントロールする",
        ],
    },
}


SDT_CRITERIA = {
    "autonomy": {
        "description": "自律性（自分で決める感覚）",
        "valid_approaches": [
            "選択を尊重する",
            "理由を説明して納得を得る",
            "自発的な行動を促す",
        ],
        "violations": [
            "強制する",
            "理由を説明しない",
            "選択を奪う",
        ],
    },
    "competence": {
        "description": "有能感（できるという感覚）",
        "valid_approaches": [
            "適切なチャレンジを与える",
            "フィードバックを提供する",
            "成長を認める",
        ],
        "violations": [
            "無理な目標を押し付ける",
            "フィードバックなしで放置",
            "できないことを強調する",
        ],
    },
    "relatedness": {
        "description": "関係性（繋がりの感覚）",
        "valid_approaches": [
            "尊重される環境を作る",
            "協力関係を築く",
            "帰属意識を高める",
        ],
        "violations": [
            "無視する",
            "孤立させる",
            "競争を煽る",
        ],
    },
}


# 検証システムプロンプト
VALIDATION_SYSTEM_PROMPT = """
あなたはソウルシンクスのガーディアンです。
CEOの教えがMVV（ミッション・ビジョン・バリュー）や組織論と整合しているかを検証します。

【重要な原則】
1. ガーディアンは「拒否」する権限を持たない
2. 矛盾を「指摘」するのみ
3. 最終判断はCEOに委ねる
4. グレーゾーンはCEOの判断に委ねる
5. 検出精度よりも説明の質を重視する

【MVV】
ミッション: 可能性の解放
ビジョン: 前を向く全ての人の可能性を解放し続けることで、企業も人も心で繋がる未来
バリュー: 感謝で自分を満たし、満たした自分で相手を満たし、相手も自分で自分を満たせるように伴走する

【選択理論の原則】
- 5つの基本欲求: 生存、愛・所属、力、自由、楽しみ
- リードマネジメント: 支援・問いかけ・傾聴
- 変えられるのは自分だけ

【自己決定理論の原則】
- 自律性: 自分で決める感覚
- 有能感: できるという感覚
- 関係性: 繋がりの感覚

【行動指針10箇条】
1. 仕事は何のためにあるのか？をわかっている
2. 人と仕事に感謝・尊敬・愛を持って取り組む
3. ついていきたいと思われる人になる
4. お客さんに自信を持ってサービス・商品を勧めている
5. 自分達の仕事が社会にどのような良い影響を与えるかを知っている
6. 人の人生を豊かにするという自覚がある
7. 大変なことも笑顔に変えていける
8. 困難な時ほど、ユニークさとユーモアを忘れない
9. 誇りを持って仲間を紹介できる
10. 自分の意見を持ち、それを伝えることができる
"""


# =============================================================================
# ガーディアンサービス
# =============================================================================


class GuardianService:
    """
    ガーディアンサービス

    CEOの教えを検証し、矛盾があればアラートを生成・送信します。
    """

    def __init__(
        self,
        pool: Engine,
        organization_id: str,
        llm_caller: Optional[Any] = None,
        chatwork_client: Optional[Any] = None,
    ):
        """
        初期化

        Args:
            pool: DB接続プール
            organization_id: 組織ID
            llm_caller: LLM呼び出し関数
            chatwork_client: ChatWorkクライアント
        """
        self._pool = pool
        self._organization_id = organization_id
        self._llm_caller = llm_caller
        self._chatwork_client = chatwork_client

        # リポジトリ
        self._teaching_repo = CEOTeachingRepository(pool, organization_id)
        self._conflict_repo = ConflictRepository(pool, organization_id)
        self._alert_repo = GuardianAlertRepository(pool, organization_id)

    # -------------------------------------------------------------------------
    # 検証
    # -------------------------------------------------------------------------

    async def validate_teaching(
        self,
        teaching: CEOTeaching,
    ) -> TeachingValidationResult:
        """
        教えを検証

        Args:
            teaching: 検証対象の教え

        Returns:
            検証結果
        """
        start_time = datetime.now()
        conflicts: List[ConflictInfo] = []

        try:
            # 1. LLMによる包括的検証
            llm_result = await self._validate_with_llm(teaching)

            # 2. 結果を解析
            conflicts = self._parse_llm_validation_result(llm_result, teaching.id)

            # 3. 既存教えとの矛盾チェック
            existing_conflicts = await self._check_existing_teachings(teaching)
            conflicts.extend(existing_conflicts)

            # 4. スコアを計算
            mvv_score = llm_result.get("mvv_score", 1.0)
            theory_score = llm_result.get("theory_score", 1.0)
            overall_score = (mvv_score + theory_score) / 2

            # 5. 矛盾をDBに保存
            for conflict in conflicts:
                conflict.teaching_id = teaching.id
                conflict.organization_id = self._organization_id
                self._conflict_repo.create_conflict(conflict)

            # 6. 結果を構築
            is_valid = len([c for c in conflicts if c.severity == Severity.HIGH]) == 0
            validation_status = (
                ValidationStatus.VERIFIED if is_valid
                else ValidationStatus.ALERT_PENDING
            )

            # 代替案
            alternative = llm_result.get("alternative_suggestion")

            elapsed = (datetime.now() - start_time).total_seconds() * 1000

            result = TeachingValidationResult(
                teaching=teaching,
                is_valid=is_valid,
                validation_status=validation_status,
                conflicts=conflicts,
                mvv_alignment_score=mvv_score,
                theory_alignment_score=theory_score,
                overall_score=overall_score,
                recommended_action="save" if is_valid else "alert",
                alternative_suggestion=alternative,
                validation_time_ms=int(elapsed),
            )

            logger.info(
                f"Teaching validation completed: id={teaching.id}, "
                f"valid={is_valid}, conflicts={len(conflicts)}, "
                f"score={overall_score:.2f}"
            )

            return result

        except Exception as e:
            logger.error(f"Teaching validation failed: {e}")
            # エラー時は安全側に倒してアラートを推奨
            return TeachingValidationResult(
                teaching=teaching,
                is_valid=False,
                validation_status=ValidationStatus.ALERT_PENDING,
                conflicts=[],
                overall_score=0.5,
                recommended_action="alert",
            )

    async def _validate_with_llm(
        self,
        teaching: CEOTeaching,
    ) -> Dict[str, Any]:
        """LLMによる検証"""
        prompt = f"""
以下のCEOの教えを検証してください。

【教え】
主張: {teaching.statement}
理由: {teaching.reasoning or "（未記入）"}
文脈: {teaching.context or "（未記入）"}
対象: {teaching.target or "全員"}
カテゴリ: {teaching.category.value if hasattr(teaching.category, 'value') else teaching.category}

【検証観点】
1. MVVとの整合性（ミッション・ビジョン・バリュー）
2. 選択理論との整合性（5つの基本欲求、リードマネジメント）
3. 自己決定理論との整合性（自律性・有能感・関係性）
4. 行動指針10箇条との整合性

【出力形式】
以下のJSON形式で出力してください。

```json
{{
  "overall_alignment": true,
  "overall_score": 0.85,
  "mvv_score": 0.9,
  "theory_score": 0.8,
  "mvv_validation": {{
    "is_aligned": true,
    "conflicts": [],
    "reasoning": "判断理由"
  }},
  "choice_theory_validation": {{
    "is_aligned": true,
    "conflicts": [],
    "reasoning": "判断理由"
  }},
  "sdt_validation": {{
    "is_aligned": true,
    "conflicts": [],
    "reasoning": "判断理由"
  }},
  "guidelines_validation": {{
    "is_aligned": true,
    "conflicts": [],
    "reasoning": "判断理由"
  }},
  "alternative_suggestion": null,
  "final_recommendation": "APPROVE"
}}
```

矛盾がある場合のconflicts例:
```json
{{
  "conflicts": [
    {{
      "type": "autonomy",
      "description": "「強制する」という表現が自律性を損なう可能性があります",
      "reference": "SDT: 自律性（自分で決める感覚）",
      "severity": "medium"
    }}
  ]
}}
```

矛盾がない場合は conflicts を空配列にしてください。
overall_score >= 0.7 の場合は APPROVE、それ以外は ALERT を推奨してください。
"""

        if not self._llm_caller:
            logger.warning("LLM caller not configured")
            return {"overall_alignment": True, "overall_score": 1.0}

        try:
            response = await self._llm_caller(
                VALIDATION_SYSTEM_PROMPT,
                prompt,
            )
            return self._parse_llm_response(response)
        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            return {"overall_alignment": True, "overall_score": 0.8}

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """LLMレスポンスを解析"""
        try:
            # JSONブロックを抽出
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response

            return json.loads(json_str)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return {"overall_alignment": True, "overall_score": 0.8}

    def _parse_llm_validation_result(
        self,
        llm_result: Dict[str, Any],
        teaching_id: str,
    ) -> List[ConflictInfo]:
        """LLM検証結果から矛盾情報を抽出"""
        conflicts = []

        # 各検証カテゴリをチェック
        validation_categories = [
            ("mvv_validation", ConflictType.MVV),
            ("choice_theory_validation", ConflictType.CHOICE_THEORY),
            ("sdt_validation", ConflictType.SDT),
            ("guidelines_validation", ConflictType.GUIDELINES),
        ]

        for key, conflict_type in validation_categories:
            validation = llm_result.get(key, {})
            if not validation.get("is_aligned", True):
                for c in validation.get("conflicts", []):
                    conflicts.append(ConflictInfo(
                        teaching_id=teaching_id,
                        conflict_type=conflict_type,
                        conflict_subtype=c.get("type"),
                        description=c.get("description", ""),
                        reference=c.get("reference", ""),
                        severity=self._parse_severity(c.get("severity", "medium")),
                    ))

        return conflicts

    def _parse_severity(self, severity_str: str) -> Severity:
        """深刻度を解析"""
        severity_map = {
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
        }
        return severity_map.get(severity_str.lower(), Severity.MEDIUM)

    async def _check_existing_teachings(
        self,
        new_teaching: CEOTeaching,
    ) -> List[ConflictInfo]:
        """既存教えとの矛盾をチェック"""
        conflicts = []

        # 同じカテゴリのアクティブな教えを取得
        existing = self._teaching_repo.get_teachings_by_category(
            [new_teaching.category],
            limit=20,
        )

        for existing_teaching in existing:
            if existing_teaching.id == new_teaching.id:
                continue

            conflict = await self._check_conflict_between_teachings(
                new_teaching,
                existing_teaching,
            )
            if conflict:
                conflicts.append(conflict)

        return conflicts

    async def _check_conflict_between_teachings(
        self,
        new_teaching: CEOTeaching,
        existing_teaching: CEOTeaching,
    ) -> Optional[ConflictInfo]:
        """2つの教えの矛盾をチェック"""
        if not self._llm_caller:
            return None

        prompt = f"""
以下の2つの教えが矛盾していないか判定してください。

【新しい教え】
{new_teaching.statement}
（理由: {new_teaching.reasoning or "未記入"}）

【既存の教え】
{existing_teaching.statement}
（理由: {existing_teaching.reasoning or "未記入"}）

【出力形式】
```json
{{
  "has_conflict": false,
  "conflict_type": "none",
  "description": "",
  "severity": "low",
  "reasoning": "両者は矛盾していません"
}}
```

conflict_type:
- contradiction: 完全に矛盾（両立不可）
- inconsistency: 一貫性がない（場合によって使い分け可能）
- supersede: 新しい教えが古い教えを上書き（進化）
- none: 矛盾なし
"""

        try:
            response = await self._llm_caller(
                "あなたは2つの教えの整合性を判定するエキスパートです。",
                prompt,
            )
            result = self._parse_llm_response(response)

            if result.get("has_conflict") and result.get("conflict_type") != "none":
                return ConflictInfo(
                    teaching_id=new_teaching.id,
                    conflict_type=ConflictType.EXISTING,
                    conflict_subtype=result.get("conflict_type"),
                    description=result.get("description", ""),
                    reference=f"既存教え: {existing_teaching.statement}",
                    severity=self._parse_severity(result.get("severity", "medium")),
                    conflicting_teaching_id=existing_teaching.id,
                )
        except Exception as e:
            logger.error(f"Conflict check failed: {e}")

        return None

    # -------------------------------------------------------------------------
    # アラート
    # -------------------------------------------------------------------------

    async def generate_alert(
        self,
        teaching: CEOTeaching,
        validation_result: TeachingValidationResult,
    ) -> GuardianAlert:
        """
        アラートを生成

        Args:
            teaching: 対象の教え
            validation_result: 検証結果

        Returns:
            生成されたアラート
        """
        # 矛盾の要約を生成
        conflict_summary = self._generate_conflict_summary(validation_result.conflicts)

        # アラートメッセージを生成（ソウルくん口調）
        alert_message = self._generate_alert_message(
            teaching,
            validation_result.conflicts,
            validation_result.alternative_suggestion,
        )

        alert = GuardianAlert(
            organization_id=self._organization_id,
            teaching_id=teaching.id,
            conflict_summary=conflict_summary,
            alert_message=alert_message,
            alternative_suggestion=validation_result.alternative_suggestion,
            conflicts=validation_result.conflicts,
            status=AlertStatus.PENDING,
        )

        # DBに保存
        saved_alert = self._alert_repo.create_alert(alert)

        logger.info(
            f"Guardian alert generated: id={saved_alert.id}, "
            f"teaching_id={teaching.id}, conflicts={len(validation_result.conflicts)}"
        )

        return saved_alert

    def _generate_conflict_summary(self, conflicts: List[ConflictInfo]) -> str:
        """矛盾の要約を生成"""
        if not conflicts:
            return "矛盾は検出されませんでした"

        high_conflicts = [c for c in conflicts if c.severity == Severity.HIGH]
        medium_conflicts = [c for c in conflicts if c.severity == Severity.MEDIUM]

        parts = []
        if high_conflicts:
            parts.append(f"重要な矛盾が{len(high_conflicts)}件")
        if medium_conflicts:
            parts.append(f"軽微な矛盾が{len(medium_conflicts)}件")

        return "検出されました: " + "、".join(parts)

    def _generate_alert_message(
        self,
        teaching: CEOTeaching,
        conflicts: List[ConflictInfo],
        alternative: Optional[str],
    ) -> str:
        """ソウルくん口調のアラートメッセージを生成"""
        # 深刻度に応じた冒頭
        has_high = any(c.severity == Severity.HIGH for c in conflicts)
        if has_high:
            opening = "🐺 ちょっと気になることがあるウル..."
        else:
            opening = "🐺 確認させてほしいウル"

        # 教えの要約
        statement_short = teaching.statement[:50] + "..." if len(teaching.statement) > 50 else teaching.statement

        # 矛盾の説明
        conflict_lines = []
        for i, c in enumerate(conflicts[:3], 1):  # 最大3件
            emoji = "🔴" if c.severity == Severity.HIGH else "🟡" if c.severity == Severity.MEDIUM else "🟢"
            conflict_lines.append(f"{emoji} {c.description}")

        parts = [
            opening,
            "",
            f"さっきの「{statement_short}」について、",
            "",
        ]
        parts.extend(conflict_lines)
        parts.append("")

        if alternative:
            parts.extend([
                "こんな言い方はどうウル？",
                f"→ {alternative}",
                "",
            ])

        parts.extend([
            "どうするか教えてほしいウル：",
            "1️⃣ そのまま保存（ソウルくんの考えを上書き）",
            "2️⃣ 取り消し（今回は保存しない）",
            "3️⃣ 言い直す（別の表現に変える）",
        ])

        return "\n".join(parts)

    async def send_alert(
        self,
        alert: GuardianAlert,
        ceo_room_id: str,
    ) -> bool:
        """
        アラートをCEOに送信

        Args:
            alert: 送信するアラート
            ceo_room_id: CEOのDMルームID

        Returns:
            送信成功ならTrue
        """
        if not self._chatwork_client:
            logger.warning("ChatWork client not configured")
            return False

        try:
            # メッセージを送信
            result = await self._chatwork_client.send_message(
                room_id=ceo_room_id,
                message=alert.alert_message,
            )

            # 通知情報を更新
            if result:
                message_id = result.get("message_id", "")
                self._alert_repo.update_notification_info(
                    alert_id=alert.id,
                    room_id=ceo_room_id,
                    message_id=message_id,
                )
                return True

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

        return False

    # -------------------------------------------------------------------------
    # アラート解決
    # -------------------------------------------------------------------------

    async def resolve_alert(
        self,
        alert_id: str,
        resolution: AlertStatus,
        ceo_response: Optional[str] = None,
        ceo_reasoning: Optional[str] = None,
    ) -> bool:
        """
        アラートを解決

        Args:
            alert_id: アラートID
            resolution: 解決タイプ（ACKNOWLEDGED, OVERRIDDEN, RETRACTED）
            ceo_response: CEOの回答
            ceo_reasoning: CEOの判断理由

        Returns:
            解決成功ならTrue
        """
        # アラートを取得
        alert = self._alert_repo.get_alert_by_id(alert_id)
        if not alert:
            logger.warning(f"Alert not found: {alert_id}")
            return False

        # アラートを更新
        success = self._alert_repo.resolve_alert(
            alert_id=alert_id,
            status=resolution,
            ceo_response=ceo_response,
            ceo_reasoning=ceo_reasoning,
        )

        if not success:
            return False

        # 教えのステータスを更新
        if resolution == AlertStatus.OVERRIDDEN:
            # 上書き許可 → 教えを有効化
            self._teaching_repo.update_validation_status(
                teaching_id=alert.teaching_id,
                status=ValidationStatus.OVERRIDDEN,
            )
        elif resolution == AlertStatus.ACKNOWLEDGED:
            # 確認済み（取り消し）→ 教えを無効化
            self._teaching_repo.deactivate_teaching(alert.teaching_id)
        elif resolution == AlertStatus.RETRACTED:
            # 撤回 → 教えを無効化（修正版は別途登録）
            self._teaching_repo.deactivate_teaching(alert.teaching_id)

        logger.info(
            f"Alert resolved: id={alert_id}, resolution={resolution}, "
            f"teaching_id={alert.teaching_id}"
        )

        return True

    def get_pending_alerts(self) -> List[GuardianAlert]:
        """未解決のアラートを取得"""
        return self._alert_repo.get_pending_alerts()

    def get_alert_by_teaching_id(self, teaching_id: str) -> Optional[GuardianAlert]:
        """教えIDでアラートを取得"""
        return self._alert_repo.get_alert_by_teaching_id(teaching_id)

    # -------------------------------------------------------------------------
    # v10.42.0 P0: アクション実行前の価値観評価（Soul OS Gate）
    # -------------------------------------------------------------------------

    def evaluate_action(
        self,
        user_message: str,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> "GuardianActionResult":
        """
        アクション実行前に価値観評価を行う

        v10.42.0 P0: 「必ず通る門」として機能
        - APPROVE: 実行OK
        - BLOCK_AND_SUGGEST: 実行ブロック + 代替案メッセージ
        - FORCE_MODE_SWITCH: モード強制遷移

        Args:
            user_message: ユーザーからのメッセージ
            action: 実行予定のアクション名
            context: 追加コンテキスト（ユーザー情報等）

        Returns:
            GuardianActionResult
        """
        # mvv_context からNG Pattern検出をインポート
        try:
            from lib.mvv_context import detect_ng_pattern, RiskLevel, AlertType
        except ImportError:
            try:
                from mvv_context import detect_ng_pattern, RiskLevel, AlertType
            except ImportError:
                # フォールバック: 常にAPPROVE
                logger.warning("mvv_context not available, guardian gate bypassed")
                return GuardianActionResult(
                    action_type=GuardianActionType.APPROVE,
                    original_action=action,
                )

        # NG Pattern検出
        ng_result = detect_ng_pattern(user_message)

        if not ng_result.detected:
            # 問題なし → APPROVE
            return GuardianActionResult(
                action_type=GuardianActionType.APPROVE,
                original_action=action,
            )

        # NG Pattern検出時の処理
        risk_level = ng_result.risk_level
        alert_type = ng_result.alert_type

        # CRITICAL (ng_mental_health) → 強制モード遷移
        if risk_level == RiskLevel.CRITICAL:
            logger.warning(
                f"🚨 [Guardian Gate] CRITICAL risk detected: "
                f"pattern={ng_result.pattern_type}, keyword={ng_result.matched_keyword}"
            )
            return GuardianActionResult(
                action_type=GuardianActionType.FORCE_MODE_SWITCH,
                original_action=action,
                blocked_reason=f"CRITICAL: {ng_result.pattern_type}",
                ng_pattern_type=ng_result.pattern_type,
                ng_keyword=ng_result.matched_keyword,
                force_mode="listening",  # 傾聴モードへ強制遷移
                alternative_message=ng_result.response_hint or (
                    "つらい状況なんだウルね。話してくれてありがとうウル。"
                    "専門家に相談することも考えてほしいウル。"
                    "今は何でも話していいウル🐺"
                ),
            )

        # HIGH (ng_retention_critical) → ブロック + 傾聴モード遷移
        if risk_level == RiskLevel.HIGH:
            logger.warning(
                f"⚠️ [Guardian Gate] HIGH risk detected: "
                f"pattern={ng_result.pattern_type}, keyword={ng_result.matched_keyword}"
            )
            return GuardianActionResult(
                action_type=GuardianActionType.FORCE_MODE_SWITCH,
                original_action=action,
                blocked_reason=f"HIGH: {ng_result.pattern_type}",
                ng_pattern_type=ng_result.pattern_type,
                ng_keyword=ng_result.matched_keyword,
                force_mode="listening",  # 傾聴モードへ
                alternative_message=ng_result.response_hint or (
                    "そう感じてるウルね。まず話を聞かせてウル🐺"
                ),
            )

        # MEDIUM → ブロック + 代替案提示
        if risk_level == RiskLevel.MEDIUM:
            logger.info(
                f"💡 [Guardian Gate] MEDIUM risk detected: "
                f"pattern={ng_result.pattern_type}, action will be modified"
            )
            return GuardianActionResult(
                action_type=GuardianActionType.BLOCK_AND_SUGGEST,
                original_action=action,
                blocked_reason=f"MEDIUM: {ng_result.pattern_type}",
                ng_pattern_type=ng_result.pattern_type,
                ng_keyword=ng_result.matched_keyword,
                alternative_message=ng_result.response_hint,
            )

        # LOW → APPROVE（警告ログのみ）
        logger.debug(
            f"[Guardian Gate] LOW risk detected: "
            f"pattern={ng_result.pattern_type}, continuing with caution"
        )
        return GuardianActionResult(
            action_type=GuardianActionType.APPROVE,
            original_action=action,
            ng_pattern_type=ng_result.pattern_type,
            ng_keyword=ng_result.matched_keyword,
        )


# =============================================================================
# v10.42.0 P0: アクション評価結果
# =============================================================================


class GuardianActionType(Enum):
    """Guardian評価結果タイプ"""
    APPROVE = "approve"                    # 実行OK
    BLOCK_AND_SUGGEST = "block_and_suggest"  # 実行ブロック + 代替案
    FORCE_MODE_SWITCH = "force_mode_switch"  # モード強制遷移


@dataclass
class GuardianActionResult:
    """
    Guardian評価結果

    v10.42.0 P0: アクション実行前の価値観評価結果
    """
    action_type: GuardianActionType
    original_action: str
    blocked_reason: Optional[str] = None
    ng_pattern_type: Optional[str] = None
    ng_keyword: Optional[str] = None
    alternative_message: Optional[str] = None
    force_mode: Optional[str] = None  # 強制遷移先のモード

    @property
    def should_block(self) -> bool:
        """実行をブロックすべきか"""
        return self.action_type in (
            GuardianActionType.BLOCK_AND_SUGGEST,
            GuardianActionType.FORCE_MODE_SWITCH,
        )

    @property
    def should_force_mode_switch(self) -> bool:
        """モード強制遷移すべきか"""
        return self.action_type == GuardianActionType.FORCE_MODE_SWITCH
