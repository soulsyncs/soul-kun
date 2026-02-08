# lib/brain/env_config.py
"""
環境変数の一元管理

v10.53.1: 環境変数名の不一致問題の再発防止

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

# LLM Brain有効化フラグ
# 注意: 歴史的理由で USE_BRAIN_ARCHITECTURE を使用
# ENABLE_LLM_BRAIN は使わない！
ENV_BRAIN_ENABLED = "USE_BRAIN_ARCHITECTURE"

# ログ設定
ENV_LOG_EXECUTION_ID = "LOG_EXECUTION_ID"

# System Prompt v2
ENV_SYSTEM_PROMPT_V2 = "ENABLE_SYSTEM_PROMPT_V2"

# ナレッジ検索回答生成（Phase 3.5: Brain Tool統合後に追加予定）


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


def get_required_env_vars() -> dict:
    """
    デプロイ時に必須の環境変数一覧を取得
    
    cloudbuild.yamlやdeploy.shはこの値を使うべき
    """
    return {
        ENV_BRAIN_ENABLED: "true",
        ENV_LOG_EXECUTION_ID: "true",
    }


def validate_env_vars() -> list:
    """
    環境変数の設定を検証
    
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
