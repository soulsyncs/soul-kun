# tests/test_critical_functions.py
"""
重要機能の統合テスト

デプロイ前に必ず実行される。
これらのテストが失敗したらデプロイが中止される。

v10.54.3: 初版作成（品質チェック強化）
"""

import pytest
import sys
import os

# chatwork-webhookディレクトリをパスに追加（handler_wrappers等のため）
CHATWORK_WEBHOOK_DIR = os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook')
if CHATWORK_WEBHOOK_DIR not in sys.path:
    sys.path.insert(0, CHATWORK_WEBHOOK_DIR)

# lib/brain/ のテスト用（共通モジュール）
LIB_DIR = os.path.join(os.path.dirname(__file__), '..')
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)


class TestCriticalImports:
    """重要なモジュールがインポートできることを確認"""

    def test_brain_models_imports(self):
        """lib/brain/models.pyが正常にインポートできること"""
        try:
            from lib.brain.models import BrainContext, GoalInfo, TaskInfo, PersonInfo, DecisionResult, HandlerResult

            assert BrainContext is not None
            assert GoalInfo is not None
            assert TaskInfo is not None
            assert PersonInfo is not None
            assert DecisionResult is not None
            assert HandlerResult is not None
        except NameError as e:
            pytest.fail(f"未定義のクラスが参照されています: {e}")
        except ImportError as e:
            pytest.fail(f"インポートエラー: {e}")

    def test_brain_state_manager_imports(self):
        """lib/brain/state_manager.pyが正常にインポートできること"""
        try:
            from lib.brain.state_manager import BrainStateManager, SafeJSONEncoder, _safe_json_dumps

            assert BrainStateManager is not None
            assert SafeJSONEncoder is not None
            assert callable(_safe_json_dumps)
        except NameError as e:
            pytest.fail(f"未定義のクラス/関数が参照されています: {e}")
        except ImportError as e:
            pytest.fail(f"インポートエラー: {e}")


class TestBrainContextSerialization:
    """BrainContextのシリアライズテスト"""

    def test_to_dict_with_objects(self):
        """オブジェクトを含むBrainContextがto_dict()できること"""
        from lib.brain.models import BrainContext, GoalInfo, TaskInfo, PersonInfo

        ctx = BrainContext()
        ctx.person_info = [PersonInfo(name="田中")]
        ctx.recent_tasks = [TaskInfo(task_id="1", body="テスト")]
        ctx.active_goals = [GoalInfo(goal_id="1", title="目標")]

        # to_dict()がエラーなく動作すること
        result = ctx.to_dict()

        assert isinstance(result, dict)
        assert 'person_info' in result
        assert 'recent_tasks' in result
        assert 'active_goals' in result

    def test_to_dict_with_dicts(self):
        """辞書を含むBrainContextがto_dict()できること（後方互換）"""
        from lib.brain.models import BrainContext

        ctx = BrainContext()
        ctx.person_info = [{"name": "田中"}]
        ctx.recent_tasks = [{"task_id": "1", "body": "テスト"}]
        ctx.active_goals = [{"goal_id": "1", "title": "目標"}]

        # to_dict()がエラーなく動作すること
        result = ctx.to_dict()

        assert isinstance(result, dict)


class TestSafeJsonEncoder:
    """SafeJSONEncoderのテスト"""

    def test_confidence_scores_serialization(self):
        """ConfidenceScoresがシリアライズできること"""
        import json
        from lib.brain.state_manager import SafeJSONEncoder
        from lib.brain.llm_brain import ConfidenceScores

        cs = ConfidenceScores(overall=0.85, intent=0.9, parameters=0.8)
        data = {'confidence': cs, 'value': 123}

        # エラーなくシリアライズできること
        result = json.dumps(data, cls=SafeJSONEncoder)

        assert 'confidence' in result
        assert '0.85' in result

    def test_datetime_serialization(self):
        """datetimeがシリアライズできること"""
        import json
        from datetime import datetime
        from lib.brain.state_manager import SafeJSONEncoder

        data = {'timestamp': datetime(2026, 2, 1, 12, 0, 0)}

        # エラーなくシリアライズできること
        result = json.dumps(data, cls=SafeJSONEncoder)

        assert '2026-02-01' in result

    def test_nested_objects_serialization(self):
        """ネストしたオブジェクトがシリアライズできること"""
        import json
        from lib.brain.state_manager import _safe_json_dumps
        from lib.brain.models import GoalInfo

        goal = GoalInfo(goal_id="1", title="目標")
        data = {'goals': [goal], 'count': 1}

        # エラーなくシリアライズできること
        result = _safe_json_dumps(data)

        assert 'goals' in result
        assert '目標' in result


class TestNoUndefinedReferences:
    """未定義の参照がないことを確認するテスト"""

    def test_models_no_undefined(self):
        """models.pyに未定義の参照がないこと"""
        import lib.brain.models
        assert True

    def test_state_manager_no_undefined(self):
        """state_manager.pyに未定義の参照がないこと"""
        import lib.brain.state_manager
        assert True

    def test_context_builder_no_undefined(self):
        """context_builder.pyに未定義の参照がないこと"""
        import lib.brain.context_builder
        assert True

    def test_llm_brain_no_undefined(self):
        """llm_brain.pyに未定義の参照がないこと"""
        import lib.brain.llm_brain
        assert True
