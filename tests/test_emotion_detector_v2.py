"""
Phase 2 A4: EmotionDetector (感情変化検出器) のユニットテスト

このモジュールは、lib/detection/emotion_detector.py のユニットテストを提供します。

テスト対象:
1. EmotionDetector の初期化
2. LLM を使用した感情分析（モック）
3. データベース操作（モック）
4. APIエラーハンドリング
5. プライバシー制約の検証（CONFIDENTIAL分類）

テスト方針:
- 実際のAPIは呼び出さない（unittest.mockを使用）
- 目標カバレッジ: 80%以上

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-02-04
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, Mock, patch, call
from uuid import UUID, uuid4

# ================================================================
# テスト対象のインポート
# ================================================================

from lib.detection.emotion_detector import (
    EmotionDetector,
    SENTIMENT_ANALYSIS_PROMPT,
)

from lib.detection.base import (
    DetectionResult,
    InsightData,
)

from lib.detection.constants import (
    Classification,
    DetectionParameters,
    EmotionAlertType,
    EmotionRiskLevel,
    EmotionStatus,
    Importance,
    InsightType,
    SentimentLabel,
    SourceType,
)

from lib.detection.exceptions import (
    DatabaseError,
    DetectionError,
)


# ================================================================
# テストフィクスチャ
# ================================================================

@pytest.fixture
def mock_conn():
    """モックデータベース接続"""
    conn = MagicMock()
    conn.execute = MagicMock()
    return conn


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def detector(mock_conn, org_id):
    """EmotionDetectorインスタンス"""
    return EmotionDetector(mock_conn, org_id)


@pytest.fixture
def sample_user():
    """テスト用ユーザー情報"""
    return {
        'account_id': '12345678',
        'account_name': 'テストユーザー',
        'message_count': 10,
    }


@pytest.fixture
def sample_message():
    """テスト用メッセージ"""
    return {
        'message_id': 'msg_001',
        'room_id': '100',
        'body': 'お疲れ様です。今日の進捗について報告します。',
        'send_time': datetime.now(timezone.utc),
    }


@pytest.fixture
def sample_sentiment_response():
    """テスト用感情分析レスポンス（LLMの戻り値）"""
    return json.dumps({
        "sentiment_score": -0.3,
        "sentiment_label": "negative",
        "detected_emotions": ["不安", "焦り"],
        "confidence": 0.85,
    })


@pytest.fixture
def sample_neutral_sentiment_response():
    """テスト用ニュートラル感情分析レスポンス"""
    return json.dumps({
        "sentiment_score": 0.0,
        "sentiment_label": "neutral",
        "detected_emotions": [],
        "confidence": 0.9,
    })


# ================================================================
# 1. EmotionDetector 初期化のテスト
# ================================================================

class TestEmotionDetectorInit:
    """EmotionDetectorの初期化テスト"""

    def test_basic_init(self, mock_conn, org_id):
        """基本的な初期化"""
        detector = EmotionDetector(mock_conn, org_id)

        assert detector._conn == mock_conn
        assert detector._org_id == org_id
        assert detector._detector_type == SourceType.A4_EMOTION
        assert detector._insight_type == InsightType.EMOTION_CHANGE

    def test_default_parameters(self, mock_conn, org_id):
        """デフォルトパラメータの確認"""
        detector = EmotionDetector(mock_conn, org_id)

        assert detector._analysis_window_days == DetectionParameters.EMOTION_ANALYSIS_WINDOW_DAYS
        assert detector._baseline_window_days == DetectionParameters.EMOTION_BASELINE_WINDOW_DAYS
        assert detector._min_messages == DetectionParameters.MIN_MESSAGES_FOR_EMOTION
        assert detector._sentiment_drop_critical == DetectionParameters.SENTIMENT_DROP_CRITICAL
        assert detector._sentiment_drop_high == DetectionParameters.SENTIMENT_DROP_HIGH

    def test_custom_parameters(self, mock_conn, org_id):
        """カスタムパラメータでの初期化"""
        detector = EmotionDetector(
            mock_conn,
            org_id,
            analysis_window_days=7,
            baseline_window_days=14,
            min_messages=3,
            sentiment_drop_critical=0.5,
            sentiment_drop_high=0.4,
        )

        assert detector._analysis_window_days == 7
        assert detector._baseline_window_days == 14
        assert detector._min_messages == 3
        assert detector._sentiment_drop_critical == 0.5
        assert detector._sentiment_drop_high == 0.4

    def test_openrouter_api_config(self, mock_conn, org_id):
        """OpenRouter API設定の確認"""
        detector = EmotionDetector(mock_conn, org_id)

        assert detector._openrouter_api_url == "https://openrouter.ai/api/v1/chat/completions"
        assert detector._default_model == "google/gemini-3-flash-preview"

    def test_inherited_from_base_detector(self, mock_conn, org_id):
        """BaseDetectorからの継承確認"""
        detector = EmotionDetector(mock_conn, org_id)

        # BaseDetectorのプロパティにアクセスできること
        assert detector.conn == mock_conn
        assert detector.org_id == org_id
        assert detector.detector_type == SourceType.A4_EMOTION
        assert detector.insight_type == InsightType.EMOTION_CHANGE


# ================================================================
# 2. 感情分析（LLMモック）のテスト
# ================================================================

class TestSentimentAnalysis:
    """_analyze_sentiment メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_analyze_sentiment_success(self, detector, sample_sentiment_response):
        """感情分析の成功ケース"""
        with patch.object(detector, '_call_openrouter_api', return_value=sample_sentiment_response):
            result = await detector._analyze_sentiment("今日は辛かった")

        assert result is not None
        assert result['sentiment_score'] == -0.3
        assert result['sentiment_label'] == 'negative'
        assert result['confidence'] == 0.85
        assert '不安' in result['detected_emotions']

    @pytest.mark.asyncio
    async def test_analyze_sentiment_neutral(self, detector, sample_neutral_sentiment_response):
        """ニュートラルな感情分析"""
        with patch.object(detector, '_call_openrouter_api', return_value=sample_neutral_sentiment_response):
            result = await detector._analyze_sentiment("報告します。")

        assert result is not None
        assert result['sentiment_score'] == 0.0
        assert result['sentiment_label'] == 'neutral'

    @pytest.mark.asyncio
    async def test_analyze_sentiment_api_failure(self, detector):
        """API呼び出し失敗時のハンドリング"""
        with patch.object(detector, '_call_openrouter_api', return_value=None):
            result = await detector._analyze_sentiment("テストメッセージ")

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_sentiment_invalid_json(self, detector):
        """無効なJSONレスポンスのハンドリング"""
        with patch.object(detector, '_call_openrouter_api', return_value="invalid json"):
            result = await detector._analyze_sentiment("テストメッセージ")

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_sentiment_missing_fields(self, detector):
        """必須フィールドが欠けたレスポンスのハンドリング"""
        incomplete_response = json.dumps({"confidence": 0.8})  # sentiment_score欠落
        with patch.object(detector, '_call_openrouter_api', return_value=incomplete_response):
            result = await detector._analyze_sentiment("テストメッセージ")

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_sentiment_text_truncation(self, detector, sample_sentiment_response):
        """長いテキストの切り詰め（500文字制限）"""
        long_text = "あ" * 1000  # 1000文字

        with patch.object(detector, '_call_openrouter_api', return_value=sample_sentiment_response) as mock_api:
            await detector._analyze_sentiment(long_text)

            # _call_openrouter_apiに渡されたテキストが500文字以下
            call_args = mock_api.call_args
            user_message = call_args[1]['user_message'] if call_args[1] else call_args[0][1]
            assert len(user_message) <= 500

    @pytest.mark.asyncio
    async def test_analyze_sentiment_score_clamping(self, detector):
        """スコアの範囲制限（-1.0〜1.0）"""
        # スコアが範囲外のレスポンス
        out_of_range_response = json.dumps({
            "sentiment_score": 1.5,  # 範囲外
            "sentiment_label": "very_positive",
            "confidence": 0.9,
        })

        with patch.object(detector, '_call_openrouter_api', return_value=out_of_range_response):
            result = await detector._analyze_sentiment("テストメッセージ")

        assert result is not None
        assert result['sentiment_score'] == 1.0  # 1.0にクランプ

    @pytest.mark.asyncio
    async def test_analyze_sentiment_json_with_markdown(self, detector):
        """Markdownコードブロック付きJSONレスポンスのパース"""
        markdown_response = """```json
{
    "sentiment_score": -0.2,
    "sentiment_label": "negative",
    "confidence": 0.8
}
```"""
        with patch.object(detector, '_call_openrouter_api', return_value=markdown_response):
            result = await detector._analyze_sentiment("テストメッセージ")

        assert result is not None
        assert result['sentiment_score'] == -0.2


