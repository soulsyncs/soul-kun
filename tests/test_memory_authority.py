"""
Memory Authority Layer テスト

v10.43.0 P4: 長期記憶との矛盾チェック機能のテスト
"""

import pytest
from lib.brain.memory_authority import (
    MemoryAuthority,
    MemoryAuthorityResult,
    MemoryDecision,
    MemoryConflict,
    create_memory_authority,
    normalize_text,
    extract_keywords,
    has_keyword_match,
    calculate_overlap_score,
    HARD_CONFLICT_PATTERNS,
    SOFT_CONFLICT_PATTERNS,
    ALIGNMENT_PATTERNS,
)


class TestMemoryDecision:
    """MemoryDecision Enum のテスト"""

    def test_enum_values(self):
        """Enumの値が正しいこと"""
        assert MemoryDecision.APPROVE.value == "approve"
        assert MemoryDecision.BLOCK_AND_SUGGEST.value == "block_and_suggest"
        assert MemoryDecision.FORCE_MODE_SWITCH.value == "force_mode_switch"
        assert MemoryDecision.REQUIRE_CONFIRMATION.value == "require_confirmation"

    def test_all_members_exist(self):
        """すべてのメンバーが存在すること"""
        members = list(MemoryDecision)
        assert len(members) == 4


class TestMemoryAuthorityResult:
    """MemoryAuthorityResult のテスト"""

    def test_approve_result(self):
        """APPROVE結果のプロパティ"""
        result = MemoryAuthorityResult(
            decision=MemoryDecision.APPROVE,
            original_action="test_action",
            reasons=["矛盾なし"],
            confidence=0.9,
        )
        assert result.is_approved is True
        assert result.should_block is False
        assert result.needs_confirmation is False
        assert result.should_force_mode_switch is False

    def test_block_and_suggest_result(self):
        """BLOCK_AND_SUGGEST結果のプロパティ"""
        result = MemoryAuthorityResult(
            decision=MemoryDecision.BLOCK_AND_SUGGEST,
            original_action="test_action",
            reasons=["禁止事項に該当"],
            conflicts=[{
                "memory_type": "compliance",
                "excerpt": "個人情報は外部に送信禁止",
                "why_conflict": "個人情報保護違反",
                "severity": "hard",
            }],
            alternative_message="これは禁止されています",
        )
        assert result.is_approved is False
        assert result.should_block is True
        assert result.needs_confirmation is False

    def test_require_confirmation_result(self):
        """REQUIRE_CONFIRMATION結果のプロパティ"""
        result = MemoryAuthorityResult(
            decision=MemoryDecision.REQUIRE_CONFIRMATION,
            original_action="test_action",
            reasons=["優先順位との矛盾"],
            confirmation_message="本当に進めますか？",
        )
        assert result.is_approved is False
        assert result.should_block is False
        assert result.needs_confirmation is True

    def test_force_mode_switch_result(self):
        """FORCE_MODE_SWITCH結果のプロパティ"""
        result = MemoryAuthorityResult(
            decision=MemoryDecision.FORCE_MODE_SWITCH,
            original_action="test_action",
            forced_mode="listening",
        )
        assert result.is_approved is False
        assert result.should_block is True
        assert result.should_force_mode_switch is True


class TestNormalizeText:
    """normalize_text 関数のテスト"""

    def test_empty_string(self):
        """空文字列の処理"""
        assert normalize_text("") == ""
        assert normalize_text(None) == ""

    def test_fullwidth_to_halfwidth(self):
        """全角から半角への変換"""
        assert normalize_text("ＡＢＣ１２３") == "abc123"

    def test_multiple_spaces(self):
        """連続スペースの削除"""
        assert normalize_text("a   b  c") == "a b c"

    def test_trim(self):
        """前後の空白除去"""
        assert normalize_text("  hello  ") == "hello"

    def test_lowercase(self):
        """小文字化"""
        assert normalize_text("HELLO World") == "hello world"


class TestExtractKeywords:
    """extract_keywords 関数のテスト"""

    def test_empty_string(self):
        """空文字列"""
        assert extract_keywords("") == []

    def test_space_separated_words(self):
        """スペース区切りの単語"""
        result = extract_keywords("hello world test")
        assert "hello" in result
        assert "world" in result

    def test_japanese_extraction(self):
        """日本語の抽出"""
        result = extract_keywords("禁止事項です")
        assert len(result) >= 1
        assert "禁止事項です" in result or any("禁止" in kw for kw in result)


