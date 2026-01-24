"""
lib/mvv_context.py のユニットテスト

Phase 2C-1: MVV・アチーブ連携 + ベテラン秘書機能
- NGパターン検出
- 5つの基本欲求分析
- MVVコンテキスト生成
"""

import pytest
import sys
import os

# テスト対象モジュールのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.mvv_context import (
    MVVContext,
    detect_ng_pattern,
    analyze_basic_needs,
    get_mvv_context,
    should_flag_for_review,
    get_situation_response_guide,
    is_mvv_question,
    get_full_mvv_info,
    NGPatternResult,
    BasicNeedAnalysis,
    RiskLevel,
    BasicNeed,
    AlertType,
    SOULSYNC_MVV,
    BEHAVIORAL_GUIDELINES_10,
    ORGANIZATIONAL_THEORY_PROMPT,
    NG_PATTERNS,
    BASIC_NEED_KEYWORDS,
)


# ============================================================
# 1. NGパターン検出テスト
# ============================================================

class TestDetectNGPattern:
    """NGパターン検出のテスト"""

    def test_detect_retention_critical_keywords(self):
        """帰属意識リスク（転職・辞めたい等）の検出"""
        test_cases = [
            ("転職を考えています", "転職", AlertType.RETENTION_RISK),
            ("もう辞めたい…", "辞めたい", AlertType.RETENTION_RISK),
            ("退職届を出そうかな", "退職", AlertType.RETENTION_RISK),
            ("他社に行こうかな", "他社", AlertType.RETENTION_RISK),
            ("フリーランスになりたい", "フリーランス", AlertType.RETENTION_RISK),
            ("独立しようかな", "独立", AlertType.RETENTION_RISK),
            ("ここじゃないかも", "ここじゃない", AlertType.RETENTION_RISK),
            ("向いてないかもしれない", "向いてない", AlertType.RETENTION_RISK),
        ]

        for message, expected_keyword, expected_alert_type in test_cases:
            result = detect_ng_pattern(message)
            assert result.detected is True, f"Failed for message: {message}"
            assert result.matched_keyword == expected_keyword, f"Wrong keyword for: {message}"
            assert result.alert_type == expected_alert_type, f"Wrong alert type for: {message}"
            assert result.risk_level == RiskLevel.HIGH, f"Wrong risk level for: {message}"

    def test_detect_hr_authority_keywords(self):
        """人事権関連キーワードの検出"""
        test_cases = [
            ("評価について教えて", "評価"),
            ("昇進できるかな", "昇進"),
            ("給料が安い", "給料"),
            ("ボーナスはいくら？", "ボーナス"),
            ("異動したい", "異動"),
        ]

        for message, expected_keyword in test_cases:
            result = detect_ng_pattern(message)
            assert result.detected is True, f"Failed for message: {message}"
            assert result.matched_keyword == expected_keyword, f"Wrong keyword for: {message}"
            assert result.alert_type == AlertType.HR_AUTHORITY, f"Wrong alert type for: {message}"

    def test_detect_mental_health_keywords(self):
        """メンタルヘルスリスクの検出（最高優先度）"""
        test_cases = [
            "死にたい",
            "消えたい",
            "生きてる意味がない",
            "もうダメだ",
        ]

        for message in test_cases:
            result = detect_ng_pattern(message)
            assert result.detected is True, f"Failed for message: {message}"
            assert result.pattern_type == "ng_mental_health", f"Wrong pattern type for: {message}"
            assert result.risk_level == RiskLevel.CRITICAL, f"Should be CRITICAL for: {message}"
            assert result.flag is True, f"Should be flagged for: {message}"

    def test_detect_company_criticism_keywords(self):
        """会社批判キーワードの検出"""
        test_cases = [
            ("この会社はおかしい", "この会社は"),
            ("うちの会社のせいだ", "うちの会社"),
            ("経営陣が悪い", "経営陣"),
        ]

        for message, expected_keyword in test_cases:
            result = detect_ng_pattern(message)
            assert result.detected is True, f"Failed for message: {message}"
            assert result.alert_type == AlertType.COMPANY_CRITICISM, f"Wrong alert type for: {message}"

    def test_detect_low_psychological_safety(self):
        """心理的安全性低下の検出"""
        test_cases = [
            "本音が言えない",
            "相談しにくい",
            "失敗できない雰囲気",
        ]

        for message in test_cases:
            result = detect_ng_pattern(message)
            assert result.detected is True, f"Failed for message: {message}"
            assert result.alert_type == AlertType.LOW_PSYCHOLOGICAL_SAFETY, f"Wrong alert type for: {message}"

    def test_no_ng_pattern_detected(self):
        """NGパターンがない通常メッセージ"""
        normal_messages = [
            "今日のタスクを教えて",
            "会議の資料を作りたい",
            "プロジェクトの進捗どう？",
            "ランチ何食べる？",
            "素晴らしい成果だね！",
        ]

        for message in normal_messages:
            result = detect_ng_pattern(message)
            assert result.detected is False, f"False positive for: {message}"

    def test_priority_order_mental_health_first(self):
        """メンタルヘルスが最優先で検出される"""
        # 複数のNGキーワードを含む場合、メンタルヘルスが優先
        message = "死にたいし、転職も考えてるし、会社も嫌い"
        result = detect_ng_pattern(message)
        assert result.pattern_type == "ng_mental_health"
        assert result.risk_level == RiskLevel.CRITICAL

    def test_response_hint_exists(self):
        """対応ヒントが存在する"""
        result = detect_ng_pattern("辞めたい")
        assert result.detected is True
        assert result.response_hint is not None
        assert len(result.response_hint) > 0
        assert "ウル" in result.response_hint  # ソウルくん口調