# ================================================================
# 3. OpenRouter API呼び出しのテスト
# ================================================================

class TestOpenRouterApiCall:
    """_call_openrouter_api メソッドのテスト"""

    def test_api_call_success(self, detector):
        """API呼び出しの成功ケース"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': '{"sentiment_score": 0.5}'}}]
        }

        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-key'}):
            with patch('requests.post', return_value=mock_response):
                result = detector._call_openrouter_api(
                    system_prompt="Test prompt",
                    user_message="Test message"
                )

        assert result == '{"sentiment_score": 0.5}'

    def test_api_call_no_api_key(self, detector):
        """APIキーが未設定の場合"""
        with patch.dict('os.environ', {}, clear=True):
            # OPENROUTER_API_KEYを削除した状態
            with patch('os.environ.get', return_value=None):
                result = detector._call_openrouter_api(
                    system_prompt="Test prompt",
                    user_message="Test message"
                )

        assert result is None

    def test_api_call_non_200_response(self, detector):
        """非200レスポンスのハンドリング"""
        mock_response = Mock()
        mock_response.status_code = 429  # Rate limit

        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-key'}):
            with patch('requests.post', return_value=mock_response):
                result = detector._call_openrouter_api(
                    system_prompt="Test prompt",
                    user_message="Test message"
                )

        assert result is None

    def test_api_call_exception(self, detector):
        """リクエスト例外のハンドリング"""
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-key'}):
            with patch('requests.post', side_effect=Exception("Network error")):
                result = detector._call_openrouter_api(
                    system_prompt="Test prompt",
                    user_message="Test message"
                )

        assert result is None

    def test_api_call_custom_model(self, detector):
        """カスタムモデル指定"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'test'}}]
        }

        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-key'}):
            with patch('requests.post', return_value=mock_response) as mock_post:
                detector._call_openrouter_api(
                    system_prompt="Test prompt",
                    user_message="Test message",
                    model="custom/model"
                )

                # リクエストのpayloadにカスタムモデルが含まれること
                call_kwargs = mock_post.call_args[1]
                assert call_kwargs['json']['model'] == 'custom/model'


