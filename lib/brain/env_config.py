# lib/brain/env_config.py
"""
環境変数の一元管理

v10.53.1: 環境変数名の不一致問題の再発防止
v11.2.0: 全必須環境変数を登録（3AI品質改善プラン Task②）

【重要】
環境変数を追加/変更する場合は必ずこのファイルを更新すること。
他のファイルで直接os.environ.get()を使わず、このモジュールを使う。

関連ファイル:
- cloudbuild.yaml
- cloudbuild-proactive-monitor.yaml
- chatwork-webhook/deploy.sh
- proactive-monitor/deploy.sh
"""

import os
from typing import Optional


# =============================================================================
# 環境変数名の定義（Single Source of Truth）
# =============================================================================

# --- Brain 有効化・ロールアウト制御 ---
# 注意: 歴史的理由で USE_BRAIN_ARCHITECTURE を使用
# ENABLE_LLM_BRAIN は使わない！
ENV_BRAIN_ENABLED = "USE_BRAIN_ARCHITECTURE"
ENV_BRAIN_GRADUAL_PERCENTAGE = "BRAIN_GRADUAL_PERCENTAGE"
ENV_BRAIN_ALLOWED_ROOMS = "BRAIN_ALLOWED_ROOMS"
ENV_BRAIN_ALLOWED_USERS = "BRAIN_ALLOWED_USERS"

# --- LLMモデル設定 ---
# Brain判断用LLM（推論精度重視）
ENV_LLM_BRAIN_MODEL = "LLM_BRAIN_MODEL"
# 一般AI補助処理用（コスパ重視）
ENV_DEFAULT_AI_MODEL = "DEFAULT_AI_MODEL"

# --- APIキー ---
ENV_OPENROUTER_API_KEY = "OPENROUTER_API_KEY"
ENV_TAVILY_API_KEY = "TAVILY_API_KEY"

# --- 観測・モニタリング（Langfuse） ---
ENV_LANGFUSE_SECRET_KEY = "LANGFUSE_SECRET_KEY"
ENV_LANGFUSE_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
ENV_LANGFUSE_HOST = "LANGFUSE_HOST"
ENV_LANGFUSE_ENABLED = "LANGFUSE_ENABLED"

# --- ログ・実行環境 ---
ENV_LOG_EXECUTION_ID = "LOG_EXECUTION_ID"
ENV_ENVIRONMENT = "ENVIRONMENT"

# --- 機能フラグ ---
ENV_SYSTEM_PROMPT_V2 = "ENABLE_SYSTEM_PROMPT_V2"
ENV_ENABLE_MEETING_TRANSCRIPTION = "ENABLE_MEETING_TRANSCRIPTION"
ENV_ENABLE_MEETING_MINUTES = "ENABLE_MEETING_MINUTES"
ENV_ENABLE_IMAGE_ANALYSIS = "ENABLE_IMAGE_ANALYSIS"
ENV_ENABLE_GOOGLE_CALENDAR = "ENABLE_GOOGLE_CALENDAR"

# --- アラート ---
ENV_ALERT_ROOM_ID = "ALERT_ROOM_ID"

# --- GCSバケット ---
ENV_MEETING_GCS_BUCKET = "MEETING_GCS_BUCKET"
ENV_OPERATIONS_GCS_BUCKET = "OPERATIONS_GCS_BUCKET"

# --- Pinecone（ベクトル検索） ---
ENV_PINECONE_INDEX_NAME = "PINECONE_INDEX_NAME"

# --- Telegram ---
ENV_TELEGRAM_CEO_CHAT_ID = "TELEGRAM_CEO_CHAT_ID"
ENV_TELEGRAM_BOT_USERNAME = "TELEGRAM_BOT_USERNAME"
ENV_TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_TELEGRAM_WEBHOOK_SECRET = "TELEGRAM_WEBHOOK_SECRET"


# =============================================================================
# 環境変数取得関数
# =============================================================================

def is_brain_enabled() -> bool:
    """LLM Brainが有効かどうかを取得"""
    value = os.environ.get(ENV_BRAIN_ENABLED, "false").lower()
    return value in ("true", "1", "yes", "enabled", "shadow", "gradual")