# ============================================================
# 2. 基本欲求分析テスト
# ============================================================

class TestAnalyzeBasicNeeds:
    """5つの基本欲求分析のテスト"""

    def test_detect_survival_need(self):
        """生存欲求の検出"""
        messages = [
            "将来が不安です",
            "経済的に心配",
            "健康が気になる",
        ]

        for message in messages:
            result = analyze_basic_needs(message)
            assert result.primary_need == BasicNeed.SURVIVAL, f"Failed for: {message}"

    def test_detect_love_need(self):
        """愛・所属欲求の検出"""
        messages = [
            "チームに馴染めない",
            "孤独を感じる",
            "仲間がほしい",
            "居場所がない",
        ]

        for message in messages:
            result = analyze_basic_needs(message)
            assert result.primary_need == BasicNeed.LOVE, f"Failed for: {message}"

    def test_detect_power_need(self):
        """力欲求の検出"""
        messages = [
            "成長を感じられない",
            "達成感がない",
            "もっとスキルアップしたい",
            "自信がない",
        ]

        for message in messages:
            result = analyze_basic_needs(message)
            assert result.primary_need == BasicNeed.POWER, f"Failed for: {message}"

    def test_detect_freedom_need(self):
        """自由欲求の検出"""
        messages = [
            "やらされてる感がある",
            "自分で決めたい",
            "縛られてる気がする",
        ]

        for message in messages:
            result = analyze_basic_needs(message)
            assert result.primary_need == BasicNeed.FREEDOM, f"Failed for: {message}"

    def test_detect_fun_need(self):
        """楽しみ欲求の検出"""
        messages = [
            "つまらない仕事ばかり",
            "マンネリ化してる",
            "ワクワクしない",
        ]

        for message in messages:
            result = analyze_basic_needs(message)
            assert result.primary_need == BasicNeed.FUN, f"Failed for: {message}"

    def test_no_need_detected_for_neutral_message(self):
        """中立的なメッセージでは欲求が検出されない"""
        neutral_messages = [
            "今日の天気いいね",
            "資料を送ります",
            "了解しました",
        ]

        for message in neutral_messages:
            result = analyze_basic_needs(message)
            assert result.primary_need is None or result.confidence < 0.3, f"False positive for: {message}"

    def test_recommended_question_exists(self):
        """推奨質問が存在する"""
        result = analyze_basic_needs("成長できない、無力感を感じる")
        assert result.recommended_question is not None
        assert "ウル" in result.recommended_question

    def test_approach_hint_exists(self):
        """アプローチヒントが存在する"""
        result = analyze_basic_needs("孤独を感じる")
        assert result.approach_hint is not None
        assert len(result.approach_hint) > 0


