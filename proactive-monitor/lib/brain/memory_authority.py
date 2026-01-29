# lib/brain/memory_authority.py
"""
記憶権威層（Memory Authority Layer）

v10.43.0 P4: 長期記憶との矛盾を最終チェックするレイヤー

【役割】
P3 ValueAuthority で価値観チェックを通過したアクションに対し、
ユーザーの「長期記憶」（保存済みの方針・禁止事項・優先順位）との矛盾を最終判定する。

【設計思想】
- 誤ブロックを最小化するため、HARD CONFLICT のみ即座にブロック
- 曖昧なケースは REQUIRE_CONFIRMATION で確認を促す
- 長期記憶がない/弱いマッチの場合はニュートラル（APPROVE）に倒す

【判定フロー】
P3 ValueAuthority → MemoryAuthority判定 → OKならExecution / NGなら代替提案 or 確認

【統合位置】
core.py の _execute() にて、P3 の直後・実行直前

設計書: docs/13_brain_architecture.md
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)


# =============================================================================
# 判定結果の型定義
# =============================================================================


class MemoryDecision(Enum):
    """
    記憶権威層の判定結果

    APPROVE: 実行OK（矛盾なし or 長期記憶なし）
    BLOCK_AND_SUGGEST: 実行ブロック + 代替案提示（HARD CONFLICT）
    FORCE_MODE_SWITCH: モード強制遷移（重大な矛盾）
    REQUIRE_CONFIRMATION: 確認が必要（SOFT CONFLICT）
    """
    APPROVE = "approve"
    BLOCK_AND_SUGGEST = "block_and_suggest"
    FORCE_MODE_SWITCH = "force_mode_switch"
    REQUIRE_CONFIRMATION = "require_confirmation"


class MemoryConflict(TypedDict):
    """記憶との矛盾情報"""
    memory_type: str
    excerpt: str
    why_conflict: str
    severity: str  # "hard" or "soft"


@dataclass
class MemoryAuthorityResult:
    """
    記憶権威層の判定結果

    Attributes:
        decision: 判定結果
        original_action: 元のアクション名
        reasons: ブロック/確認理由のリスト
        conflicts: 検出された矛盾のリスト
        suggested_actions: 代替アクション候補
        confidence: 判定の確信度（0.0-1.0）
        confirmation_message: 確認用メッセージ（REQUIRE_CONFIRMATION時）
        alternative_message: 代替応答メッセージ（BLOCK時）
        forced_mode: 強制遷移先モード名
    """
    decision: MemoryDecision
    original_action: str
    reasons: List[str] = field(default_factory=list)
    conflicts: List[MemoryConflict] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    confidence: float = 1.0
    confirmation_message: Optional[str] = None
    alternative_message: Optional[str] = None
    forced_mode: Optional[str] = None

    @property
    def is_approved(self) -> bool:
        """実行が承認されたか"""
        return self.decision == MemoryDecision.APPROVE

    @property
    def should_block(self) -> bool:
        """実行をブロックすべきか"""
        return self.decision in (
            MemoryDecision.BLOCK_AND_SUGGEST,
            MemoryDecision.FORCE_MODE_SWITCH,
        )

    @property
    def needs_confirmation(self) -> bool:
        """確認が必要か"""
        return self.decision == MemoryDecision.REQUIRE_CONFIRMATION

    @property
    def should_force_mode_switch(self) -> bool:
        """モード強制遷移すべきか"""
        return self.decision == MemoryDecision.FORCE_MODE_SWITCH


# =============================================================================
# HARD CONFLICT パターン定義（即ブロック対象）
# =============================================================================


HARD_CONFLICT_PATTERNS: Dict[str, Dict[str, Any]] = {
    "explicit_prohibition": {
        "memory_keywords": ["禁止", "絶対にしない", "やらない", "NG", "厳禁"],
        "description": "明示的に禁止されている行動",
        "weight": 1.0,
    },
    "legal_compliance": {
        "memory_keywords": ["法務", "コンプライアンス", "法令", "規約", "契約違反"],
        "description": "法務・コンプラ的な禁止方針",
        "weight": 1.0,
    },
    "privacy_protection": {
        "memory_keywords": ["個人情報", "機密", "秘密", "プライバシー", "漏洩禁止"],
        "description": "個人情報/機微情報の扱いに関する禁止",
        "weight": 1.0,
    },
    "security_policy": {
        "memory_keywords": ["セキュリティ", "パスワード", "認証", "アクセス制限"],
        "description": "セキュリティポリシー違反",
        "weight": 0.9,
    },
}


# =============================================================================
# SOFT CONFLICT パターン定義（確認対象）
# =============================================================================


SOFT_CONFLICT_PATTERNS: Dict[str, Dict[str, Any]] = {
    "priority_contradiction": {
        "memory_keywords": ["最優先", "第一優先", "何より大事", "最重要"],
        "check_patterns": [
            r"後回し",
            r"優先.*下げ",
            r"延期",
            r"キャンセル",
        ],
        "description": "優先順位との矛盾",
        "weight": 0.7,
    },
    "family_health_risk": {
        "memory_keywords": ["家族", "健康", "体調", "休息"],
        "check_patterns": [
            r"徹夜",
            r"深夜",
            r"休み.*返上",
            r"無理.*して",
        ],
        "description": "家族・健康を削る可能性",
        "weight": 0.6,
    },
    "freedom_restriction": {
        "memory_keywords": ["自由", "自分の時間", "プライベート", "ワークライフバランス"],
        "check_patterns": [
            r"強制",
            r"必須",
            r"絶対.*やる",
            r"逃げられない",
        ],
        "description": "自由を強く制限する可能性",
        "weight": 0.5,
    },
}


# =============================================================================
# ALIGNMENT パターン定義（積極承認対象）
# =============================================================================


ALIGNMENT_PATTERNS: Dict[str, Dict[str, Any]] = {
    "business_priority": {
        "memory_keywords": ["受注", "売上", "採用", "成約"],
        "description": "ビジネス目標に沿う",
        "weight": 0.8,
    },
    "systematization": {
        "memory_keywords": ["仕組み化", "自動化", "効率化", "標準化"],
        "description": "仕組み化・効率化に沿う",
        "weight": 0.7,
    },
    "growth": {
        "memory_keywords": ["成長", "学習", "スキルアップ", "挑戦"],
        "description": "成長目標に沿う",
        "weight": 0.7,
    },
}


# =============================================================================
# テキスト正規化関数
# =============================================================================


def normalize_text(text: str) -> str:
    """
    テキストを正規化（全角半角統一、スペース削除、記号除去）

    Args:
        text: 正規化対象テキスト

    Returns:
        正規化されたテキスト
    """
    if not text:
        return ""

    # NFKC正規化（全角→半角、互換文字統一）
    text = unicodedata.normalize("NFKC", text)

    # 小文字化
    text = text.lower()

    # 連続スペースを単一スペースに
    text = re.sub(r"\s+", " ", text)

    # 前後の空白を除去
    text = text.strip()

    return text


def extract_keywords(text: str, min_length: int = 2) -> List[str]:
    """
    テキストからキーワードを抽出（日本語対応）

    Args:
        text: 抽出対象テキスト
        min_length: 最小文字数

    Returns:
        キーワードリスト
    """
    if not text:
        return []

    normalized = normalize_text(text)
    words = []

    for word in normalized.split():
        if len(word) >= min_length:
            words.append(word)

    japanese_pattern = r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+"
    for match in re.finditer(japanese_pattern, normalized):
        word = match.group()
        if len(word) >= min_length and word not in words:
            words.append(word)

    return words


def has_keyword_match(
    text: str,
    keywords: List[str],
    require_exact: bool = False,
) -> tuple[bool, List[str]]:
    """
    テキスト内にキーワードが含まれるかチェック

    Args:
        text: 検査対象テキスト
        keywords: 検索キーワードリスト
        require_exact: 完全一致を要求するか

    Returns:
        (マッチしたか, マッチしたキーワードリスト)
    """
    if not text or not keywords:
        return False, []

    normalized_text = normalize_text(text)
    matched = []

    for keyword in keywords:
        normalized_kw = normalize_text(keyword)
        if not normalized_kw:
            continue

        if require_exact:
            pattern = rf"\b{re.escape(normalized_kw)}\b"
            if re.search(pattern, normalized_text):
                matched.append(keyword)
        else:
            if normalized_kw in normalized_text:
                matched.append(keyword)

    return len(matched) > 0, matched


def calculate_overlap_score(
    text1: str,
    text2: str,
    ngram_size: int = 3,
) -> float:
    """
    2つのテキスト間のN-gram重複スコアを計算

    Args:
        text1: テキスト1
        text2: テキスト2
        ngram_size: N-gramサイズ（デフォルト3）

    Returns:
        重複スコア（0.0-1.0）
    """
    if not text1 or not text2:
        return 0.0

    normalized1 = normalize_text(text1)
    normalized2 = normalize_text(text2)

    if len(normalized1) < ngram_size or len(normalized2) < ngram_size:
        return 0.0

    ngrams1 = set()
    ngrams2 = set()

    for i in range(len(normalized1) - ngram_size + 1):
        ngrams1.add(normalized1[i:i + ngram_size])

    for i in range(len(normalized2) - ngram_size + 1):
        ngrams2.add(normalized2[i:i + ngram_size])

    if not ngrams1 or not ngrams2:
        return 0.0

    intersection = len(ngrams1 & ngrams2)
    union = len(ngrams1 | ngrams2)

    if union == 0:
        return 0.0

    return intersection / union


# =============================================================================
# Memory Authority クラス
# =============================================================================


class MemoryAuthority:
    """
    記憶権威層

    ユーザーの長期記憶（保存済みの方針・禁止事項・優先順位）に照らして
    「このアクションは実行してよいか」を最終判定するレイヤー。
    """

    HARD_THRESHOLD = 0.8
    SOFT_THRESHOLD = 0.5
    LOW_CONFIDENCE_THRESHOLD = 0.3

    def __init__(
        self,
        long_term_memory: Optional[List[Dict[str, Any]]] = None,
        user_name: str = "",
        organization_id: str = "",
    ):
        self.long_term_memory = long_term_memory or []
        self.user_name = user_name or "あなた"
        self.organization_id = organization_id
        self._categorized_memory = self._categorize_memory()

        logger.debug(
            f"MemoryAuthority initialized: "
            f"memory_count={len(self.long_term_memory)}, "
            f"user_name={user_name}"
        )

    def _categorize_memory(self) -> Dict[str, List[Dict[str, Any]]]:
        categorized: Dict[str, List[Dict[str, Any]]] = {
            "compliance": [],
            "principles": [],
            "values": [],
            "goals": [],
            "preferences": [],
        }

        type_weights = {
            "compliance": 1.0,
            "legal": 1.0,
            "principles": 0.9,
            "life_why": 0.8,
            "values": 0.7,
            "long_term_goal": 0.6,
            "identity": 0.5,
        }

        for memory in self.long_term_memory:
            memory_type = memory.get("memory_type", "")
            content = memory.get("content", "")

            if not content:
                continue

            if memory_type in ("compliance", "legal"):
                categorized["compliance"].append(memory)
            elif memory_type in ("principles", "life_why"):
                categorized["principles"].append(memory)
            elif memory_type == "values":
                categorized["values"].append(memory)
            elif memory_type in ("long_term_goal", "goal"):
                categorized["goals"].append(memory)
            else:
                categorized["preferences"].append(memory)

            memory["_weight"] = type_weights.get(memory_type, 0.3)

        return categorized

    def evaluate(
        self,
        message: str,
        action: str,
        action_params: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> MemoryAuthorityResult:
        action_params = action_params or {}
        context = context or {}

        logger.debug(f"🔍 [MemoryAuthority] Evaluating action: {action}")

        if not self.long_term_memory:
            logger.debug("[MemoryAuthority] No long-term memory, auto-approving")
            return MemoryAuthorityResult(
                decision=MemoryDecision.APPROVE,
                original_action=action,
                reasons=["長期記憶データなし（ニュートラル判定）"],
                confidence=1.0,
            )

        check_text = self._build_check_text(message, action_params)

        hard_result = self._check_hard_conflicts(check_text, action)
        if hard_result:
            return hard_result

        soft_result = self._check_soft_conflicts(check_text, action)
        if soft_result:
            return soft_result

        alignment_reasons = self._check_alignment(check_text)

        logger.debug(f"✅ [MemoryAuthority] Action approved: {action}")
        return MemoryAuthorityResult(
            decision=MemoryDecision.APPROVE,
            original_action=action,
            reasons=alignment_reasons if alignment_reasons else ["矛盾なし"],
            confidence=0.9 if alignment_reasons else 0.7,
        )

    def _build_check_text(
        self,
        message: str,
        action_params: Dict[str, Any],
    ) -> str:
        parts = [message]

        for key in ("task_body", "content", "description", "title", "body"):
            if key in action_params:
                parts.append(str(action_params[key]))

        return " ".join(parts)

    def _check_hard_conflicts(
        self,
        check_text: str,
        action: str,
    ) -> Optional[MemoryAuthorityResult]:
        conflicts: List[MemoryConflict] = []
        reasons: List[str] = []

        high_priority_memories = (
            self._categorized_memory.get("compliance", []) +
            self._categorized_memory.get("principles", [])
        )

        for memory in high_priority_memories:
            content = memory.get("content", "")
            memory_type = memory.get("memory_type", "")
            weight = memory.get("_weight", 0.5)

            for pattern_key, pattern_def in HARD_CONFLICT_PATTERNS.items():
                keywords = pattern_def.get("memory_keywords", [])

                has_hard_keyword, matched_kws = has_keyword_match(content, keywords)
                if not has_hard_keyword:
                    continue

                overlap_score = calculate_overlap_score(content, check_text)

                if overlap_score >= self.HARD_THRESHOLD or (
                    weight >= 0.9 and overlap_score >= self.SOFT_THRESHOLD
                ):
                    conflict: MemoryConflict = {
                        "memory_type": memory_type,
                        "excerpt": content[:100] + ("..." if len(content) > 100 else ""),
                        "why_conflict": pattern_def.get("description", "禁止事項に該当"),
                        "severity": "hard",
                    }
                    conflicts.append(conflict)
                    reasons.append(
                        f"【{pattern_def.get('description', 'HARD CONFLICT')}】"
                        f"記憶「{content[:30]}...」との矛盾"
                    )

        if conflicts:
            logger.warning(
                f"🚨 [MemoryAuthority] HARD CONFLICT detected: {len(conflicts)} conflicts"
            )
            return MemoryAuthorityResult(
                decision=MemoryDecision.BLOCK_AND_SUGGEST,
                original_action=action,
                reasons=reasons,
                conflicts=conflicts,
                suggested_actions=["general_conversation"],
                confidence=0.95,
                alternative_message=(
                    f"🐺 ちょっと待ってウル！{self.user_name}さん、"
                    f"これは以前決めた方針と矛盾してるかもウル。\n"
                    f"「{conflicts[0]['excerpt'][:50]}」との整合性を確認してほしいウル🐺"
                ),
            )

        return None

    def _check_soft_conflicts(
        self,
        check_text: str,
        action: str,
    ) -> Optional[MemoryAuthorityResult]:
        conflicts: List[MemoryConflict] = []
        reasons: List[str] = []

        all_memories = []
        for category in self._categorized_memory.values():
            all_memories.extend(category)

        for memory in all_memories:
            content = memory.get("content", "")
            memory_type = memory.get("memory_type", "")
            weight = memory.get("_weight", 0.5)

            for pattern_key, pattern_def in SOFT_CONFLICT_PATTERNS.items():
                keywords = pattern_def.get("memory_keywords", [])
                check_patterns = pattern_def.get("check_patterns", [])

                has_soft_keyword, _ = has_keyword_match(content, keywords)
                if not has_soft_keyword:
                    continue

                pattern_matched = False
                for pattern in check_patterns:
                    if re.search(pattern, normalize_text(check_text)):
                        pattern_matched = True
                        break

                if pattern_matched:
                    if weight < self.LOW_CONFIDENCE_THRESHOLD:
                        continue

                    conflict: MemoryConflict = {
                        "memory_type": memory_type,
                        "excerpt": content[:100] + ("..." if len(content) > 100 else ""),
                        "why_conflict": pattern_def.get("description", "優先順位との矛盾"),
                        "severity": "soft",
                    }
                    conflicts.append(conflict)
                    reasons.append(
                        f"【{pattern_def.get('description', 'SOFT CONFLICT')}】"
                        f"記憶「{content[:30]}...」との潜在的矛盾"
                    )

        if conflicts:
            logger.info(
                f"⚠️ [MemoryAuthority] SOFT CONFLICT detected: {len(conflicts)} conflicts"
            )
            return MemoryAuthorityResult(
                decision=MemoryDecision.REQUIRE_CONFIRMATION,
                original_action=action,
                reasons=reasons,
                conflicts=conflicts,
                suggested_actions=[action, "general_conversation"],
                confidence=0.6,
                confirmation_message=(
                    f"🐺 確認させてウル！{self.user_name}さん、\n"
                    f"これ、「{conflicts[0]['excerpt'][:40]}」と少し矛盾するかもウル。\n"
                    f"本当に進めていいウル？🐺"
                ),
            )

        return None

    def _check_alignment(self, check_text: str) -> List[str]:
        reasons: List[str] = []

        goal_memories = self._categorized_memory.get("goals", [])

        for memory in goal_memories:
            content = memory.get("content", "")

            for pattern_key, pattern_def in ALIGNMENT_PATTERNS.items():
                keywords = pattern_def.get("memory_keywords", [])

                has_alignment_keyword, matched_kws = has_keyword_match(content, keywords)
                if not has_alignment_keyword:
                    continue

                has_check_keyword, _ = has_keyword_match(check_text, keywords)
                if has_check_keyword:
                    reasons.append(
                        f"✅ {pattern_def.get('description', '目標')}に沿う行動"
                    )
                    break

        return reasons


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_memory_authority(
    long_term_memory: Optional[List[Dict[str, Any]]] = None,
    user_name: str = "",
    organization_id: str = "",
) -> MemoryAuthority:
    return MemoryAuthority(
        long_term_memory=long_term_memory,
        user_name=user_name,
        organization_id=organization_id,
    )
