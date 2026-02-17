"""
Phase 2E: 学習基盤 - 検出パターン定義

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 3.1 フィードバックパターン

15種の検出パターンを定義:
- 直接的な修正パターン（4種）
- ルール教示パターン（3種）
- 好み教示パターン（3種）
- 事実教示パターン（3種）
- 文脈依存パターン（2種）
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern

logger = logging.getLogger(__name__)

from .constants import LearningCategory


# ============================================================================
# パターン定義クラス
# ============================================================================

@dataclass
class DetectionPattern:
    """検出パターン定義

    ユーザーの発言から「これは教えている」ことを検出するパターン。
    """

    # パターン識別子
    name: str

    # 対応する学習カテゴリ
    category: str

    # 正規表現パターン（複数可）
    regex_patterns: List[str] = field(default_factory=list)

    # コンパイル済み正規表現（内部用）
    _compiled_patterns: List[Pattern] = field(default_factory=list, repr=False)

    # 基本確信度（0.0-1.0）
    base_confidence: float = 0.7

    # パターンの説明
    description: str = ""

    # 抽出グループ名
    extract_groups: List[str] = field(default_factory=list)

    # 文脈が必要か
    requires_context: bool = False

    # 優先度（高いほど先にマッチ）
    priority: int = 50

    def __post_init__(self):
        """正規表現をコンパイル"""
        self._compiled_patterns = []
        for pattern in self.regex_patterns:
            try:
                self._compiled_patterns.append(
                    re.compile(pattern, re.IGNORECASE | re.UNICODE)
                )
            except re.error as e:
                logger.warning("Invalid regex pattern '%s': %s", pattern, type(e).__name__)

    def match(self, text: str) -> Optional[Dict[str, Any]]:
        """テキストにパターンをマッチング

        Args:
            text: 検査対象のテキスト

        Returns:
            マッチした場合は抽出結果の辞書、しなかった場合はNone
        """
        for compiled in self._compiled_patterns:
            match = compiled.search(text)
            if match:
                # 名前付きグループを抽出
                groups = match.groupdict()

                # グループが空の場合は通常のグループを使用
                if not groups:
                    groups = {
                        f"group_{i}": g
                        for i, g in enumerate(match.groups())
                        if g is not None
                    }

                return {
                    "matched_text": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                    "groups": groups,
                    "pattern_name": self.name,
                }

        return None


# ============================================================================
# 3.1.1 直接的な修正パターン（4種）
# ============================================================================

# パターン1: 「〇〇は△△だよ」
PATTERN_ALIAS_DEFINITION = DetectionPattern(
    name="alias_definition",
    category=LearningCategory.ALIAS.value,
    regex_patterns=[
        # 「麻美は渡部麻美のことだよ」
        r"(?P<from_value>[^\s、。]+)は(?P<to_value>[^\s、。]+)のことだ(よ|ね)?",
        # 「麻美って渡部麻美のことだよ」
        r"(?P<from_value>[^\s、。]+)って(?P<to_value>[^\s、。]+)のことだ(よ|ね)?",
        # 「麻美=渡部麻美」
        r"(?P<from_value>[^\s、。=]+)[=＝](?P<to_value>[^\s、。]+)",
        # 「麻美イコール渡部麻美」
        r"(?P<from_value>[^\s、。]+)(イコール|いこーる)(?P<to_value>[^\s、。]+)",
    ],
    base_confidence=0.85,
    description="別名・略称の定義",
    extract_groups=["from_value", "to_value"],
    priority=90,
)

# パターン2: 「〇〇じゃなくて△△」
PATTERN_CORRECTION = DetectionPattern(
    name="correction",
    category=LearningCategory.CORRECTION.value,
    regex_patterns=[
        # 「田中じゃなくて佐藤」
        r"(?P<wrong>[^\s、。]+)じゃなく(て|っ)(?P<correct>[^\s、。]+)",
        # 「田中ではなく佐藤」
        r"(?P<wrong>[^\s、。]+)ではなく(?P<correct>[^\s、。]+)",
        # 「田中じゃない、佐藤」
        r"(?P<wrong>[^\s、。]+)じゃない[、,](?P<correct>[^\s、。]+)",
        # 「違う、〇〇だよ」
        r"(違う|ちがう)[、,](?P<correct>[^\s、。]+)(だよ|だ)?",
    ],
    base_confidence=0.90,
    description="間違いの修正",
    extract_groups=["wrong", "correct"],
    priority=95,
)

# パターン3: 「〇〇のことは△△って呼んで」
PATTERN_ALIAS_REQUEST = DetectionPattern(
    name="alias_request",
    category=LearningCategory.ALIAS.value,
    regex_patterns=[
        # 「渡部麻美のことは麻美って呼んで」
        r"(?P<to_value>[^\s、。]+)のことは(?P<from_value>[^\s、。]+)って呼んで",
        # 「渡部麻美は麻美って呼んで」
        r"(?P<to_value>[^\s、。]+)は(?P<from_value>[^\s、。]+)って呼んで",
        # 「渡部麻美を麻美と呼んで」
        r"(?P<to_value>[^\s、。]+)を(?P<from_value>[^\s、。]+)と呼んで",
    ],
    base_confidence=0.90,
    description="別名・呼び方の指定",
    extract_groups=["from_value", "to_value"],
    priority=85,
)

# パターン4: 「〇〇=△△」「〇〇イコール△△」
PATTERN_EQUALITY = DetectionPattern(
    name="equality",
    category=LearningCategory.ALIAS.value,
    regex_patterns=[
        # 「SS=ソウルシンクス」
        r"(?P<from_value>[A-Za-zＡ-Ｚａ-ｚ]+)[=＝](?P<to_value>[^\s、。]+)",
        # 「SSはソウルシンクスの略」
        r"(?P<from_value>[A-Za-zＡ-Ｚａ-ｚ]+)は(?P<to_value>[^\s、。]+)の(略|りゃく)",
    ],
    base_confidence=0.85,
    description="略称・等価の定義",
    extract_groups=["from_value", "to_value"],
    priority=80,
)


# ============================================================================
# 3.1.2 ルール教示パターン（3種）
# ============================================================================

# パターン5: 「〇〇の時は△△して」
PATTERN_CONDITIONAL_RULE = DetectionPattern(
    name="conditional_rule",
    category=LearningCategory.RULE.value,
    regex_patterns=[
        # 「急ぎの時は先にDMで連絡して」
        r"(?P<condition>[^\s、。]+)の時は(?P<action>[^\s、。]+)して",
        # 「急ぎなら先にDMで連絡して」
        r"(?P<condition>[^\s、。]+)(なら|の場合は?)(?P<action>[^\s、。]+)して",
        # 「緊急時は先にDMで連絡」
        r"(?P<condition>[^\s、。]+)時は(?P<action>[^\s、。]+)(して|する)",
    ],
    base_confidence=0.80,
    description="条件付きルールの定義",
    extract_groups=["condition", "action"],
    priority=75,
)

# パターン6: 「〇〇は△△がルール」
PATTERN_RULE_STATEMENT = DetectionPattern(
    name="rule_statement",
    category=LearningCategory.RULE.value,
    regex_patterns=[
        # 「報告は毎日17時がルール」
        r"(?P<subject>[^\s、。]+)は(?P<rule>[^\s、。]+)がルール",
        # 「報告は毎日17時に決まっている」
        r"(?P<subject>[^\s、。]+)は(?P<rule>[^\s、。]+)(に|って)決まっている",
        # 「報告は毎日17時だからね」
        r"(?P<subject>[^\s、。]+)は(?P<rule>[^\s、。]+)だからね",
    ],
    base_confidence=0.80,
    description="ルールの明示",
    extract_groups=["subject", "rule"],
    priority=70,
)

# パターン7: 「〇〇しないで」「〇〇は禁止」
PATTERN_PROHIBITION = DetectionPattern(
    name="prohibition",
    category=LearningCategory.RULE.value,
    regex_patterns=[
        # 「勝手にタスク削除しないで」
        r"(?P<action>[^\s、。]+)しないで",
        # 「勝手なタスク削除は禁止」
        r"(?P<action>[^\s、。]+)は(禁止|きんし|ダメ|だめ)",
        # 「勝手にタスク削除するな」
        r"(?P<action>[^\s、。]+)するな",
        # 「勝手にタスク削除はやめて」
        r"(?P<action>[^\s、。]+)(は|を)やめて",
    ],
    base_confidence=0.85,
    description="禁止ルールの定義",
    extract_groups=["action"],
    priority=85,
)


# ============================================================================
# 3.1.3 好み教示パターン（3種）
# ============================================================================

# パターン8: 「〇〇が好き」「〇〇の方がいい」
PATTERN_PREFERENCE_LIKE = DetectionPattern(
    name="preference_like",
    category=LearningCategory.PREFERENCE.value,
    regex_patterns=[
        # 「箇条書きが好き」
        r"(?P<preference>[^\s、。]+)(が|は)(好き|すき)",
        # 「箇条書きの方がいい」
        r"(?P<preference>[^\s、。]+)の方が(いい|良い)",
        # 「箇条書きが好み」
        r"(?P<preference>[^\s、。]+)(が|は)(好み|このみ)",
    ],
    base_confidence=0.75,
    description="好みの表明",
    extract_groups=["preference"],
    priority=60,
)

# パターン9: 「〇〇でお願い」
PATTERN_PREFERENCE_REQUEST = DetectionPattern(
    name="preference_request",
    category=LearningCategory.PREFERENCE.value,
    regex_patterns=[
        # 「敬語でお願い」
        r"(?P<preference>[^\s、。]+)でお願い",
        # 「敬語でお願いします」
        r"(?P<preference>[^\s、。]+)でお願いします",
        # 「敬語で頼む」
        r"(?P<preference>[^\s、。]+)で頼む",
    ],
    base_confidence=0.80,
    description="好みの依頼",
    extract_groups=["preference"],
    priority=65,
)

# パターン10: 「いつも〇〇で」
PATTERN_PREFERENCE_ALWAYS = DetectionPattern(
    name="preference_always",
    category=LearningCategory.PREFERENCE.value,
    regex_patterns=[
        # 「いつも要点3つでまとめて」
        r"いつも(?P<preference>[^\s、。]+)で",
        # 「毎回要点3つでまとめて」
        r"毎回(?P<preference>[^\s、。]+)で",
        # 「常に要点3つでまとめて」
        r"常に(?P<preference>[^\s、。]+)で",
    ],
    base_confidence=0.80,
    description="恒常的な好み",
    extract_groups=["preference"],
    priority=65,
)


# ============================================================================
# 3.1.4 事実教示パターン（3種）
# ============================================================================

# パターン11: 「〇〇は△△」（事実の陳述）
PATTERN_FACT_STATEMENT = DetectionPattern(
    name="fact_statement",
    category=LearningCategory.FACT.value,
    regex_patterns=[
        # 「Aプロジェクトの担当は田中さん」
        r"(?P<subject>[^\s、。]+の[^\s、。]+)は(?P<value>[^\s、。]+さん)",
        # 「〇〇の担当は△△」
        r"(?P<subject>[^\s、。]+)の担当は(?P<value>[^\s、。]+)",
        # 「〇〇の責任者は△△」
        r"(?P<subject>[^\s、。]+)の(責任者|リーダー)は(?P<value>[^\s、。]+)",
    ],
    base_confidence=0.70,
    description="事実の陳述",
    extract_groups=["subject", "value"],
    priority=50,
)

# パターン12: 「覚えておいて、〇〇」
PATTERN_REMEMBER_REQUEST = DetectionPattern(
    name="remember_request",
    category=LearningCategory.FACT.value,
    regex_patterns=[
        # 「覚えておいて、来月から新オフィス」
        r"覚えておいて[、,](?P<fact>[^、。]+)",
        # 「覚えといて、来月から新オフィス」
        r"覚えといて[、,](?P<fact>[^、。]+)",
        # 「メモしておいて、来月から新オフィス」
        r"メモしておいて[、,](?P<fact>[^、。]+)",
        # 「記録しておいて」
        r"記録しておいて[、,](?P<fact>[^、。]+)",
    ],
    base_confidence=0.90,
    description="記憶依頼",
    extract_groups=["fact"],
    priority=90,
)

# パターン13: 「〇〇だから覚えておいて」
PATTERN_REMEMBER_REASON = DetectionPattern(
    name="remember_reason",
    category=LearningCategory.FACT.value,
    regex_patterns=[
        # 「山田さんは育休中だから覚えておいて」
        r"(?P<fact>[^、。]+)だから覚えておいて",
        # 「山田さんは育休中なので覚えておいて」
        r"(?P<fact>[^、。]+)なので覚えておいて",
        # 「山田さんは育休中だから忘れないで」
        r"(?P<fact>[^、。]+)だから忘れないで",
    ],
    base_confidence=0.90,
    description="理由付き記憶依頼",
    extract_groups=["fact"],
    priority=90,
)


# ============================================================================
# 3.1.5 文脈依存パターン（2種）
# ============================================================================

# パターン14: 直前の間違いへの指摘
PATTERN_CONTEXT_CORRECTION = DetectionPattern(
    name="context_correction",
    category=LearningCategory.CORRECTION.value,
    regex_patterns=[
        # 単独の名前（「佐藤」だけなど）- 文脈依存
        r"^(?P<correct>[^\s、。]{2,10})(だよ|です)?$",
        # 「それ〇〇」
        r"^それ(?P<correct>[^\s、。]+)(だよ|です)?$",
        # 「〇〇です」
        r"^(?P<correct>[^\s、。]+)です$",
    ],
    base_confidence=0.50,  # 文脈がないと確信度低
    description="文脈依存の修正",
    extract_groups=["correct"],
    requires_context=True,
    priority=40,
)

# パターン15: 暗黙の修正
PATTERN_IMPLICIT_CORRECTION = DetectionPattern(
    name="implicit_correction",
    category=LearningCategory.CORRECTION.value,
    regex_patterns=[
        # 「10時じゃなくて11時」- パターン2と重複するがこちらは数値に特化
        r"(?P<wrong>\d+)時じゃなく(て|っ)(?P<correct>\d+)時",
        # 「10日じゃなくて11日」
        r"(?P<wrong>\d+)日じゃなく(て|っ)(?P<correct>\d+)日",
        # 「10時→11時」
        r"(?P<wrong>\d+)(時|日)[→➡](?P<correct>\d+)\1",
    ],
    base_confidence=0.85,
    description="数値の暗黙修正",
    extract_groups=["wrong", "correct"],
    requires_context=True,
    priority=45,
)


# ============================================================================
# 追加パターン: 関係性
# ============================================================================

PATTERN_RELATIONSHIP = DetectionPattern(
    name="relationship",
    category=LearningCategory.RELATIONSHIP.value,
    regex_patterns=[
        # 「佐藤と鈴木は同期」
        r"(?P<person1>[^\s、。]+)と(?P<person2>[^\s、。]+)は(?P<relationship>同期|先輩後輩|上司部下)",
        # 「佐藤は鈴木の上司」
        r"(?P<person1>[^\s、。]+)は(?P<person2>[^\s、。]+)の(?P<relationship>上司|部下|先輩|後輩|同僚)",
        # 「佐藤さんと鈴木さんは仲がいい」
        r"(?P<person1>[^\s、。]+さん?)と(?P<person2>[^\s、。]+さん?)は(?P<relationship>仲がいい|仲が良い|親しい)",
    ],
    base_confidence=0.75,
    description="人間関係の定義",
    extract_groups=["person1", "person2", "relationship"],
    priority=55,
)


# ============================================================================
# 追加パターン: 手順
# ============================================================================

PATTERN_PROCEDURE = DetectionPattern(
    name="procedure",
    category=LearningCategory.PROCEDURE.value,
    regex_patterns=[
        # 「請求書は経理に回して」
        r"(?P<task>[^\s、。]+)は(?P<action>[^\s、。]+)に回して",
        # 「請求書は経理に送って」
        r"(?P<task>[^\s、。]+)は(?P<action>[^\s、。]+)に送って",
        # 「〇〇の時は△△に連絡」
        r"(?P<task>[^\s、。]+)の時は(?P<action>[^\s、。]+)に連絡",
    ],
    base_confidence=0.75,
    description="手順の定義",
    extract_groups=["task", "action"],
    priority=55,
)


# ============================================================================
# 追加パターン: 文脈情報
# ============================================================================

PATTERN_CONTEXT = DetectionPattern(
    name="context",
    category=LearningCategory.CONTEXT.value,
    regex_patterns=[
        # 「今月は繁忙期」
        r"(?P<period>今月|今週|今日|来月|来週)は(?P<context>[^\s、。]+)",
        # 「〇〇までは△△」
        r"(?P<period>[^\s、。]+)までは(?P<context>[^\s、。]+)",
        # 「〇〇の間は△△」
        r"(?P<period>[^\s、。]+)の間は(?P<context>[^\s、。]+)",
    ],
    base_confidence=0.70,
    description="文脈・期間情報",
    extract_groups=["period", "context"],
    priority=50,
)


# ============================================================================
# 全パターンリスト
# ============================================================================

# 優先度順にソート
ALL_PATTERNS: List[DetectionPattern] = sorted(
    [
        # 直接的な修正パターン（4種）
        PATTERN_ALIAS_DEFINITION,
        PATTERN_CORRECTION,
        PATTERN_ALIAS_REQUEST,
        PATTERN_EQUALITY,
        # ルール教示パターン（3種）
        PATTERN_CONDITIONAL_RULE,
        PATTERN_RULE_STATEMENT,
        PATTERN_PROHIBITION,
        # 好み教示パターン（3種）
        PATTERN_PREFERENCE_LIKE,
        PATTERN_PREFERENCE_REQUEST,
        PATTERN_PREFERENCE_ALWAYS,
        # 事実教示パターン（3種）
        PATTERN_FACT_STATEMENT,
        PATTERN_REMEMBER_REQUEST,
        PATTERN_REMEMBER_REASON,
        # 文脈依存パターン（2種）
        PATTERN_CONTEXT_CORRECTION,
        PATTERN_IMPLICIT_CORRECTION,
        # 追加パターン
        PATTERN_RELATIONSHIP,
        PATTERN_PROCEDURE,
        PATTERN_CONTEXT,
    ],
    key=lambda p: -p.priority  # 優先度の高い順
)

# パターン名でアクセスするための辞書
PATTERNS_BY_NAME: Dict[str, DetectionPattern] = {p.name: p for p in ALL_PATTERNS}

# カテゴリでグループ化
PATTERNS_BY_CATEGORY: Dict[str, List[DetectionPattern]] = {}
for pattern in ALL_PATTERNS:
    if pattern.category not in PATTERNS_BY_CATEGORY:
        PATTERNS_BY_CATEGORY[pattern.category] = []
    PATTERNS_BY_CATEGORY[pattern.category].append(pattern)


# ============================================================================
# パターン統計
# ============================================================================

def get_pattern_stats() -> Dict[str, Any]:
    """パターン統計を取得"""
    return {
        "total_patterns": len(ALL_PATTERNS),
        "by_category": {
            cat: len(patterns)
            for cat, patterns in PATTERNS_BY_CATEGORY.items()
        },
        "avg_confidence": sum(p.base_confidence for p in ALL_PATTERNS) / len(ALL_PATTERNS),
        "context_required": len([p for p in ALL_PATTERNS if p.requires_context]),
    }


def get_patterns_for_category(category: str) -> List[DetectionPattern]:
    """カテゴリ別のパターンを取得

    Args:
        category: 学習カテゴリ（LearningCategory.value）

    Returns:
        そのカテゴリに属するパターンのリスト
    """
    return PATTERNS_BY_CATEGORY.get(category, [])