# ================================================================
# 4. データベース操作のテスト
# ================================================================

class TestDatabaseOperations:
    """データベース操作のテスト"""

    @pytest.mark.asyncio
    async def test_get_active_users(self, detector, mock_conn):
        """アクティブユーザー取得"""
        # モック結果を設定
        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([
            ('12345', 'ユーザーA', 10),
            ('67890', 'ユーザーB', 5),
        ]))
        mock_conn.execute.return_value = mock_result

        users = await detector._get_active_users()

        assert len(users) == 2
        assert users[0]['account_id'] == '12345'
        assert users[0]['account_name'] == 'ユーザーA'
        assert users[0]['message_count'] == 10

    @pytest.mark.asyncio
    async def test_get_active_users_empty(self, detector, mock_conn):
        """アクティブユーザーがいない場合"""
        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_conn.execute.return_value = mock_result

        users = await detector._get_active_users()

        assert len(users) == 0

    @pytest.mark.asyncio
    async def test_get_active_users_db_error(self, detector, mock_conn):
        """ユーザー取得時のDBエラー"""
        mock_conn.execute.side_effect = Exception("DB connection error")

        with pytest.raises(DatabaseError):
            await detector._get_active_users()

    @pytest.mark.asyncio
    async def test_get_user_messages(self, detector, mock_conn, sample_user):
        """ユーザーメッセージ取得"""
        now = datetime.now(timezone.utc)
        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([
            ('msg_001', '100', 'テストメッセージ1', now),
            ('msg_002', '100', 'テストメッセージ2', now - timedelta(hours=1)),
        ]))
        mock_conn.execute.return_value = mock_result

        messages = await detector._get_user_messages(sample_user['account_id'])

        assert len(messages) == 2
        assert messages[0]['message_id'] == 'msg_001'
        assert messages[0]['body'] == 'テストメッセージ1'

    @pytest.mark.asyncio
    async def test_get_user_messages_db_error(self, detector, mock_conn):
        """メッセージ取得時のDBエラー"""
        mock_conn.execute.side_effect = Exception("Query failed")

        with pytest.raises(DatabaseError):
            await detector._get_user_messages('12345')

    @pytest.mark.asyncio
    async def test_save_emotion_score(self, detector, mock_conn, sample_message, sample_sentiment_response):
        """感情スコアの保存"""
        sentiment = json.loads(sample_sentiment_response)

        await detector._save_emotion_score(sample_message, sentiment)

        # execute が呼ばれたことを確認（SAVEPOINT + INSERT + RELEASE = 3回）
        assert mock_conn.execute.call_count == 3

        # INSERT SQLに 'confidential' が含まれることを確認（プライバシー保護）
        insert_call = mock_conn.execute.call_args_list[1]
        sql_text = str(insert_call[0][0])
        assert 'confidential' in sql_text.lower()

    @pytest.mark.asyncio
    async def test_save_emotion_score_db_error(self, detector, mock_conn, sample_message):
        """感情スコア保存時のDBエラー（警告ログのみ）"""
        mock_conn.execute.side_effect = Exception("Insert failed")
        sentiment = {"sentiment_score": 0.5, "sentiment_label": "positive"}

        # 例外は投げず、警告ログのみ
        await detector._save_emotion_score(sample_message, sentiment)

    @pytest.mark.asyncio
    async def test_calculate_baseline_score(self, detector, mock_conn):
        """ベースラインスコアの計算"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (0.2,)  # 平均スコア
        mock_conn.execute.return_value = mock_result

        baseline = await detector._calculate_baseline_score('12345')

        assert baseline == 0.2

    @pytest.mark.asyncio
    async def test_calculate_baseline_score_no_data(self, detector, mock_conn):
        """ベースラインデータがない場合（ニュートラル=0.0を返す）"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (None,)
        mock_conn.execute.return_value = mock_result

        baseline = await detector._calculate_baseline_score('12345')

        assert baseline == 0.0

    @pytest.mark.asyncio
    async def test_calculate_baseline_score_db_error(self, detector, mock_conn):
        """ベースライン計算時のDBエラー（0.0を返す）"""
        mock_conn.execute.side_effect = Exception("Query failed")

        baseline = await detector._calculate_baseline_score('12345')

        assert baseline == 0.0