# ============================================================
# 3. MVVコンテキストテスト
# ============================================================

class TestMVVContext:
    """MVVContextクラスのテスト"""

    def test_get_mvv_summary(self):
        """MVV要約の取得"""
        ctx = MVVContext()
        summary = ctx.get_mvv_summary()

        assert "可能性の解放" in summary
        assert "心で繋がる" in summary
        assert "ソウルシンクス" in summary

    def test_get_context_for_prompt_includes_mvv(self):
        """プロンプト用コンテキストにMVVが含まれる"""
        ctx = MVVContext()
        prompt = ctx.get_context_for_prompt(include_mvv=True, include_org_theory=False)

        assert "ミッション" in prompt
        assert "ビジョン" in prompt

    def test_get_context_for_prompt_includes_org_theory(self):
        """プロンプト用コンテキストに組織論が含まれる"""
        ctx = MVVContext()
        prompt = ctx.get_context_for_prompt(include_mvv=False, include_org_theory=True)

        assert "3つの絶対原則" in prompt
        assert "リードマネジメント" in prompt

    def test_get_context_for_prompt_with_user_message(self):
        """ユーザーメッセージ分析結果がプロンプトに含まれる"""
        ctx = MVVContext()
        prompt = ctx.get_context_for_prompt(
            include_mvv=False,
            include_org_theory=False,
            user_message="転職を考えています"
        )

        assert "検出されたパターン" in prompt
        assert "retention" in prompt.lower() or "転職" in prompt

    def test_analyze_user_message(self):
        """ユーザーメッセージ分析"""
        ctx = MVVContext()
        ng_result, need_result = ctx.analyze_user_message("成長できなくて辞めたい")

        assert ng_result.detected is True
        assert ng_result.pattern_type == "ng_retention_critical"
        assert need_result.primary_need == BasicNeed.POWER


# ============================================================
# 4. ユーティリティ関数テスト
# ============================================================

class TestUtilityFunctions:
    """ユーティリティ関数のテスト"""

    def test_get_mvv_context_singleton(self):
        """MVVContextのシングルトン取得"""
        ctx1 = get_mvv_context()
        ctx2 = get_mvv_context()

        assert isinstance(ctx1, MVVContext)
        assert isinstance(ctx2, MVVContext)

    def test_should_flag_for_review_critical(self):
        """CRITICALリスクはフラグ対象"""
        ng_result = NGPatternResult(
            detected=True,
            pattern_type="ng_mental_health",
            risk_level=RiskLevel.CRITICAL,
            flag=True
        )
        assert should_flag_for_review(ng_result) is True

    def test_should_flag_for_review_high(self):
        """HIGHリスクはフラグ対象"""
        ng_result = NGPatternResult(
            detected=True,
            pattern_type="ng_retention_critical",
            risk_level=RiskLevel.HIGH,
            flag=True
        )
        assert should_flag_for_review(ng_result) is True

    def test_should_not_flag_for_review_low(self):
        """LOWリスクはフラグ対象外"""
        ng_result = NGPatternResult(
            detected=True,
            pattern_type="ng_hr_authority",
            risk_level=RiskLevel.LOW,
            flag=False
        )
        assert should_flag_for_review(ng_result) is False

    def test_should_not_flag_when_not_detected(self):
        """検出されていない場合はフラグ対象外"""
        ng_result = NGPatternResult(detected=False)
        assert should_flag_for_review(ng_result) is False

    def test_get_situation_response_guide_exists(self):
        """状況別対応ガイドが取得できる"""
        guide = get_situation_response_guide("やる気がない")
        assert guide is not None
        assert "steps" in guide
        assert "ng" in guide

    def test_get_situation_response_guide_quit(self):
        """辞めたいケースのガイド"""
        guide = get_situation_response_guide("辞めたい")
        assert guide is not None
        assert len(guide["steps"]) >= 5
        assert "過去の良い経験" in "".join(guide["steps"])

    def test_get_situation_response_guide_failure(self):
        """失敗ケースのガイド"""
        guide = get_situation_response_guide("失敗")
        assert guide is not None
        assert "学び" in "".join(guide["steps"])

    def test_get_situation_response_guide_not_found(self):
        """存在しない状況"""
        guide = get_situation_response_guide("存在しない状況")
        assert guide is None

    def test_get_situation_response_guide_high_goal(self):
        """目標が高すぎるケースのガイド"""
        guide = get_situation_response_guide("目標が高すぎる")
        assert guide is not None
        assert len(guide["steps"]) >= 5
        assert "内発的動機" in "".join(guide["steps"])
        assert "無理" in guide["ng"][0]  # NG発言に「無理」が含まれる

    def test_get_situation_response_guide_relationship(self):
        """人間関係の悩みケースのガイド"""
        guide = get_situation_response_guide("人間関係の悩み")
        assert guide is not None
        assert "選択理論" in "".join(guide["steps"])
        assert "関わり方" in "".join(guide["steps"])

    def test_get_situation_response_guide_success(self):
        """成功した時のケースのガイド"""
        guide = get_situation_response_guide("成功した時")
        assert guide is not None
        assert "祝福" in guide["steps"][0]
        assert "MVV" in "".join(guide["steps"])
        assert "感謝" in "".join(guide["steps"])


