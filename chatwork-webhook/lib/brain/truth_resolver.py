# lib/brain/truth_resolver.py
"""
Truth順位リゾルバー

CLAUDE.md セクション3で定義されたデータソース優先順位に基づいて
データを取得するリゾルバー。

【Truth順位】
1位: リアルタイムAPI（ChatWork API, Google API等）
2位: DB（正規データ）
3位: 設計書・仕様書
4位: Memory（会話の文脈）
5位: 推測 → **禁止**（GuessNotAllowedErrorを発生）

【設計書参照】
- CLAUDE.md セクション3「データソース優先順位（Truth順位）【最重要】」
  - 質問に答えるとき、この順番でデータを探す
  - 5位（推測）は禁止
- docs/13_brain_architecture.md セクション5「記憶層」
  - 記憶の種類と優先度

Author: Claude Opus 4.5
Created: 2026-01-29
"""

import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable, Awaitable

from lib.brain.constants import (
    TruthSource,
    TruthSourceResult,
    TruthSourceConfig,
    QUERY_TYPE_SOURCE_MAP,
    DEFAULT_TRUTH_SOURCE_CONFIGS,
    FEATURE_FLAG_TRUTH_RESOLVER,
    DEFAULT_FEATURE_FLAGS,
)
from lib.brain.exceptions import BrainError

logger = logging.getLogger(__name__)


# =============================================================================
# 例外クラス
# =============================================================================


class TruthResolverError(BrainError):
    """TruthResolver関連のエラー基底クラス"""

    pass


class GuessNotAllowedError(TruthResolverError):
    """
    推測が必要な状況で発生するエラー

    CLAUDE.md セクション3: 5位: 推測は**禁止**
    すべてのデータソースで取得に失敗し、推測が必要な状況は許可されない。
    """

    def __init__(self, query_type: str, attempted_sources: List[TruthSource]):
        self.query_type = query_type
        self.attempted_sources = attempted_sources
        super().__init__(
            f"全てのデータソースで取得に失敗しました。"
            f"query_type={query_type}, "
            f"attempted_sources={[s.name for s in attempted_sources]}。"
            f"推測（5位）は禁止されています。ユーザーに確認を取ってください。"
        )


class TruthSourceExhaustedError(TruthResolverError):
    """すべてのデータソースが使い果たされた"""

    pass


class TruthSourceTimeoutError(TruthResolverError):
    """データソースへのアクセスがタイムアウト"""

    pass


# =============================================================================
# TruthResolver クラス
# =============================================================================