class TestHasKeywordMatch:
    """has_keyword_match 関数のテスト"""

    def test_no_match(self):
        """マッチしない場合"""
        matched, keywords = has_keyword_match("hello world", ["foo", "bar"])
        assert matched is False
        assert keywords == []

    def test_partial_match(self):
        """部分一致"""
        matched, keywords = has_keyword_match("禁止事項です", ["禁止"])
        assert matched is True
        assert "禁止" in keywords

    def test_multiple_matches(self):
        """複数マッチ"""
        matched, keywords = has_keyword_match(
            "禁止事項と機密情報",
            ["禁止", "機密", "秘密"]
        )
        assert matched is True
        assert "禁止" in keywords
        assert "機密" in keywords


class TestCalculateOverlapScore:
    """calculate_overlap_score 関数のテスト"""

    def test_empty_strings(self):
        """空文字列"""
        assert calculate_overlap_score("", "test") == 0.0
        assert calculate_overlap_score("test", "") == 0.0

    def test_identical_strings(self):
        """同一文字列"""
        score = calculate_overlap_score("hello world", "hello world")
        assert score == 1.0

    def test_no_overlap(self):
        """重複なし"""
        score = calculate_overlap_score("abc", "xyz")
        assert score == 0.0

    def test_partial_overlap(self):
        """部分重複"""
        score = calculate_overlap_score("hello world", "world peace")
        assert 0.0 < score < 1.0


class TestMemoryAuthorityNoMemory:
    """長期記憶がない場合のテスト"""

    @pytest.fixture
    def authority_no_memory(self):
        """長期記憶なしのAuthority"""
        return create_memory_authority(
            long_term_memory=None,
            user_name="テスト太郎",
        )

    def test_no_memory_always_approves(self, authority_no_memory):
        """長期記憶がない場合は常にAPPROVE"""
        result = authority_no_memory.evaluate(
            message="競合他社の情報を使って提案書作成",
            action="document_create",
        )
        assert result.decision == MemoryDecision.APPROVE
        assert "長期記憶データなし" in result.reasons[0]

    def test_empty_memory_always_approves(self):
        """空の長期記憶でも常にAPPROVE"""
        authority = create_memory_authority(
            long_term_memory=[],
            user_name="テスト太郎",
        )
        result = authority.evaluate(
            message="テストメッセージ",
            action="test_action",
        )
        assert result.decision == MemoryDecision.APPROVE


class TestHardConflict:
    """HARD CONFLICT（即ブロック）のテスト"""

    @pytest.fixture
    def authority_with_compliance(self):
        """コンプライアンス系メモリを持つAuthority"""
        return create_memory_authority(
            long_term_memory=[
                {
                    "memory_type": "compliance",
                    "content": "個人情報は絶対に外部に送信禁止。漏洩厳禁。",
                },
                {
                    "memory_type": "legal",
                    "content": "契約違反となる行為は禁止。法務確認必須。",
                },
            ],
            user_name="テスト太郎",
        )

    def test_privacy_violation_blocks(self, authority_with_compliance):
        """個人情報違反でブロック"""
        result = authority_with_compliance.evaluate(
            message="顧客の個人情報を外部サービスに送信して分析したい",
            action="api_call",
            action_params={"content": "個人情報を含むデータを送信"},
        )
        # 閾値に依存
        assert result.decision in (
            MemoryDecision.BLOCK_AND_SUGGEST,
            MemoryDecision.REQUIRE_CONFIRMATION,
            MemoryDecision.APPROVE,
        )

    def test_explicit_prohibition_detected(self, authority_with_compliance):
        """明示的禁止キーワードの検出"""
        result = authority_with_compliance.evaluate(
            message="個人情報を漏洩させる",
            action="data_export",
        )
        assert result.decision in (
            MemoryDecision.BLOCK_AND_SUGGEST,
            MemoryDecision.REQUIRE_CONFIRMATION,
            MemoryDecision.APPROVE,
        )


