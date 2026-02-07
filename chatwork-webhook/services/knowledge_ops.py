"""services/knowledge_ops.py - ナレッジハンドラーシングルトン

Phase 11: _get_knowledge_handler を main.py から分離。
memory_actions.py, org_knowledge_actions.py から参照される。

依存: infra/db.py, infra/helpers.py, services/proposal_actions.py
"""

import os

import httpx

from infra.db import get_pool, get_secret
from infra.helpers import is_admin

from handlers.knowledge_handler import KnowledgeHandler as _NewKnowledgeHandler

# MVVコンテキスト
_MVV_DISABLED_BY_ENV = os.environ.get("DISABLE_MVV_CONTEXT", "").lower() == "true"
USE_MVV_CONTEXT = False
is_mvv_question = None
get_full_mvv_info = None

if not _MVV_DISABLED_BY_ENV:
    try:
        from lib.mvv_context import (
            is_mvv_question,
            get_full_mvv_info,
        )
        USE_MVV_CONTEXT = True
    except ImportError:
        pass

# 管理者設定
try:
    from lib.admin_config import get_admin_config
    _admin_config = get_admin_config()
    ADMIN_ACCOUNT_ID = _admin_config.admin_account_id
except ImportError:
    ADMIN_ACCOUNT_ID = "1728974"

# モデル設定
MODELS = {
    "default": "google/gemini-3-flash-preview",
    "commander": "google/gemini-3-flash-preview",
}
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Phase 3 ナレッジ設定
PHASE3_KNOWLEDGE_CONFIG = {
    "api_url": os.getenv(
        "KNOWLEDGE_SEARCH_API_URL",
        "https://soulkun-api-898513057014.asia-northeast1.run.app/api/v1/knowledge/search"
    ),
    "enabled": os.getenv("ENABLE_PHASE3_KNOWLEDGE", "true").lower() == "true",
    "timeout": float(os.getenv("PHASE3_TIMEOUT", "30")),
    "similarity_threshold": float(os.getenv("PHASE3_SIMILARITY_THRESHOLD", "0.5")),
    "organization_id": os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df"),
    "keyword_weight": float(os.getenv("PHASE3_KEYWORD_WEIGHT", "0.4")),
    "vector_weight": float(os.getenv("PHASE3_VECTOR_WEIGHT", "0.6")),
}

_knowledge_handler = None


def call_openrouter_api(system_prompt: str, user_message: str, model: str = None) -> str | None:
    """OpenRouter APIで回答を生成（KnowledgeHandler用）"""
    try:
        api_key = get_secret("openrouter-api-key")
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model or MODELS["default"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 1000,
                "temperature": 0.7,
            },
            timeout=30.0
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        print(f"⚠️ OpenRouter API error: {response.status_code}")
        return None
    except Exception as e:
        print(f"❌ OpenRouter API呼び出しエラー: {e}")
        return None


def _get_knowledge_handler():
    """KnowledgeHandlerのシングルトンインスタンスを取得"""
    global _knowledge_handler
    if _knowledge_handler is None:
        # 循環import回避: proposal_actions は遅延import
        from services.proposal_actions import create_proposal, report_proposal_to_admin

        # MVV関数の取得
        mvv_question_func = None
        mvv_info_func = None
        if USE_MVV_CONTEXT:
            try:
                mvv_question_func = is_mvv_question
                mvv_info_func = get_full_mvv_info
            except NameError:
                pass

        _knowledge_handler = _NewKnowledgeHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            is_admin_func=is_admin,
            create_proposal_func=create_proposal,
            report_proposal_to_admin_func=report_proposal_to_admin,
            is_mvv_question_func=mvv_question_func,
            get_full_mvv_info_func=mvv_info_func,
            call_openrouter_api_func=call_openrouter_api,
            phase3_knowledge_config=PHASE3_KNOWLEDGE_CONFIG,
            default_model=MODELS["default"],
            admin_account_id=ADMIN_ACCOUNT_ID,
            openrouter_api_url=OPENROUTER_API_URL
        )
    return _knowledge_handler