# ============================================================
# 5. 定数・データ構造テスト
# ============================================================

class TestConstantsAndDataStructures:
    """定数とデータ構造のテスト"""

    def test_soulsync_mvv_structure(self):
        """MVV定数の構造"""
        assert "mission" in SOULSYNC_MVV
        assert "vision" in SOULSYNC_MVV
        assert "values" in SOULSYNC_MVV
        assert "slogan" in SOULSYNC_MVV

        assert "statement" in SOULSYNC_MVV["mission"]
        assert "description" in SOULSYNC_MVV["mission"]

    def test_behavioral_guidelines_count(self):
        """行動指針が10個ある"""
        assert len(BEHAVIORAL_GUIDELINES_10) == 10

    def test_behavioral_guidelines_structure(self):
        """行動指針の構造"""
        for guideline in BEHAVIORAL_GUIDELINES_10:
            assert "number" in guideline
            assert "title" in guideline
            assert "theory" in guideline
            assert "soulkun_action" in guideline
            assert "example" in guideline
            assert "ウル" in guideline["example"]  # ソウルくん口調

    def test_organizational_theory_prompt_content(self):
        """組織論プロンプトの内容"""
        assert "3つの絶対原則" in ORGANIZATIONAL_THEORY_PROMPT
        assert "絶対にやらないこと" in ORGANIZATIONAL_THEORY_PROMPT
        assert "積極的にやること" in ORGANIZATIONAL_THEORY_PROMPT
        assert "5つの基本欲求" in ORGANIZATIONAL_THEORY_PROMPT
        assert "リードマネジメント" in ORGANIZATIONAL_THEORY_PROMPT

    def test_ng_patterns_all_have_required_fields(self):
        """NGパターンに必要なフィールドがある"""
        for pattern_key, pattern in NG_PATTERNS.items():
            assert "keywords" in pattern, f"Missing keywords in {pattern_key}"
            assert "response_hint" in pattern, f"Missing response_hint in {pattern_key}"
            assert len(pattern["keywords"]) > 0, f"Empty keywords in {pattern_key}"

    def test_basic_need_keywords_all_have_required_fields(self):
        """基本欲求キーワードに必要なフィールドがある"""
        for need, config in BASIC_NEED_KEYWORDS.items():
            assert "keywords" in config
            assert "question" in config
            assert "approach" in config
            assert len(config["keywords"]) > 0