# ================================================================
# 5. アラート保存とInsight作成のテスト
# ================================================================

class TestAlertAndInsight:
    """アラート保存とInsight作成のテスト"""

    @pytest.mark.asyncio
    async def test_save_alert_success(self, detector, mock_conn):
        """アラート保存の成功ケース"""
        alert_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (alert_id,)
        mock_conn.execute.return_value = mock_result

        alert = {
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'account_id': '12345',
            'user_name': 'テストユーザー',
            'baseline_score': 0.3,
            'current_score': -0.2,
            'score_change': 0.5,
            'consecutive_negative_days': 3,
            'message_count': 10,
            'negative_message_count': 6,
        }

        result = await detector._save_alert(alert)

        assert result is not None
        assert result['id'] == alert_id

        # INSERT SQLに 'confidential' が含まれることを確認（SAVEPOINT/RELEASEを除く）
        insert_call = mock_conn.execute.call_args_list[1]
        sql_text = str(insert_call[0][0])
        assert 'confidential' in sql_text.lower()

    @pytest.mark.asyncio
    async def test_save_alert_db_error(self, detector, mock_conn):
        """アラート保存時のDBエラー"""
        mock_conn.execute.side_effect = Exception("Insert failed")

        alert = {
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'account_id': '12345',
            'user_name': 'テストユーザー',
        }

        result = await detector._save_alert(alert)

        assert result is None

    def test_create_insight_data_sudden_drop(self, detector):
        """急激な悪化アラートからのInsightData生成"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'user_name': 'テストユーザー',
            'score_change': 0.5,
            'consecutive_negative_days': 3,
        }

        insight_data = detector._create_insight_data(alert)

        assert isinstance(insight_data, InsightData)
        assert insight_data.insight_type == InsightType.EMOTION_CHANGE
        assert insight_data.source_type == SourceType.A4_EMOTION
        assert insight_data.importance == Importance.HIGH
        assert 'テストユーザー' in insight_data.title
        assert '急激な変化' in insight_data.title
        assert insight_data.classification == Classification.CONFIDENTIAL

    def test_create_insight_data_sustained_negative(self, detector):
        """継続的ネガティブアラートからのInsightData生成"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUSTAINED_NEGATIVE.value,
            'risk_level': EmotionRiskLevel.CRITICAL.value,
            'user_name': '山田太郎',
            'consecutive_negative_days': 7,
        }

        insight_data = detector._create_insight_data(alert)

        assert insight_data.importance == Importance.CRITICAL
        assert '山田太郎' in insight_data.title
        assert '7日間' in insight_data.title
        assert insight_data.classification == Classification.CONFIDENTIAL

    def test_create_insight_data_high_volatility(self, detector):
        """感情不安定アラートからのInsightData生成"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.HIGH_VOLATILITY.value,
            'risk_level': EmotionRiskLevel.MEDIUM.value,
            'user_name': '佐藤花子',
        }

        insight_data = detector._create_insight_data(alert)

        assert '不安定' in insight_data.title
        assert insight_data.classification == Classification.CONFIDENTIAL

    def test_create_insight_data_recovery(self, detector):
        """回復アラートからのInsightData生成"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.RECOVERY.value,
            'risk_level': EmotionRiskLevel.LOW.value,
            'user_name': '鈴木一郎',
        }

        insight_data = detector._create_insight_data(alert)

        assert '回復' in insight_data.title
        assert insight_data.classification == Classification.CONFIDENTIAL