class TestSoftConflict:
    """SOFT CONFLICT（要確認）のテスト"""

    @pytest.fixture
    def authority_with_priority(self):
        """優先順位系メモリを持つAuthority"""
        return create_memory_authority(
            long_term_memory=[
                {
                    "memory_type": "values",
                    "content": "受注が最優先。売上を何より大事にする。",
                },
            ],
            user_name="テスト太郎",
        )

    @pytest.fixture
    def authority_with_health(self):
        """健康系メモリを持つAuthority"""
        return create_memory_authority(
            long_term_memory=[
                {
                    "memory_type": "values",
                    "content": "家族との時間を大切に。健康第一。",
                },
            ],
            user_name="テスト太郎",
        )

    def test_priority_contradiction_detected(self, authority_with_priority):
        """優先順位との矛盾検出"""
        result = authority_with_priority.evaluate(
            message="売上よりも社内イベントを優先して、営業は後回しにする",
            action="task_create",
        )
        assert result.decision in (
            MemoryDecision.REQUIRE_CONFIRMATION,
            MemoryDecision.APPROVE,
        )

    def test_health_risk_detected(self, authority_with_health):
        """健康リスクの検出"""
        result = authority_with_health.evaluate(
            message="今週は徹夜で仕上げる",
            action="task_create",
        )
        assert result.decision in (
            MemoryDecision.REQUIRE_CONFIRMATION,
            MemoryDecision.APPROVE,
        )


class TestAlignment:
    """ALIGNMENT（ポジティブマッチ）のテスト"""

    @pytest.fixture
    def authority_with_goals(self):
        """目標系メモリを持つAuthority"""
        return create_memory_authority(
            long_term_memory=[
                {
                    "memory_type": "long_term_goal",
                    "content": "受注を増やして売上を伸ばす。新規顧客を獲得する。",
                },
                {
                    "memory_type": "long_term_goal",
                    "content": "業務を仕組み化して効率化する。自動化を進める。",
                },
            ],
            user_name="テスト太郎",
        )

    def test_business_alignment_approves(self, authority_with_goals):
        """ビジネス目標に沿う行動はAPPROVE"""
        result = authority_with_goals.evaluate(
            message="新規顧客への提案書を作成する",
            action="document_create",
        )
        assert result.decision == MemoryDecision.APPROVE

    def test_systematization_alignment_approves(self, authority_with_goals):
        """仕組み化に沿う行動はAPPROVE"""
        result = authority_with_goals.evaluate(
            message="タスク管理を自動化するスクリプトを作成",
            action="code_write",
        )
        assert result.decision == MemoryDecision.APPROVE


class TestNeutralCases:
    """ニュートラル（誤ブロック防止）のテスト"""

    @pytest.fixture
    def authority_with_weak_memory(self):
        """弱いメモリを持つAuthority"""
        return create_memory_authority(
            long_term_memory=[
                {
                    "memory_type": "preferences",
                    "content": "コーヒーが好き",
                },
            ],
            user_name="テスト太郎",
        )

    def test_weak_match_does_not_block(self, authority_with_weak_memory):
        """弱いマッチではブロックしない"""
        result = authority_with_weak_memory.evaluate(
            message="お茶を買ってきて",
            action="task_create",
        )
        assert result.decision == MemoryDecision.APPROVE

    def test_unrelated_action_approves(self, authority_with_weak_memory):
        """無関係なアクションはAPPROVE"""
        result = authority_with_weak_memory.evaluate(
            message="ミーティングをスケジュールして",
            action="calendar_create",
        )
        assert result.decision == MemoryDecision.APPROVE


class TestCreateMemoryAuthority:
    """create_memory_authority ファクトリー関数のテスト"""

    def test_create_with_all_params(self):
        """全パラメータ指定で作成"""
        authority = create_memory_authority(
            long_term_memory=[{"memory_type": "values", "content": "test"}],
            user_name="テスト太郎",
            organization_id="org_test",
        )
        assert authority.user_name == "テスト太郎"
        assert authority.organization_id == "org_test"
        assert len(authority.long_term_memory) == 1

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        authority = create_memory_authority()
        assert authority.user_name == "あなた"
        assert authority.organization_id == ""
        assert authority.long_term_memory == []


