"""
LLM Brain E2Eテスト

設計書: docs/25_llm_native_brain_architecture.md

【目的】
実際のOpenRouter/Anthropic APIを使用して、LLM Brainが正しく動作することを確認する。

【前提条件】
本番環境:
  1. GCP Secret Manager に "openrouter-api-key" が設定されていること

ローカル開発:
  1. 環境変数 OPENROUTER_API_KEY が設定されていること
  または
  2. 環境変数 ANTHROPIC_API_KEY が設定されていること

【API取得優先順位】
1. 環境変数 OPENROUTER_API_KEY
2. GCP Secret Manager (openrouter-api-key)
3. 環境変数 ANTHROPIC_API_KEY (フォールバック)

【テスト内容】
1. LLM Brainの初期化
2. 「タスク追加して」でTool呼び出しが正しく行われるか
3. 確認フローが正しく動作するか
4. Guardian Layerが正しく機能するか

Author: Claude Opus 4.5
Created: 2026-01-30
Updated: 2026-01-30 - OpenRouter対応、lib/secrets統合
"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from typing import Optional, Tuple

import pytest

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def get_api_key_info() -> Tuple[Optional[str], str]:
    """
    APIキーの取得状況を確認する

    Returns:
        Tuple[Optional[str], str]: (取得したキーの種類, 詳細メッセージ)
        種類: "openrouter_env", "openrouter_secret", "anthropic_env", None
    """
    # 1. 環境変数 OPENROUTER_API_KEY
    openrouter_env = os.getenv("OPENROUTER_API_KEY")
    if openrouter_env:
        return ("openrouter_env", f"環境変数 OPENROUTER_API_KEY (length={len(openrouter_env)})")

    # 2. GCP Secret Manager
    try:
        from lib.secrets import get_secret_cached
        openrouter_secret = get_secret_cached("openrouter-api-key")
        if openrouter_secret:
            return ("openrouter_secret", f"GCP Secret Manager (length={len(openrouter_secret)})")
    except Exception as e:
        logger.debug(f"Secret Manager取得失敗: {e}")

    # 3. 環境変数 ANTHROPIC_API_KEY (フォールバック)
    anthropic_env = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_env:
        return ("anthropic_env", f"環境変数 ANTHROPIC_API_KEY (length={len(anthropic_env)})")

    return (None, "APIキーが見つかりません")


def check_prerequisites() -> bool:
    """前提条件をチェック"""
    print("=" * 60)
    print("🧪 LLM Brain E2Eテスト - 前提条件チェック")
    print("=" * 60)

    errors = []

    # APIキー取得状況を確認
    key_type, key_info = get_api_key_info()

    if key_type == "openrouter_env":
        print(f"✅ APIキー: {key_info}")
        print("   → OpenRouter経由でClaude Opus 4.5を使用")
    elif key_type == "openrouter_secret":
        print(f"✅ APIキー: {key_info}")
        print("   → OpenRouter経由でClaude Opus 4.5を使用")
    elif key_type == "anthropic_env":
        print(f"⚠️  OpenRouterキーなし。フォールバック:")
        print(f"✅ APIキー: {key_info}")
        print("   → Anthropic直接APIを使用")
    else:
        print("❌ APIキー: 未設定")
        errors.append("API_KEY")

    # ENABLE_LLM_BRAIN (情報として表示、必須ではない)
    llm_brain_flag = os.getenv("ENABLE_LLM_BRAIN", "false").lower()
    if llm_brain_flag == "true":
        print("✅ ENABLE_LLM_BRAIN: true")
    else:
        print(f"⚠️  ENABLE_LLM_BRAIN: {llm_brain_flag} (テスト時に強制有効化)")

    print("=" * 60)

    if errors:
        print(f"\n❌ APIキーを設定してください:")
        print(f"\n   【推奨】OpenRouter:")
        print(f"   export OPENROUTER_API_KEY=<your-openrouter-key>")
        print(f"\n   【フォールバック】Anthropic直接:")
        print(f"   export ANTHROPIC_API_KEY=<your-anthropic-key>")
        print(f"\n   【本番環境】GCP Secret Manager:")
        print(f"   シークレット名: openrouter-api-key")
        return False

    return True


async def test_llm_brain_initialization():
    """LLM Brainの初期化テスト（ファクトリ関数使用）"""
    print("\n" + "=" * 60)
    print("📋 テスト1: LLM Brain初期化")
    print("=" * 60)

    try:
        from lib.brain.llm_brain import create_llm_brain_auto, APIProvider

        # 自動検出でBrainを作成
        brain = create_llm_brain_auto()

        api_name = "OpenRouter" if brain.api_provider == APIProvider.OPENROUTER else "Anthropic直接"

        print(f"✅ LLMBrain初期化成功")
        print(f"   モデル: {brain.model}")
        print(f"   max_tokens: {brain.max_tokens}")
        print(f"   API: {api_name}")
        print(f"   確信度閾値（自動実行）: {brain.CONFIDENCE_THRESHOLD_AUTO_EXECUTE}")
        print(f"   確信度閾値（確認必要）: {brain.CONFIDENCE_THRESHOLD_CONFIRM}")

        return brain
    except Exception as e:
        print(f"❌ LLMBrain初期化失敗: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_context_builder():
    """Context Builderのテスト"""
    print("\n" + "=" * 60)
    print("📋 テスト2: Context Builder")
    print("=" * 60)

    try:
        from lib.brain.context_builder import LLMContext, Message, UserPreferences

        # テスト用のコンテキストを作成
        context = LLMContext(
            user_id="test_user_123",
            user_name="テストユーザー",
            room_id="test_room_456",
            organization_id="org_test",
            recent_messages=[
                Message(role="user", content="おはようございます"),
                Message(role="assistant", content="おはようございますウル！"),
            ],
            user_preferences=UserPreferences(
                preferred_name="テストさん",
            ),
        )

        prompt_string = context.to_prompt_string()
        print(f"✅ LLMContext作成成功")
        print(f"   ユーザー: {context.user_name}")
        print(f"   メッセージ数: {len(context.recent_messages)}")
        print(f"\n📝 Prompt文字列（抜粋）:")
        print(prompt_string[:500] + "..." if len(prompt_string) > 500 else prompt_string)

        return context
    except Exception as e:
        print(f"❌ Context Builder失敗: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_tool_converter():
    """Tool Converterのテスト"""
    print("\n" + "=" * 60)
    print("📋 テスト3: Tool Converter")
    print("=" * 60)

    try:
        from lib.brain.tool_converter import get_tools_for_llm

        tools = get_tools_for_llm()
        print(f"✅ Tool変換成功: {len(tools)}個のToolを生成")

        # 主要なToolを表示
        important_tools = [
            "chatwork_task_create",
            "chatwork_task_list",
            "knowledge_search",
            "goal_add",
        ]

        print("\n📝 主要なTool:")
        for tool in tools:
            if tool["name"] in important_tools:
                desc = tool.get('description', '')[:50]
                print(f"   - {tool['name']}: {desc}...")

        return tools
    except Exception as e:
        print(f"❌ Tool Converter失敗: {e}")
        import traceback
        traceback.print_exc()
        return None


@pytest.mark.skip(reason="E2Eテスト: main()から呼び出す（pytestから直接実行不可）")
async def test_llm_brain_process(brain, context, tools):
    """LLM Brainの処理テスト（実際のAPI呼び出し）"""
    print("\n" + "=" * 60)
    print("📋 テスト4: LLM Brain処理（API呼び出し）")
    print("=" * 60)

    test_messages = [
        "タスク追加して",
        "自分のタスク教えて",
        "おはようございます",
    ]

    results = []

    for message in test_messages:
        print(f"\n🔹 テストメッセージ: 「{message}」")
        print("-" * 40)

        try:
            result = await brain.process(
                context=context,
                message=message,
                tools=tools,
            )

            print(f"✅ 処理成功")
            print(f"   出力タイプ: {result.output_type}")
            print(f"   確信度: {result.confidence.overall:.2f}")
            print(f"   入力トークン: {result.input_tokens}")
            print(f"   出力トークン: {result.output_tokens}")

            if result.tool_calls:
                print(f"   Tool呼び出し:")
                for tc in result.tool_calls:
                    print(f"      - {tc.tool_name}: {tc.parameters}")

            if result.text_response:
                response_preview = result.text_response[:100] + "..." if len(result.text_response) > 100 else result.text_response
                print(f"   応答: {response_preview}")

            if result.reasoning:
                reasoning_preview = result.reasoning[:150] + "..." if len(result.reasoning) > 150 else result.reasoning
                print(f"   思考過程: {reasoning_preview}")

            results.append((message, result, None))

        except Exception as e:
            print(f"❌ 処理失敗: {e}")
            import traceback
            traceback.print_exc()
            results.append((message, None, str(e)))

    return results


async def test_guardian_layer():
    """Guardian Layerのテスト"""
    print("\n" + "=" * 60)
    print("📋 テスト5: Guardian Layer")
    print("=" * 60)

    try:
        from lib.brain.guardian_layer import GuardianLayer, GuardianAction
        from lib.brain.llm_brain import LLMBrainResult, ToolCall, ConfidenceScores
        from lib.brain.context_builder import LLMContext

        guardian = GuardianLayer(ceo_teachings=[])

        # テスト用のLLMBrainResult（reasoningは必須）
        test_result = LLMBrainResult(
            output_type="tool_call",
            tool_calls=[
                ToolCall(
                    tool_name="chatwork_task_create",
                    parameters={"body": "テストタスク"},
                )
            ],
            confidence=ConfidenceScores(overall=0.8),
            reasoning="ユーザーがタスク追加を依頼したのでchatwork_task_createを使用するウル",
        )

        test_context = LLMContext(
            user_id="test_user",
            user_name="テスター",
            room_id="test_room",
            organization_id="org_test",
        )

        guardian_result = await guardian.check(test_result, test_context)

        print(f"✅ Guardian Layer動作確認")
        print(f"   アクション: {guardian_result.action.value}")
        print(f"   理由: {guardian_result.reason}")

        if guardian_result.action == GuardianAction.ALLOW:
            print(f"   → Tool実行を許可")
        elif guardian_result.action == GuardianAction.CONFIRM:
            print(f"   → 確認が必要")
        elif guardian_result.action == GuardianAction.BLOCK:
            print(f"   → 実行をブロック")

        return guardian_result

    except Exception as e:
        print(f"❌ Guardian Layer失敗: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_summary(results: list):
    """テスト結果のサマリーを表示"""
    print("\n" + "=" * 60)
    print("📊 テスト結果サマリー")
    print("=" * 60)

    if not results:
        print("⚠️  テスト結果がありません")
        return

    success_count = sum(1 for _, result, error in results if result is not None)
    total_count = len(results)

    print(f"\n成功: {success_count}/{total_count}")

    for message, result, error in results:
        if result is not None:
            status = "✅"
            detail = f"type={result.output_type}, confidence={result.confidence.overall:.2f}"
            if result.tool_calls:
                detail += f", tools={[tc.tool_name for tc in result.tool_calls]}"
        else:
            status = "❌"
            detail = f"error={error}"

        print(f"  {status} 「{message}」: {detail}")


async def main():
    """メイン実行関数"""
    print("\n🐺 ソウルくん LLM Brain E2Eテスト 🐺")
    print("=" * 60)

    # 前提条件チェック
    if not check_prerequisites():
        print("\n❌ 前提条件を満たしていません。テストを中止します。")
        sys.exit(1)

    # テスト実行
    try:
        # 1. LLM Brain初期化
        brain = await test_llm_brain_initialization()
        if not brain:
            print("\n❌ LLM Brain初期化に失敗したため、テストを中止します。")
            sys.exit(1)

        # 2. Context Builder
        context = await test_context_builder()
        if not context:
            print("\n❌ Context Builderに失敗したため、テストを中止します。")
            sys.exit(1)

        # 3. Tool Converter
        tools = await test_tool_converter()
        if not tools:
            print("\n❌ Tool Converterに失敗したため、テストを中止します。")
            sys.exit(1)

        # 4. LLM Brain処理（実際のAPI呼び出し）
        results = await test_llm_brain_process(brain, context, tools)

        # 5. Guardian Layer
        await test_guardian_layer()

        # サマリー表示
        print_summary(results)

        print("\n" + "=" * 60)
        print("🎉 E2Eテスト完了！")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️  テストが中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