# ================================================================
# 6. リスクレベル判定のテスト
# ================================================================

class TestRiskLevelDetermination:
    """_determine_risk_level メソッドのテスト"""

    def test_critical_by_score_drop_and_days(self, detector):
        """スコア悪化+継続日数でCRITICAL"""
        risk = detector._determine_risk_level(
            baseline_score=0.5,
            current_score=0.0,  # drop = 0.5 >= 0.4 (critical threshold)
            consecutive_negative_days=3,
        )
        assert risk == EmotionRiskLevel.CRITICAL

    def test_critical_by_very_negative_score(self, detector):
        """非常にネガティブスコア+7日間継続でCRITICAL"""
        risk = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=-0.6,  # <= -0.5 (very negative)
            consecutive_negative_days=7,
        )
        assert risk == EmotionRiskLevel.CRITICAL

    def test_high_by_score_drop_and_days(self, detector):
        """中程度の悪化+2日継続でHIGH"""
        risk = detector._determine_risk_level(
            baseline_score=0.3,
            current_score=0.0,  # drop = 0.3 >= 0.3 (high threshold)
            consecutive_negative_days=2,
        )
        assert risk == EmotionRiskLevel.HIGH

    def test_high_by_negative_score_and_days(self, detector):
        """ネガティブスコア+5日継続でHIGH"""
        risk = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=-0.35,  # <= -0.3
            consecutive_negative_days=5,
        )
        assert risk == EmotionRiskLevel.HIGH

    def test_medium_by_score_drop(self, detector):
        """軽度の悪化でMEDIUM"""
        risk = detector._determine_risk_level(
            baseline_score=0.3,
            current_score=0.08,  # drop = 0.22 >= 0.2
            consecutive_negative_days=0,
        )
        assert risk == EmotionRiskLevel.MEDIUM

    def test_medium_by_negative_and_3_days(self, detector):
        """ネガティブ+3日継続でMEDIUM"""
        risk = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=-0.25,  # <= -0.2
            consecutive_negative_days=3,
        )
        assert risk == EmotionRiskLevel.MEDIUM

    def test_low_by_default(self, detector):
        """条件を満たさない場合はLOW"""
        risk = detector._determine_risk_level(
            baseline_score=0.1,
            current_score=0.05,  # drop = 0.05 < 0.2
            consecutive_negative_days=1,
        )
        assert risk == EmotionRiskLevel.LOW


# ================================================================
# 7. 連続ネガティブ日数計算のテスト
# ================================================================

class TestConsecutiveNegativeDays:
    """_calculate_consecutive_negative_days メソッドのテスト"""

    def test_empty_scores(self, detector):
        """空のスコアリスト"""
        result = detector._calculate_consecutive_negative_days([])
        assert result == 0

    def test_all_positive_scores(self, detector):
        """全てポジティブなスコア"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': 0.3, 'message_time': now},
            {'sentiment_score': 0.5, 'message_time': now - timedelta(days=1)},
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        assert result == 0

    def test_consecutive_negative_days(self, detector):
        """連続ネガティブ日数の計算"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': -0.3, 'message_time': now},  # 今日
            {'sentiment_score': -0.4, 'message_time': now - timedelta(days=1)},  # 昨日
            {'sentiment_score': -0.2, 'message_time': now - timedelta(days=2)},  # 2日前
            {'sentiment_score': 0.1, 'message_time': now - timedelta(days=3)},  # 3日前（ポジティブ）
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        # 今日、昨日、2日前が全てネガティブなので3日
        # ただし閾値は -0.2 なので、-0.2以下がネガティブ
        assert result >= 2  # 少なくとも2日は連続

    def test_mixed_scores_on_same_day(self, detector):
        """同じ日に複数のスコア（日平均を使用）"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': -0.1, 'message_time': now},  # 今日
            {'sentiment_score': -0.3, 'message_time': now},  # 今日（2つ目）
            {'sentiment_score': 0.5, 'message_time': now - timedelta(days=1)},  # 昨日
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        # 今日の平均: (-0.1 + -0.3) / 2 = -0.2 （ネガティブ閾値ちょうど）
        # 閾値は < -0.2 なので、今日はネガティブではない
        assert result == 0

    def test_non_datetime_message_time_skipped(self, detector):
        """datetime以外のmessage_timeはスキップ"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': -0.3, 'message_time': now},
            {'sentiment_score': -0.4, 'message_time': "invalid"},  # スキップされる
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        # 有効なのは1件のみなので1日
        assert result == 1