class TruthResolver:
    """
    Truth順位に基づいてデータを取得するリゾルバー

    責務:
    - データソースの優先順位に従った取得
    - フォールバック制御
    - 推測の禁止を強制
    - 取得結果のメタデータ付与

    使用例:
        resolver = TruthResolver(
            org_id="org_soulsyncs",
            api_clients={"chatwork": chatwork_client},
            db_accessor=db_accessor,
            memory_accessor=memory_accessor,
        )

        result = await resolver.resolve(
            query_type="dm_contacts",
            query_params={"account_id": "123"},
        )
        # result.source == TruthSource.REALTIME_API
    """

    def __init__(
        self,
        org_id: str,
        api_clients: Optional[Dict[str, Any]] = None,
        db_accessor: Optional[Any] = None,
        memory_accessor: Optional[Any] = None,
        spec_accessor: Optional[Any] = None,
        source_configs: Optional[Dict[TruthSource, TruthSourceConfig]] = None,
        feature_flags: Optional[Dict[str, bool]] = None,
    ):
        """
        Args:
            org_id: 組織ID
            api_clients: APIクライアントのマッピング（chatwork, google等）
            db_accessor: データベースアクセサー
            memory_accessor: メモリアクセサー
            spec_accessor: 設計書アクセサー
            source_configs: データソースごとの設定
            feature_flags: Feature Flags
        """
        self.org_id = org_id
        self._api_clients = api_clients or {}
        self._db_accessor = db_accessor
        self._memory_accessor = memory_accessor
        self._spec_accessor = spec_accessor
        self._source_configs = source_configs or DEFAULT_TRUTH_SOURCE_CONFIGS.copy()
        self._feature_flags = feature_flags or DEFAULT_FEATURE_FLAGS.copy()

        # カスタムフェッチャーの登録
        self._custom_fetchers: Dict[str, Callable[..., Awaitable[Any]]] = {}

        logger.info(
            f"TruthResolver initialized: org_id={org_id}, "
            f"api_clients={list(self._api_clients.keys())}, "
            f"db_accessor={'yes' if db_accessor else 'no'}, "
            f"memory_accessor={'yes' if memory_accessor else 'no'}"
        )

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def resolve(
        self,
        query_type: str,
        query_params: Optional[Dict[str, Any]] = None,
        required_source: Optional[TruthSource] = None,
        max_source_level: Optional[TruthSource] = None,
        allow_fallback: bool = True,
    ) -> TruthSourceResult:
        """
        Truth順位に従ってデータを取得

        Args:
            query_type: クエリの種類（dm_contacts, user_profile等）
            query_params: クエリパラメータ
            required_source: 必須のデータソース（指定時はこれのみ使用）
            max_source_level: 使用する最大のソースレベル
            allow_fallback: フォールバックを許可するか

        Returns:
            TruthSourceResult: 取得結果（ソース情報付き）

        Raises:
            GuessNotAllowedError: すべてのソースで取得失敗（推測は禁止）
        """
        query_params = query_params or {}
        start_time = time.time()

        # 推奨ソースを決定
        preferred_source = self._get_preferred_source(query_type, required_source)

        # 試行するソースのリストを構築
        sources_to_try = self._build_source_list(
            preferred_source, max_source_level, allow_fallback
        )

        logger.debug(
            f"TruthResolver.resolve: query_type={query_type}, "
            f"preferred_source={preferred_source.name}, "
            f"sources_to_try={[s.name for s in sources_to_try]}"
        )

        # 各ソースを順番に試行
        attempted_sources: List[TruthSource] = []
        last_error: Optional[Exception] = None

        for source in sources_to_try:
            config = self._source_configs.get(source)
            if config and not config.enabled:
                logger.debug(f"Source {source.name} is disabled, skipping")
                continue

            attempted_sources.append(source)

            try:
                data = await self._fetch_from_source(
                    source, query_type, query_params, config
                )

                if data is not None:
                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.info(
                        f"TruthResolver: query_type={query_type} resolved from "
                        f"{source.name} in {elapsed_ms:.1f}ms"
                    )

                    return TruthSourceResult(
                        source=source,
                        data=data,
                        confidence=self._calculate_confidence(source, preferred_source),
                        timestamp=datetime.now().isoformat(),
                        metadata={
                            "query_type": query_type,
                            "elapsed_ms": elapsed_ms,
                        },
                        fallback_used=source != preferred_source,
                        original_source=preferred_source if source != preferred_source else None,
                    )

            except Exception as e:
                last_error = e
                logger.warning(
                    f"TruthResolver: Failed to fetch from {source.name}: {e}"
                )
                # フォールバックが許可されていれば次のソースを試行
                if not allow_fallback:
                    break

        # すべてのソースで失敗 → 推測は禁止
        logger.error(
            f"TruthResolver: All sources exhausted for query_type={query_type}. "
            f"Guess is NOT allowed (CLAUDE.md Section 3)."
        )
        raise GuessNotAllowedError(query_type, attempted_sources)

    # =========================================================================
    # ソース選択ロジック
    # =========================================================================

    def _get_preferred_source(
        self,
        query_type: str,
        required_source: Optional[TruthSource] = None,
    ) -> TruthSource:
        """推奨ソースを決定"""
        if required_source:
            return required_source

        # QUERY_TYPE_SOURCE_MAPから取得
        if query_type in QUERY_TYPE_SOURCE_MAP:
            return QUERY_TYPE_SOURCE_MAP[query_type]

        # デフォルトはDB
        logger.debug(
            f"Unknown query_type '{query_type}', defaulting to DATABASE"
        )
        return TruthSource.DATABASE

    def _build_source_list(
        self,
        preferred_source: TruthSource,
        max_source_level: Optional[TruthSource],
        allow_fallback: bool,
    ) -> List[TruthSource]:
        """試行するソースのリストを構築"""
        if not allow_fallback:
            return [preferred_source]

        # 優先度順のソースリスト
        all_sources = TruthSource.get_priority_order()

        # 推奨ソースから始めて、それ以降のソースを追加
        sources = []
        found_preferred = False

        for source in all_sources:
            if source == preferred_source:
                found_preferred = True

            if found_preferred:
                # max_source_levelを超えたら終了
                if max_source_level and source > max_source_level:
                    break
                sources.append(source)

        return sources

    def _calculate_confidence(
        self,
        actual_source: TruthSource,
        preferred_source: TruthSource,
    ) -> float:
        """取得結果の確信度を計算"""
        if actual_source == preferred_source:
            return 1.0

        # フォールバックした場合は確信度を下げる
        source_diff = actual_source.value - preferred_source.value
        return max(0.5, 1.0 - (source_diff * 0.15))

    # =========================================================================
    # データ取得（各ソース）
    # =========================================================================

    async def _fetch_from_source(
        self,
        source: TruthSource,
        query_type: str,
        params: Dict[str, Any],
        config: Optional[TruthSourceConfig] = None,
    ) -> Optional[Any]:
        """指定されたソースからデータを取得"""
        # カスタムフェッチャーがあれば使用
        fetcher_key = f"{source.name}:{query_type}"
        if fetcher_key in self._custom_fetchers:
            return await self._custom_fetchers[fetcher_key](params)

        # ソースタイプに応じた取得
        if source == TruthSource.REALTIME_API:
            return await self._fetch_from_api(query_type, params, config)
        elif source == TruthSource.DATABASE:
            return await self._fetch_from_db(query_type, params, config)
        elif source == TruthSource.SPECIFICATION:
            return await self._fetch_from_spec(query_type, params, config)
        elif source == TruthSource.MEMORY:
            return await self._fetch_from_memory(query_type, params, config)

        return None

    async def _fetch_from_api(
        self,
        query_type: str,
        params: Dict[str, Any],
        config: Optional[TruthSourceConfig] = None,
    ) -> Optional[Any]:
        """
        1位: リアルタイムAPIからの取得

        対応クエリタイプ:
        - dm_contacts: ChatWork APIからDM可能な相手を取得
        - room_members: ChatWork APIからルームメンバーを取得
        - current_tasks: ChatWork APIから現在のタスクを取得
        """
        if not self._api_clients:
            logger.debug("No API clients configured")
            return None

        # ChatWork API
        if query_type in ("dm_contacts", "room_members", "current_tasks", "user_status"):
            chatwork_client = self._api_clients.get("chatwork")
            if not chatwork_client:
                logger.debug("ChatWork client not available")
                return None

            try:
                if query_type == "dm_contacts":
                    # DMできる相手を取得
                    if hasattr(chatwork_client, "get_contacts"):
                        return await self._call_async_or_sync(
                            chatwork_client.get_contacts
                        )
                elif query_type == "room_members":
                    room_id = params.get("room_id")
                    if room_id and hasattr(chatwork_client, "get_room_members"):
                        return await self._call_async_or_sync(
                            chatwork_client.get_room_members, room_id
                        )
                elif query_type == "current_tasks":
                    if hasattr(chatwork_client, "get_my_tasks"):
                        return await self._call_async_or_sync(
                            chatwork_client.get_my_tasks
                        )
            except Exception as e:
                logger.warning(f"API fetch failed for {query_type}: {e}")
                raise

        return None

    async def _fetch_from_db(
        self,
        query_type: str,
        params: Dict[str, Any],
        config: Optional[TruthSourceConfig] = None,
    ) -> Optional[Any]:
        """
        2位: DBからの取得

        対応クエリタイプ:
        - user_profile: ユーザープロファイル
        - task_history: タスク履歴
        - organization_info: 組織情報
        - person_info: 人物情報
        - goal_info: 目標情報
        - knowledge_base: ナレッジベース
        """
        if not self._db_accessor:
            logger.debug("DB accessor not configured")
            return None

        try:
            # DBアクセサーのメソッドを呼び出し
            method_map = {
                "user_profile": "get_user_profile",
                "task_history": "get_task_history",
                "organization_info": "get_organization_info",
                "person_info": "get_person_info",
                "goal_info": "get_goal_info",
                "knowledge_base": "search_knowledge",
            }

            method_name = method_map.get(query_type)
            if method_name and hasattr(self._db_accessor, method_name):
                method = getattr(self._db_accessor, method_name)
                return await self._call_async_or_sync(method, **params)

        except Exception as e:
            logger.warning(f"DB fetch failed for {query_type}: {e}")
            raise

        return None

    async def _fetch_from_spec(
        self,
        query_type: str,
        params: Dict[str, Any],
        config: Optional[TruthSourceConfig] = None,
    ) -> Optional[Any]:
        """
        3位: 設計書・仕様書からの取得

        対応クエリタイプ:
        - system_spec: システム仕様
        - feature_definition: 機能定義
        - api_reference: API仕様
        """
        if not self._spec_accessor:
            logger.debug("Specification accessor not configured")
            return None

        try:
            if hasattr(self._spec_accessor, "get_spec"):
                return await self._call_async_or_sync(
                    self._spec_accessor.get_spec, query_type, params
                )
        except Exception as e:
            logger.warning(f"Spec fetch failed for {query_type}: {e}")
            raise

        return None

    async def _fetch_from_memory(
        self,
        query_type: str,
        params: Dict[str, Any],
        config: Optional[TruthSourceConfig] = None,
    ) -> Optional[Any]:
        """
        4位: Memoryからの取得

        対応クエリタイプ:
        - user_preference: ユーザーの好み
        - conversation_context: 会話の文脈
        - recent_topic: 最近の話題
        - user_mood: ユーザーの気分
        """
        if not self._memory_accessor:
            logger.debug("Memory accessor not configured")
            return None

        try:
            method_map = {
                "user_preference": "get_user_preferences",
                "conversation_context": "get_conversation_context",
                "recent_topic": "get_recent_topics",
                "user_mood": "get_user_mood",
            }

            method_name = method_map.get(query_type)
            if method_name and hasattr(self._memory_accessor, method_name):
                method = getattr(self._memory_accessor, method_name)
                return await self._call_async_or_sync(method, **params)

        except Exception as e:
            logger.warning(f"Memory fetch failed for {query_type}: {e}")
            raise

        return None

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    async def _call_async_or_sync(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """同期/非同期関数を統一的に呼び出し"""
        import asyncio
        import inspect

        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            # 同期関数の場合はスレッドプールで実行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def register_custom_fetcher(
        self,
        source: TruthSource,
        query_type: str,
        fetcher: Callable[..., Awaitable[Any]],
    ) -> None:
        """
        カスタムフェッチャーを登録

        特定のソース/クエリタイプの組み合わせに対して
        カスタムの取得ロジックを設定できる。

        Args:
            source: データソース
            query_type: クエリタイプ
            fetcher: 取得関数（async）
        """
        key = f"{source.name}:{query_type}"
        self._custom_fetchers[key] = fetcher
        logger.debug(f"Registered custom fetcher for {key}")

    def is_enabled(self) -> bool:
        """TruthResolverが有効かどうか"""
        return self._feature_flags.get(FEATURE_FLAG_TRUTH_RESOLVER, False)


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_truth_resolver(
    org_id: str,
    api_clients: Optional[Dict[str, Any]] = None,
    db_accessor: Optional[Any] = None,
    memory_accessor: Optional[Any] = None,
    spec_accessor: Optional[Any] = None,
    feature_flags: Optional[Dict[str, bool]] = None,
) -> TruthResolver:
    """
    TruthResolverのインスタンスを作成

    使用例:
        resolver = create_truth_resolver(
            org_id="org_soulsyncs",
            api_clients={"chatwork": chatwork_client},
            db_accessor=db_accessor,
        )
    """
    return TruthResolver(
        org_id=org_id,
        api_clients=api_clients,
        db_accessor=db_accessor,
        memory_accessor=memory_accessor,
        spec_accessor=spec_accessor,
        feature_flags=feature_flags,
    )