def is_log_execution_id_enabled() -> bool:
    """実行IDログが有効かどうかを取得"""
    value = os.environ.get(ENV_LOG_EXECUTION_ID, "false").lower()
    return value in ("true", "1", "yes")


def is_system_prompt_v2_enabled() -> bool:
    """System Prompt v2が有効かどうかを取得"""
    value = os.environ.get(ENV_SYSTEM_PROMPT_V2, "false").lower()
    return value in ("true", "1", "yes")


def is_production() -> bool:
    """本番環境かどうかを取得"""
    return os.environ.get(ENV_ENVIRONMENT, "development").lower() == "production"


def get_required_env_vars() -> dict:
    """
    デプロイ時に必須の環境変数一覧を取得（サービス起動に不可欠なもの）

    cloudbuild.yamlやdeploy.shはこの値を使うべき

    注意:
    - APIキー（OPENROUTER_API_KEY等）はSecret Manager経由で注入されるため
      ここには含まない（値が平文で露出するリスクを避けるため）
    - Secretsは cloudbuild.yaml の --update-secrets で管理すること
    """
    return {
        ENV_BRAIN_ENABLED: os.environ.get(ENV_BRAIN_ENABLED, "false"),
        ENV_LOG_EXECUTION_ID: os.environ.get(ENV_LOG_EXECUTION_ID, "false"),
        ENV_ENVIRONMENT: os.environ.get(ENV_ENVIRONMENT, "(unset)"),
        ENV_LLM_BRAIN_MODEL: os.environ.get(ENV_LLM_BRAIN_MODEL, "(unset)"),
        ENV_DEFAULT_AI_MODEL: os.environ.get(ENV_DEFAULT_AI_MODEL, "(unset)"),
        ENV_LANGFUSE_ENABLED: os.environ.get(ENV_LANGFUSE_ENABLED, "(unset)"),
        ENV_ALERT_ROOM_ID: os.environ.get(ENV_ALERT_ROOM_ID, "(unset)"),
        ENV_ENABLE_MEETING_TRANSCRIPTION: os.environ.get(ENV_ENABLE_MEETING_TRANSCRIPTION, "(unset)"),
        ENV_ENABLE_MEETING_MINUTES: os.environ.get(ENV_ENABLE_MEETING_MINUTES, "(unset)"),
        ENV_ENABLE_IMAGE_ANALYSIS: os.environ.get(ENV_ENABLE_IMAGE_ANALYSIS, "(unset)"),
        ENV_MEETING_GCS_BUCKET: os.environ.get(ENV_MEETING_GCS_BUCKET, "(unset)"),
        ENV_OPERATIONS_GCS_BUCKET: os.environ.get(ENV_OPERATIONS_GCS_BUCKET, "(unset)"),
        ENV_PINECONE_INDEX_NAME: os.environ.get(ENV_PINECONE_INDEX_NAME, "(unset)"),
    }


def get_missing_required_vars() -> list[str]:
    """
    未設定の必須環境変数名のリストを返す。
    起動時チェックや管理画面の死活監視で使用する。

    Returns:
        未設定の環境変数名リスト（空なら問題なし）
    """
    required = [
        ENV_BRAIN_ENABLED,
        ENV_ENVIRONMENT,
        ENV_OPENROUTER_API_KEY,
        ENV_LLM_BRAIN_MODEL,
        ENV_DEFAULT_AI_MODEL,
        ENV_ALERT_ROOM_ID,
        ENV_MEETING_GCS_BUCKET,
        ENV_OPERATIONS_GCS_BUCKET,
        ENV_PINECONE_INDEX_NAME,
    ]
    return [var for var in required if not os.environ.get(var)]


def validate_env_vars() -> list:
    """
    環境変数の設定を検証（非推奨変数のみチェック）

    必須変数の未設定チェックは get_missing_required_vars() を使うこと。

    Returns:
        警告メッセージのリスト（空なら問題なし）
    """
    warnings = []

    # 古い環境変数名が使われていないかチェック
    deprecated_vars = ["ENABLE_LLM_BRAIN"]
    for var in deprecated_vars:
        if os.environ.get(var):
            warnings.append(
                f"⚠️ 非推奨の環境変数 {var} が設定されています。"
                f"代わりに {ENV_BRAIN_ENABLED} を使用してください。"
            )

    return warnings