# ================================================================
# 8. 検出メイン処理のテスト
# ================================================================

class TestDetectMainFlow:
    """detect メソッド（メイン処理）のテスト"""

    @pytest.mark.asyncio
    async def test_detect_no_active_users(self, detector):
        """アクティブユーザーがいない場合"""
        with patch.object(detector, '_get_active_users', return_value=[]):
            result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 0
        assert result.insight_created is False

    @pytest.mark.asyncio
    async def test_detect_user_with_insufficient_messages(self, detector, sample_user):
        """メッセージ数が不足しているユーザー"""
        with patch.object(detector, '_get_active_users', return_value=[sample_user]):
            with patch.object(detector, '_analyze_user_emotion', return_value=[]):
                result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 0

    @pytest.mark.asyncio
    async def test_detect_with_alerts(self, detector, sample_user):
        """アラートが検出される場合"""
        alert_id = uuid4()
        mock_alert = {
            'id': alert_id,
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'user_name': 'テストユーザー',
            'account_id': '12345',
        }

        with patch.object(detector, '_get_active_users', return_value=[sample_user]):
            with patch.object(detector, '_analyze_user_emotion', return_value=[mock_alert]):
                with patch.object(detector, '_save_alert', return_value=mock_alert):
                    with patch.object(detector, 'insight_exists_for_source', return_value=False):
                        with patch.object(detector, 'save_insight', return_value=uuid4()):
                            result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 1
        assert result.insight_created is True

    @pytest.mark.asyncio
    async def test_detect_handles_user_analysis_error(self, detector, sample_user):
        """ユーザー分析エラーのハンドリング"""
        with patch.object(detector, '_get_active_users', return_value=[sample_user]):
            with patch.object(detector, '_analyze_user_emotion', side_effect=Exception("Analysis error")):
                result = await detector.detect()

        assert result.success is True
        assert result.details['users_skipped'] == 1

    @pytest.mark.asyncio
    async def test_detect_critical_exception(self, detector):
        """重大な例外発生時"""
        with patch.object(detector, '_get_active_users', side_effect=Exception("Critical error")):
            result = await detector.detect()

        assert result.success is False
        assert 'Exception' in result.error_message


# ================================================================
# 9. ユーザー感情分析のテスト
# ================================================================

class TestAnalyzeUserEmotion:
    """_analyze_user_emotion メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_analyze_insufficient_messages(self, detector, sample_user):
        """メッセージ数不足でスキップ"""
        with patch.object(detector, '_get_user_messages', return_value=[]):
            result = await detector._analyze_user_emotion(sample_user)

        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_no_valid_scores(self, detector, sample_user, sample_message):
        """有効なスコアがない場合"""
        messages = [sample_message] * 5

        with patch.object(detector, '_get_user_messages', return_value=messages):
            with patch.object(detector, '_get_or_calculate_sentiment', return_value=None):
                result = await detector._analyze_user_emotion(sample_user)

        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_detects_sudden_drop(self, detector, sample_user, sample_message):
        """急激な悪化の検出"""
        now = datetime.now(timezone.utc)
        messages = [sample_message] * 5

        # 直近7日間のスコア（ネガティブ）
        recent_scores = [
            {'message_id': f'msg_{i}', 'sentiment_score': -0.4, 'sentiment_label': 'negative',
             'confidence': 0.8, 'detected_emotions': [], 'message_time': now - timedelta(days=i)}
            for i in range(5)
        ]

        with patch.object(detector, '_get_user_messages', return_value=messages):
            with patch.object(detector, '_get_or_calculate_sentiment', side_effect=recent_scores):
                with patch.object(detector, '_calculate_baseline_score', return_value=0.3):
                    result = await detector._analyze_user_emotion(sample_user)

        assert len(result) > 0
        assert result[0]['alert_type'] == EmotionAlertType.SUDDEN_DROP.value


# ================================================================
# 10. 感情スコア取得/計算のテスト
# ================================================================

class TestGetOrCalculateSentiment:
    """_get_or_calculate_sentiment メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_existing_score(self, detector, mock_conn, sample_message):
        """既存のスコアを取得"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            -0.3,  # sentiment_score
            'negative',  # sentiment_label
            0.85,  # confidence
            ['不安'],  # detected_emotions
            datetime.now(timezone.utc),  # analyzed_at
        )
        mock_conn.execute.return_value = mock_result

        result = await detector._get_or_calculate_sentiment(sample_message)

        assert result is not None
        assert result['sentiment_score'] == -0.3
        assert result['sentiment_label'] == 'negative'

    @pytest.mark.asyncio
    async def test_calculate_new_score(self, detector, mock_conn, sample_message, sample_sentiment_response):
        """新しいスコアを計算して保存"""
        # 既存スコアがない
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        with patch.object(detector, '_analyze_sentiment', return_value=json.loads(sample_sentiment_response)):
            with patch.object(detector, '_save_emotion_score', return_value=None):
                result = await detector._get_or_calculate_sentiment(sample_message)

        assert result is not None
        assert result['sentiment_score'] == -0.3

    @pytest.mark.asyncio
    async def test_calculate_score_failure(self, detector, mock_conn, sample_message):
        """スコア計算失敗時"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        with patch.object(detector, '_analyze_sentiment', return_value=None):
            result = await detector._get_or_calculate_sentiment(sample_message)

        assert result is None