# ============================================================
# 6. エッジケーステスト
# ============================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    def test_empty_message(self):
        """空メッセージの処理"""
        ng_result = detect_ng_pattern("")
        assert ng_result.detected is False

        need_result = analyze_basic_needs("")
        assert need_result.primary_need is None

    def test_very_long_message(self):
        """非常に長いメッセージの処理"""
        long_message = "今日は良い天気ですね。" * 1000
        ng_result = detect_ng_pattern(long_message)
        assert ng_result.detected is False

        need_result = analyze_basic_needs(long_message)
        # 特定の欲求は検出されない
        assert need_result.confidence < 0.3 or need_result.primary_need is None

    def test_special_characters_in_message(self):
        """特殊文字を含むメッセージ"""
        messages = [
            "🔥転職したい🔥",
            "<script>alert('辞めたい')</script>",
            "【重要】評価について",
        ]

        for message in messages:
            # エラーなく処理される
            ng_result = detect_ng_pattern(message)
            # キーワードが含まれていれば検出される
            if "転職" in message or "辞めたい" in message or "評価" in message:
                assert ng_result.detected is True

    def test_case_insensitivity(self):
        """大文字小文字の区別"""
        # 日本語なので大文字小文字は関係ない
        result = detect_ng_pattern("転職")
        assert result.detected is True

    def test_multiple_keywords_same_category(self):
        """同じカテゴリの複数キーワード"""
        message = "成長したい、達成感がほしい、認められたい"
        result = analyze_basic_needs(message)
        assert result.primary_need == BasicNeed.POWER
        assert result.confidence > 0.5  # 複数マッチで確信度UP


# ============================================================
# 7. 統合テスト
# ============================================================

class TestIntegration:
    """統合テスト"""

    def test_full_workflow_retention_risk(self):
        """帰属意識リスクの完全ワークフロー"""
        message = "もう辞めたい。成長できない。孤独を感じる。"

        # 1. NGパターン検出
        ng_result = detect_ng_pattern(message)
        assert ng_result.detected is True
        assert ng_result.pattern_type == "ng_retention_critical"

        # 2. 基本欲求分析
        need_result = analyze_basic_needs(message)
        assert need_result.primary_need is not None

        # 3. フラグ判定
        should_flag = should_flag_for_review(ng_result)
        assert should_flag is True

        # 4. 対応ガイド取得
        guide = get_situation_response_guide("辞めたい")
        assert guide is not None

    def test_full_context_generation(self):
        """完全なコンテキスト生成"""
        ctx = MVVContext()
        full_context = ctx.get_context_for_prompt(
            include_mvv=True,
            include_org_theory=True,
            user_message="転職を考えています。成長できない気がして…"
        )

        # 全ての要素が含まれている
        assert "ミッション" in full_context or "可能性の解放" in full_context
        assert "3つの絶対原則" in full_context
        assert "検出されたパターン" in full_context
        assert "基本欲求分析" in full_context


# ============================================================
# 8. MVV質問検出テスト (v10.22.6)
# ============================================================

class TestMVVQuestionDetection:
    """MVV質問検出のテスト"""

    @pytest.mark.parametrize("message", [
        "MVVって何？",
        "MVVを教えて",
        "ミッションとビジョンを教えて",
        "会社の理念は？",
        "企業理念について知りたい",
        "ソウルシンクスのビジョンは？",
        "行動指針って何？",
        "スローガンを教えて",
        "うちの会社の目標って何？",
    ])
    def test_mvv_question_detected(self, message):
        """MVV関連の質問が検出される"""
        assert is_mvv_question(message) is True

    @pytest.mark.parametrize("message", [
        "おはようございます",
        "今日のタスクは？",
        "ミーティングの予定を教えて",
        "売上を報告します",
        "プロジェクトの進捗は順調です",
    ])
    def test_non_mvv_question_not_detected(self, message):
        """MVV関連でない質問は検出されない"""
        assert is_mvv_question(message) is False

    def test_get_full_mvv_info_contains_all_sections(self):
        """完全なMVV情報に全セクションが含まれる"""
        info = get_full_mvv_info()

        # ミッション
        assert "ミッション" in info
        assert "可能性の解放" in info

        # ビジョン
        assert "ビジョン" in info
        assert "心で繋がる未来を目指します" in info

        # バリュー = 行動指針10箇条
        assert "バリュー" in info
        assert "行動指針10箇条" in info

        # スローガン
        assert "スローガン" in info
        assert "感謝で自分を満たし" in info
        assert "さあ、自分の可能性に挑戦しよう" in info

        # 行動指針
        assert "理想の未来のために何をすべきか考え、行動する" in info

    def test_get_full_mvv_info_includes_guidelines_count(self):
        """行動指針が10個含まれる"""
        info = get_full_mvv_info()
        # 1〜10の番号が含まれているか
        for i in range(1, 11):
            assert f"{i}." in info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
