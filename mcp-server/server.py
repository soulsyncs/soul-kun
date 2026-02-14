#!/usr/bin/env python3
"""
ソウルくん MCP Server — Model Context Protocol でツールを公開

soul-kunの既存ツール（SYSTEM_CAPABILITIES）をMCPプロトコルで外部公開する。
Claude Desktop、Cursor、その他MCP対応クライアントからソウルくんの全機能を利用可能。

【設計方針】
- 既存の SYSTEM_CAPABILITIES / HANDLERS をそのまま活用（二重定義しない）
- BrainIntegrationを通して実行（Brain bypass禁止: CLAUDE.md 鉄則1）
- organization_id フィルタ必須（鉄則#1）
- PII はレスポンスに含めない（鉄則#8）

【起動方法】
  # stdio モード（Claude Desktop等）
  python3 mcp-server/server.py

  # SSE モード（HTTP経由）
  python3 mcp-server/server.py --transport sse --port 8080

Author: Claude Opus 4.6
Created: 2026-02-14
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# lib/ を import path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chatwork-webhook"))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    ResourceTemplate,
    TextContent,
    Tool,
    Prompt,
    PromptArgument,
    PromptMessage,
    GetPromptResult,
)

from lib.config import DB_NAME, DB_USER, ORGANIZATION_ID
from lib.db import get_db_pool

logger = logging.getLogger(__name__)

# =============================================================================
# MCP Server インスタンス
# =============================================================================

app = Server("soulkun-mcp")

# グローバル状態
_db_pool = None
_handlers = None
_capabilities = None


async def _get_db_pool():
    """DB接続プールを遅延初期化"""
    global _db_pool
    if _db_pool is None:
        _db_pool = get_db_pool()
    return _db_pool


def _load_capabilities() -> Dict[str, Dict[str, Any]]:
    """SYSTEM_CAPABILITIESをロード"""
    global _capabilities
    if _capabilities is None:
        from handlers.registry import SYSTEM_CAPABILITIES
        _capabilities = SYSTEM_CAPABILITIES
    return _capabilities


def _load_handlers() -> Dict[str, Any]:
    """HANDLERSをロード"""
    global _handlers
    if _handlers is None:
        from handlers.registry import build_handlers
        _handlers = build_handlers()
    return _handlers


# =============================================================================
# Tools — SYSTEM_CAPABILITIESから自動生成
# =============================================================================


def _capability_to_mcp_tool(key: str, cap: Dict[str, Any]) -> Tool:
    """SYSTEM_CAPABILITYエントリをMCP Tool形式に変換"""
    # パラメータスキーマをJSON Schema形式に変換
    properties = {}
    required = []

    for param_name, param_def in cap.get("params_schema", {}).items():
        prop = {
            "type": _map_type(param_def.get("type", "string")),
            "description": param_def.get("description", ""),
        }
        properties[param_name] = prop
        if param_def.get("required", False):
            required.append(param_name)

    input_schema = {
        "type": "object",
        "properties": properties,
    }
    if required:
        input_schema["required"] = required

    # トリガー例を説明に追加
    description = cap.get("description", "")
    examples = cap.get("trigger_examples", [])
    if examples:
        description += "\n\n使用例:\n" + "\n".join(f"- {ex}" for ex in examples[:3])

    return Tool(
        name=key,
        description=description,
        inputSchema=input_schema,
    )


def _map_type(cap_type: str) -> str:
    """SYSTEM_CAPABILITIESの型をJSON Schema型にマッピング"""
    mapping = {
        "string": "string",
        "str": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "date": "string",
        "time": "string",
        "list": "array",
        "array": "array",
    }
    return mapping.get(cap_type, "string")


@app.list_tools()
async def list_tools() -> List[Tool]:
    """利用可能なツール一覧を返す"""
    capabilities = _load_capabilities()
    tools = []
    for key, cap in capabilities.items():
        if cap.get("enabled", True):
            tools.append(_capability_to_mcp_tool(key, cap))
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """
    ツールを実行する

    Brain経由で実行（bypass禁止）。
    organization_idフィルタは Brain が自動付与。
    """
    capabilities = _load_capabilities()

    if name not in capabilities:
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False),
        )]

    cap = capabilities[name]
    if not cap.get("enabled", True):
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Tool is disabled: {name}"}, ensure_ascii=False),
        )]

    try:
        pool = await _get_db_pool()
        handlers = _load_handlers()

        # BrainIntegration経由で実行（鉄則: Brainをバイパスしない）
        from lib.brain.integration import BrainIntegration
        from lib.brain.llm import get_ai_response_raw

        integration = BrainIntegration(
            pool=pool,
            org_id=ORGANIZATION_ID,
            handlers=handlers,
            capabilities=capabilities,
            get_ai_response_func=get_ai_response_raw,
        )

        # ツール実行メッセージを構築
        tool_message = f"[MCP] ツール実行: {name}"
        if arguments:
            tool_message += f"\nパラメータ: {json.dumps(arguments, ensure_ascii=False)}"

        result = await integration.process_message(
            message=tool_message,
            room_id="mcp-client",
            account_id="mcp-user",
            sender_name="MCP Client",
        )

        return [TextContent(
            type="text",
            text=result.to_chatwork_message() if hasattr(result, 'to_chatwork_message') else str(result),
        )]

    except Exception as e:
        logger.exception(f"Tool execution failed: {name}")
        return [TextContent(
            type="text",
            text=json.dumps(
                {"error": str(e), "tool": name},
                ensure_ascii=False,
            ),
        )]


# =============================================================================
# Resources — 組織データへの読み取りアクセス
# =============================================================================


@app.list_resources()
async def list_resources() -> List[Resource]:
    """利用可能なリソース一覧"""
    return [
        Resource(
            uri="soulkun://tasks/active",
            name="アクティブタスク一覧",
            description="現在進行中のChatWorkタスク",
            mimeType="application/json",
        ),
        Resource(
            uri="soulkun://goals/active",
            name="アクティブ目標一覧",
            description="現在の目標と進捗状況",
            mimeType="application/json",
        ),
        Resource(
            uri="soulkun://persons",
            name="メンバー一覧",
            description="組織のメンバー情報（PII除外）",
            mimeType="application/json",
        ),
        Resource(
            uri="soulkun://departments",
            name="部署一覧",
            description="組織の部署構造",
            mimeType="application/json",
        ),
    ]


@app.list_resource_templates()
async def list_resource_templates() -> List[ResourceTemplate]:
    """リソーステンプレート一覧"""
    return [
        ResourceTemplate(
            uriTemplate="soulkun://persons/{person_id}",
            name="メンバー詳細",
            description="指定メンバーの詳細情報（PII除外）",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="soulkun://tasks/{task_id}",
            name="タスク詳細",
            description="指定タスクの詳細",
            mimeType="application/json",
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """リソースを読み取る（organization_idフィルタ付き）"""
    pool = await _get_db_pool()

    try:
        conn = pool.connect()
        try:
            # organization_id フィルタ設定（鉄則#1）
            conn.execute(
                "SELECT set_config('app.current_organization_id', %s, true)",
                [ORGANIZATION_ID],
            )

            if uri == "soulkun://tasks/active":
                result = conn.execute(
                    """SELECT id, title, status, assigned_to, due_date
                       FROM tasks
                       WHERE organization_id = %s AND status != 'completed'
                       ORDER BY due_date ASC NULLS LAST
                       LIMIT 100""",
                    [ORGANIZATION_ID],
                )
                rows = [dict(r) for r in result]
                return json.dumps(rows, ensure_ascii=False, default=str)

            elif uri == "soulkun://goals/active":
                result = conn.execute(
                    """SELECT id, title, description, status, progress_percentage
                       FROM goals
                       WHERE organization_id = %s AND status = 'active'
                       ORDER BY created_at DESC
                       LIMIT 50""",
                    [ORGANIZATION_ID],
                )
                rows = [dict(r) for r in result]
                return json.dumps(rows, ensure_ascii=False, default=str)

            elif uri == "soulkun://persons":
                # PII除外: メール・電話番号は返さない（鉄則#8）
                result = conn.execute(
                    """SELECT id, display_name, department, position
                       FROM persons
                       WHERE organization_id = %s
                       ORDER BY display_name
                       LIMIT 200""",
                    [ORGANIZATION_ID],
                )
                rows = [dict(r) for r in result]
                return json.dumps(rows, ensure_ascii=False, default=str)

            elif uri == "soulkun://departments":
                result = conn.execute(
                    """SELECT id, name, parent_id, path
                       FROM departments
                       WHERE organization_id = %s
                       ORDER BY path""",
                    [ORGANIZATION_ID],
                )
                rows = [dict(r) for r in result]
                return json.dumps(rows, ensure_ascii=False, default=str)

            else:
                return json.dumps({"error": f"Unknown resource: {uri}"})

        finally:
            conn.close()

    except Exception as e:
        logger.exception(f"Resource read failed: {uri}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# =============================================================================
# Prompts — 定型プロンプトテンプレート
# =============================================================================


@app.list_prompts()
async def list_prompts() -> List[Prompt]:
    """利用可能なプロンプト一覧"""
    return [
        Prompt(
            name="ceo_feedback",
            description="CEOフィードバック生成 — 指定したトピックについてCEO視点のフィードバックを生成",
            arguments=[
                PromptArgument(
                    name="topic",
                    description="フィードバック対象のトピック",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="weekly_summary",
            description="週次サマリー — 今週の活動・タスク・目標進捗をまとめる",
            arguments=[],
        ),
        Prompt(
            name="deep_research",
            description="ディープリサーチ — 社内ナレッジ＋外部情報を統合して調査",
            arguments=[
                PromptArgument(
                    name="query",
                    description="調査テーマ",
                    required=True,
                ),
            ],
        ),
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: Optional[Dict[str, str]] = None) -> GetPromptResult:
    """プロンプトテンプレートを取得"""
    if name == "ceo_feedback":
        topic = (arguments or {}).get("topic", "")
        return GetPromptResult(
            description="CEOフィードバック",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"以下のトピックについて、CEO視点でフィードバックをください。\n\nトピック: {topic}\n\n"
                             "【観点】\n"
                             "- ミッション（人でなくてもできることはテクノロジーに）との整合性\n"
                             "- 経営への影響とROI\n"
                             "- リスクと対策\n"
                             "- 次のアクション",
                    ),
                ),
            ],
        )

    elif name == "weekly_summary":
        return GetPromptResult(
            description="週次サマリー",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="今週の活動を振り返り、以下の形式でサマリーを作成してください。\n\n"
                             "## 今週の成果\n"
                             "- 完了タスク\n"
                             "- 目標進捗\n\n"
                             "## 来週の予定\n"
                             "- 重要タスク\n"
                             "- 注意事項\n\n"
                             "## 所感\n"
                             "- 気づき、改善点",
                    ),
                ),
            ],
        )

    elif name == "deep_research":
        query = (arguments or {}).get("query", "")
        return GetPromptResult(
            description="ディープリサーチ",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"以下のテーマについて、社内ナレッジベースと外部情報を統合して調査してください。\n\n"
                             f"テーマ: {query}\n\n"
                             "【出力形式】\n"
                             "1. 要約（3行以内）\n"
                             "2. 社内関連情報\n"
                             "3. 外部参考情報\n"
                             "4. 推奨アクション",
                    ),
                ),
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


# =============================================================================
# メイン
# =============================================================================


async def main():
    """MCPサーバー起動"""
    parser = argparse.ArgumentParser(description="ソウルくん MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8080, help="SSE port (default: 8080)")
    args = parser.parse_args()

    if args.transport == "stdio":
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    else:
        # SSE transport for HTTP-based clients
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        import uvicorn

        sse = SseServerTransport("/messages")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        starlette_app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
            ],
        )
        uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