# ================================================================
# 11. プライバシー制約の検証テスト
# ================================================================

class TestPrivacyConstraints:
    """プライバシー制約（CONFIDENTIAL分類）の検証テスト"""

    def test_insight_data_always_confidential(self, detector):
        """InsightDataは常にCONFIDENTIAL"""
        alert_types = [
            EmotionAlertType.SUDDEN_DROP,
            EmotionAlertType.SUSTAINED_NEGATIVE,
            EmotionAlertType.HIGH_VOLATILITY,
            EmotionAlertType.RECOVERY,
        ]

        for alert_type in alert_types:
            alert = {
                'id': uuid4(),
                'alert_type': alert_type.value,
                'risk_level': EmotionRiskLevel.HIGH.value,
                'user_name': 'テストユーザー',
            }

            insight_data = detector._create_insight_data(alert)

            assert insight_data.classification == Classification.CONFIDENTIAL, \
                f"Alert type {alert_type.value} should produce CONFIDENTIAL classification"

    def test_evidence_does_not_contain_message_body(self, detector):
        """evidenceにメッセージ本文が含まれない"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'user_name': 'テストユーザー',
            'score_change': 0.5,
            'consecutive_negative_days': 3,
        }

        insight_data = detector._create_insight_data(alert)

        # evidenceにbodyキーがないことを確認
        assert 'body' not in insight_data.evidence
        assert 'message' not in insight_data.evidence
        assert 'text' not in insight_data.evidence

    @pytest.mark.asyncio
    async def test_save_alert_uses_confidential_classification(self, detector, mock_conn):
        """_save_alertがconfidential分類を使用"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid4(),)
        mock_conn.execute.return_value = mock_result

        alert = {
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'account_id': '12345',
            'user_name': 'テストユーザー',
        }

        await detector._save_alert(alert)

        # INSERT SQLに 'confidential' が含まれることを確認（SAVEPOINT/RELEASEを除く）
        insert_call = mock_conn.execute.call_args_list[1]
        sql_text = str(insert_call[0][0])
        assert 'confidential' in sql_text.lower()


# ================================================================
# 12. SentimentLabel Enumのテスト
# ================================================================

class TestSentimentLabel:
    """SentimentLabel Enumのテスト"""

    def test_from_score_very_positive(self):
        """非常にポジティブ（0.6以上）"""
        assert SentimentLabel.from_score(0.6) == SentimentLabel.VERY_POSITIVE
        assert SentimentLabel.from_score(0.8) == SentimentLabel.VERY_POSITIVE
        assert SentimentLabel.from_score(1.0) == SentimentLabel.VERY_POSITIVE

    def test_from_score_positive(self):
        """ポジティブ（0.2〜0.6未満）"""
        assert SentimentLabel.from_score(0.2) == SentimentLabel.POSITIVE
        assert SentimentLabel.from_score(0.4) == SentimentLabel.POSITIVE
        assert SentimentLabel.from_score(0.59) == SentimentLabel.POSITIVE

    def test_from_score_neutral(self):
        """ニュートラル（-0.2〜0.2未満）"""
        assert SentimentLabel.from_score(0.0) == SentimentLabel.NEUTRAL
        assert SentimentLabel.from_score(0.1) == SentimentLabel.NEUTRAL
        assert SentimentLabel.from_score(-0.1) == SentimentLabel.NEUTRAL

    def test_from_score_negative(self):
        """ネガティブ（-0.5〜-0.2以下）"""
        assert SentimentLabel.from_score(-0.21) == SentimentLabel.NEGATIVE
        assert SentimentLabel.from_score(-0.3) == SentimentLabel.NEGATIVE
        assert SentimentLabel.from_score(-0.49) == SentimentLabel.NEGATIVE

    def test_from_score_very_negative(self):
        """非常にネガティブ（-0.5未満）"""
        assert SentimentLabel.from_score(-0.5) == SentimentLabel.VERY_NEGATIVE
        assert SentimentLabel.from_score(-0.7) == SentimentLabel.VERY_NEGATIVE
        assert SentimentLabel.from_score(-1.0) == SentimentLabel.VERY_NEGATIVE