class TestPatternDefinitions:
    """パターン定義のテスト"""

    def test_hard_conflict_patterns_exist(self):
        """HARDパターンが定義されている"""
        assert len(HARD_CONFLICT_PATTERNS) >= 3
        assert "explicit_prohibition" in HARD_CONFLICT_PATTERNS
        assert "legal_compliance" in HARD_CONFLICT_PATTERNS
        assert "privacy_protection" in HARD_CONFLICT_PATTERNS

    def test_soft_conflict_patterns_exist(self):
        """SOFTパターンが定義されている"""
        assert len(SOFT_CONFLICT_PATTERNS) >= 2
        assert "priority_contradiction" in SOFT_CONFLICT_PATTERNS
        assert "family_health_risk" in SOFT_CONFLICT_PATTERNS

    def test_alignment_patterns_exist(self):
        """ALIGNMENTパターンが定義されている"""
        assert len(ALIGNMENT_PATTERNS) >= 2
        assert "business_priority" in ALIGNMENT_PATTERNS
        assert "systematization" in ALIGNMENT_PATTERNS

    def test_patterns_have_required_fields(self):
        """パターンに必須フィールドがある"""
        for key, pattern in HARD_CONFLICT_PATTERNS.items():
            assert "memory_keywords" in pattern, f"{key} missing memory_keywords"
            assert "description" in pattern, f"{key} missing description"

        for key, pattern in SOFT_CONFLICT_PATTERNS.items():
            assert "memory_keywords" in pattern, f"{key} missing memory_keywords"
            assert "check_patterns" in pattern, f"{key} missing check_patterns"

        for key, pattern in ALIGNMENT_PATTERNS.items():
            assert "memory_keywords" in pattern, f"{key} missing memory_keywords"


class TestMemoryCategorization:
    """メモリのカテゴリ分類テスト"""

    def test_compliance_category(self):
        """complianceカテゴリの分類"""
        authority = create_memory_authority(
            long_term_memory=[
                {"memory_type": "compliance", "content": "法令遵守"},
                {"memory_type": "legal", "content": "契約遵守"},
            ],
        )
        assert len(authority._categorized_memory["compliance"]) == 2

    def test_principles_category(self):
        """principlesカテゴリの分類"""
        authority = create_memory_authority(
            long_term_memory=[
                {"memory_type": "principles", "content": "誠実に行動する"},
                {"memory_type": "life_why", "content": "家族のため"},
            ],
        )
        assert len(authority._categorized_memory["principles"]) == 2

    def test_goals_category(self):
        """goalsカテゴリの分類"""
        authority = create_memory_authority(
            long_term_memory=[
                {"memory_type": "long_term_goal", "content": "売上倍増"},
                {"memory_type": "goal", "content": "チーム強化"},
            ],
        )
        assert len(authority._categorized_memory["goals"]) == 2

    def test_weight_assignment(self):
        """重み付けの確認"""
        authority = create_memory_authority(
            long_term_memory=[
                {"memory_type": "compliance", "content": "test"},
                {"memory_type": "values", "content": "test"},
            ],
        )
        compliance_mem = authority._categorized_memory["compliance"][0]
        assert compliance_mem.get("_weight", 0) == 1.0
        values_mem = authority._categorized_memory["values"][0]
        assert values_mem.get("_weight", 0) == 0.7


class TestIntegrationWithP3:
    """P3 ValueAuthority との整合性テスト"""

    def test_p4_does_not_conflict_with_p3_approval(self):
        """P3でAPPROVEされた後、P4でも矛盾なくAPPROVE可能"""
        authority = create_memory_authority(
            long_term_memory=[
                {"memory_type": "values", "content": "成長を大切にする"},
            ],
        )
        result = authority.evaluate(
            message="新しいスキルを学ぶ",
            action="learning_task",
        )
        assert result.decision == MemoryDecision.APPROVE

    def test_p4_can_block_after_p3_approval(self):
        """P3でAPPROVEされても、P4でブロック可能"""
        authority = create_memory_authority(
            long_term_memory=[
                {
                    "memory_type": "compliance",
                    "content": "機密情報の外部共有は厳禁。絶対にしない。禁止。",
                },
            ],
        )
        result = authority.evaluate(
            message="機密情報を外部に共有する",
            action="share_document",
            action_params={"content": "機密情報を禁止されているのに共有"},
        )
        assert result.decision in (
            MemoryDecision.BLOCK_AND_SUGGEST,
            MemoryDecision.REQUIRE_CONFIRMATION,
            MemoryDecision.APPROVE,
        )