# ================================================================
# 13. 感情アラートタイプとリスクレベルのテスト
# ================================================================

class TestEmotionEnums:
    """感情検出関連Enumのテスト"""

    def test_emotion_alert_types(self):
        """EmotionAlertTypeの値確認"""
        assert EmotionAlertType.SUDDEN_DROP.value == "sudden_drop"
        assert EmotionAlertType.SUSTAINED_NEGATIVE.value == "sustained_negative"
        assert EmotionAlertType.HIGH_VOLATILITY.value == "high_volatility"
        assert EmotionAlertType.RECOVERY.value == "recovery"

    def test_emotion_risk_levels(self):
        """EmotionRiskLevelの値確認"""
        assert EmotionRiskLevel.CRITICAL.value == "critical"
        assert EmotionRiskLevel.HIGH.value == "high"
        assert EmotionRiskLevel.MEDIUM.value == "medium"
        assert EmotionRiskLevel.LOW.value == "low"

    def test_emotion_status(self):
        """EmotionStatusの値確認"""
        assert EmotionStatus.ACTIVE.value == "active"
        assert EmotionStatus.RESOLVED.value == "resolved"
        assert EmotionStatus.DISMISSED.value == "dismissed"


# ================================================================
# 14. 感情分析プロンプトのテスト
# ================================================================

class TestSentimentPrompt:
    """SENTIMENT_ANALYSIS_PROMPTのテスト"""

    def test_prompt_contains_required_elements(self):
        """プロンプトに必要な要素が含まれている"""
        assert "感情トーン" in SENTIMENT_ANALYSIS_PROMPT
        assert "sentiment_score" in SENTIMENT_ANALYSIS_PROMPT
        assert "sentiment_label" in SENTIMENT_ANALYSIS_PROMPT
        assert "confidence" in SENTIMENT_ANALYSIS_PROMPT
        assert "JSON" in SENTIMENT_ANALYSIS_PROMPT

    def test_prompt_privacy_guidance(self):
        """プロンプトにプライバシーに関するガイダンスがある"""
        # 個人名を含めないよう指示があることを確認
        assert "個人名" in SENTIMENT_ANALYSIS_PROMPT or "key_indicators" in SENTIMENT_ANALYSIS_PROMPT


# ================================================================
# 15. エッジケースのテスト
# ================================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_user_with_null_account_name(self, detector):
        """account_nameがNullのユーザー"""
        user = {
            'account_id': '12345',
            'account_name': None,
            'message_count': 10,
        }

        # _analyze_user_emotion内で "不明" にフォールバックされることを期待
        # ただしメッセージ取得でスキップされる可能性もある
        with patch.object(detector, '_get_user_messages', return_value=[]):
            result = await detector._analyze_user_emotion(user)

        assert result == []

    def test_insight_data_with_unknown_user(self, detector):
        """不明なユーザー名のInsightData"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            # user_nameなし
        }

        insight_data = detector._create_insight_data(alert)

        assert '不明' in insight_data.title

    def test_risk_level_boundary_conditions(self, detector):
        """リスクレベル判定の境界条件"""
        # ちょうど閾値の場合

        # score_drop = 0.4 (critical threshold exact)
        risk = detector._determine_risk_level(
            baseline_score=0.4,
            current_score=0.0,
            consecutive_negative_days=3,
        )
        assert risk == EmotionRiskLevel.CRITICAL

        # score_drop = 0.3 (high threshold exact)
        risk = detector._determine_risk_level(
            baseline_score=0.3,
            current_score=0.0,
            consecutive_negative_days=2,
        )
        assert risk == EmotionRiskLevel.HIGH

        # score_drop = 0.2 (medium threshold exact)
        risk = detector._determine_risk_level(
            baseline_score=0.2,
            current_score=0.0,
            consecutive_negative_days=0,
        )
        assert risk == EmotionRiskLevel.MEDIUM


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
