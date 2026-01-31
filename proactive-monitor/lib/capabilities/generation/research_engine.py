# lib/capabilities/generation/research_engine.py
"""
Phase G3: ディープリサーチ能力 - リサーチエンジン

このモジュールは、Perplexity等のWeb検索AIを使用して
深い調査を実行し、分析レポートを生成する機能を提供します。

設計書: docs/20_next_generation_capabilities.md セクション5.5
Author: Claude Opus 4.5
Created: 2026-01-27
"""

import os
import logging
import json
import re
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
import httpx

from .constants import (
    GenerationType,
    GenerationStatus,
    QualityLevel,
    ResearchDepth,
    ResearchType,
    SourceType,
    ReportFormat,
    PERPLEXITY_API_URL,
    PERPLEXITY_API_TIMEOUT_SECONDS,
    PERPLEXITY_MAX_RETRIES,
    PERPLEXITY_RETRY_DELAY_SECONDS,
    PERPLEXITY_DEFAULT_MODEL,
    PERPLEXITY_PRO_MODEL,
    MAX_CONCURRENT_SEARCHES,
    RESEARCH_DEPTH_CONFIG,
    RESEARCH_TYPE_DEFAULT_SECTIONS,
    RESEARCH_COST_PER_QUERY,
    RESEARCH_REPORT_COST_PER_1K_TOKENS,
    MAX_RESEARCH_QUERY_LENGTH,
    RESEARCH_PLAN_GENERATION_PROMPT,
    RESEARCH_ANALYSIS_PROMPT,
    RESEARCH_SUMMARY_PROMPT,
    FEATURE_FLAG_RESEARCH,
)
from .models import (
    ResearchRequest,
    ResearchResult,
    ResearchPlan,
    ResearchSource,
    GenerationMetadata,
    GenerationInput,
    GenerationOutput,
)
from .exceptions import (
    ResearchError,
    ResearchQueryEmptyError,
    ResearchQueryTooLongError,
    ResearchNoResultsError,
    ResearchInsufficientSourcesError,
    ResearchAnalysisError,
    ResearchReportGenerationError,
    PerplexityAPIError,
    PerplexityRateLimitError,
    PerplexityTimeoutError,
    ResearchFeatureDisabledError,
    wrap_research_error,
)
from .base import BaseGenerator


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# Perplexity クライアント
# =============================================================================


class PerplexityClient:
    """
    Perplexity APIクライアント

    Web検索を含むAI応答を取得する。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: int = PERPLEXITY_API_TIMEOUT_SECONDS,
        max_retries: int = PERPLEXITY_MAX_RETRIES,
    ):
        """
        初期化

        Args:
            api_key: Perplexity API Key
            timeout_seconds: タイムアウト秒数
            max_retries: 最大リトライ回数
        """
        self._api_key = api_key or os.environ.get("PERPLEXITY_API_KEY")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def search(
        self,
        query: str,
        model: str = PERPLEXITY_DEFAULT_MODEL,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Web検索を実行

        Args:
            query: 検索クエリ
            model: 使用モデル
            system_prompt: システムプロンプト

        Returns:
            検索結果（response, citations, tokens_used等）
        """
        if not self._api_key:
            logger.warning("Perplexity API key not configured")
            return {
                "success": False,
                "error": "API key not configured",
            }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})

        payload = {
            "model": model,
            "messages": messages,
        }

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        PERPLEXITY_API_URL,
                        headers=headers,
                        json=payload,
                    )

                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        if attempt < self._max_retries - 1:
                            await asyncio.sleep(PERPLEXITY_RETRY_DELAY_SECONDS * (attempt + 1))
                            continue
                        raise PerplexityRateLimitError(model=model, retry_after=retry_after)

                    response.raise_for_status()
                    data = response.json()

                    # レスポンス解析
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    citations = data.get("citations", [])
                    usage = data.get("usage", {})

                    return {
                        "success": True,
                        "response": content,
                        "citations": citations,
                        "model": model,
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    }

            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(PERPLEXITY_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                raise PerplexityTimeoutError(
                    model=model,
                    timeout_seconds=self._timeout_seconds
                )

            except httpx.HTTPStatusError as e:
                logger.error(f"Perplexity API error: {e.response.status_code}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(PERPLEXITY_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                raise PerplexityAPIError(
                    message=f"API error: {e.response.status_code}",
                    model=model,
                    original_error=e,
                )

        return {"success": False, "error": "Max retries exceeded"}


def create_perplexity_client(
    api_key: Optional[str] = None,
) -> PerplexityClient:
    """PerplexityClientを作成"""
    return PerplexityClient(api_key=api_key)


# =============================================================================
# リサーチエンジン
# =============================================================================


class ResearchEngine(BaseGenerator):
    """
    ディープリサーチエンジン

    Perplexity等を使用して深い調査を実行し、
    構造化されたレポートを生成する。

    使用例:
        engine = ResearchEngine(pool, org_id)
        result = await engine.generate(GenerationInput(
            generation_type=GenerationType.RESEARCH,
            organization_id=org_id,
            research_request=ResearchRequest(
                organization_id=org_id,
                query="競合A社について詳しく調べて",
                research_type=ResearchType.COMPETITOR,
                depth=ResearchDepth.STANDARD,
            ),
        ))
    """

    def __init__(
        self,
        pool,
        organization_id: UUID,
        api_key: Optional[str] = None,
        perplexity_api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: OpenRouter API Key（レポート生成用）
            perplexity_api_key: Perplexity API Key（検索用）
        """
        super().__init__(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
        )
        self._generation_type = GenerationType.RESEARCH
        self._perplexity_api_key = perplexity_api_key or os.environ.get("PERPLEXITY_API_KEY")
        self._perplexity_client = create_perplexity_client(api_key=self._perplexity_api_key)

    # =========================================================================
    # メイン処理
    # =========================================================================

    @wrap_research_error
    async def generate(self, input_data: GenerationInput) -> GenerationOutput:
        """
        ディープリサーチを実行

        Args:
            input_data: 生成入力

        Returns:
            GenerationOutput: 生成結果
        """
        request = input_data.research_request
        if not request:
            raise ResearchError(
                message="research_request is required",
                error_code="MISSING_REQUEST",
            )

        # 入力検証
        self._validate_request(request)

        # メタデータ初期化
        metadata = GenerationMetadata(
            organization_id=request.organization_id,
            user_id=request.user_id,
        )

        logger.info(f"Starting deep research: org={request.organization_id}, query={request.query[:50]}")

        try:
            # 1. 調査計画の生成
            plan = await self._create_research_plan(request)

            # 計画確認が必要な場合は保留状態で返す
            if request.require_plan_confirmation:
                result = ResearchResult(
                    status=GenerationStatus.PENDING,
                    success=False,
                    plan=plan,
                    estimated_cost_jpy=plan.estimated_cost_jpy,
                    metadata=metadata,
                )
                return GenerationOutput(
                    generation_type=GenerationType.RESEARCH,
                    success=True,  # 計画生成は成功
                    status=GenerationStatus.PENDING,
                    research_result=result,
                    metadata=metadata,
                )

            # 2. 情報収集
            sources = await self._gather_information(plan, request)

            if not sources:
                raise ResearchNoResultsError(query=request.query)

            # 3. 情報の分析・統合
            analysis = await self._analyze_sources(sources, plan, request)

            # 4. レポート生成
            report_content = await self._generate_report(analysis, plan, request)

            # 5. エグゼクティブサマリー生成
            summary = await self._generate_summary(report_content, request)

            # 6. Google Docsに保存（オプション）
            doc_url = None
            doc_id = None
            if request.save_to_drive:
                doc_result = await self._save_to_google_docs(
                    report_content=report_content,
                    title=f"リサーチレポート: {request.query[:30]}",
                    folder_id=request.drive_folder_id,
                )
                if doc_result:
                    doc_url = doc_result.get("url")
                    doc_id = doc_result.get("document_id")

            # 7. 結果構築
            result = ResearchResult(
                status=GenerationStatus.COMPLETED,
                success=True,
                plan=plan,
                sources=sources,
                sources_count=len(sources),
                executive_summary=summary.get("summary", ""),
                full_report=report_content,
                key_findings=summary.get("key_findings", []),
                recommendations=summary.get("recommendations", []),
                document_url=doc_url,
                document_id=doc_id,
                confidence_score=analysis.get("confidence", 0.7),
                coverage_score=analysis.get("coverage", 0.7),
                estimated_cost_jpy=plan.estimated_cost_jpy,
                actual_cost_jpy=self._calculate_actual_cost(plan, sources),
                metadata=metadata,
            )

            # 8. ChatWorkに送信（オプション）
            if request.send_to_chatwork and request.chatwork_room_id:
                await self._send_to_chatwork(
                    result=result,
                    room_id=request.chatwork_room_id,
                )
                result.chatwork_sent = True

            # メタデータ完了
            metadata.complete(success=True)
            result.metadata = metadata

            logger.info(
                f"Research completed: sources={len(sources)}, "
                f"cost=¥{result.actual_cost_jpy:.0f}"
            )

            return GenerationOutput(
                generation_type=GenerationType.RESEARCH,
                success=True,
                status=GenerationStatus.COMPLETED,
                research_result=result,
                metadata=metadata,
            )

        except ResearchError:
            raise

        except Exception as e:
            logger.error(f"Research failed: {e}")
            metadata.complete(success=False, error_message=str(e))

            return GenerationOutput(
                generation_type=GenerationType.RESEARCH,
                success=False,
                status=GenerationStatus.FAILED,
                research_result=ResearchResult(
                    status=GenerationStatus.FAILED,
                    success=False,
                    error_message=str(e),
                    metadata=metadata,
                ),
                metadata=metadata,
                error_message=str(e),
            )

    # =========================================================================
    # 検証
    # =========================================================================

    def validate(self, input_data: GenerationInput) -> None:
        """
        入力を検証

        Args:
            input_data: 生成入力

        Raises:
            ResearchError: 検証に失敗した場合
        """
        if input_data.research_request:
            self._validate_request(input_data.research_request)

    def _validate_request(self, request: ResearchRequest) -> None:
        """リクエストを検証"""
        # クエリチェック
        if not request.query or not request.query.strip():
            raise ResearchQueryEmptyError()

        if len(request.query) > MAX_RESEARCH_QUERY_LENGTH:
            raise ResearchQueryTooLongError(
                actual_length=len(request.query),
                max_length=MAX_RESEARCH_QUERY_LENGTH,
            )

    # =========================================================================
    # 調査計画生成
    # =========================================================================

    async def _create_research_plan(
        self,
        request: ResearchRequest,
    ) -> ResearchPlan:
        """調査計画を生成"""
        depth_config = RESEARCH_DEPTH_CONFIG.get(
            request.depth.value,
            RESEARCH_DEPTH_CONFIG[ResearchDepth.STANDARD.value]
        )

        # デフォルトセクションを取得
        default_sections = RESEARCH_TYPE_DEFAULT_SECTIONS.get(
            request.research_type.value,
            RESEARCH_TYPE_DEFAULT_SECTIONS[ResearchType.TOPIC.value]
        )

        # LLMで計画を生成
        prompt = RESEARCH_PLAN_GENERATION_PROMPT.format(
            query=request.query,
            research_type=request.research_type.value,
            depth=request.depth.value,
            instruction=request.instruction or "特になし",
        )

        try:
            result = await self._call_llm_json(
                prompt=prompt,
                temperature=0.3,
                task_type="outline",
                quality_level=request.quality_level,
            )
            parsed = result.get("parsed", {})

            search_queries = parsed.get("search_queries", [])
            if not search_queries:
                # フォールバック: 基本的な検索クエリを生成
                search_queries = self._generate_fallback_queries(request)

            expected_sections = parsed.get("expected_sections", default_sections)

            # 推定コスト計算
            estimated_cost = self._estimate_cost(
                num_queries=len(search_queries),
                depth=request.depth,
            )

            return ResearchPlan(
                query=request.query,
                research_type=request.research_type,
                depth=request.depth,
                search_queries=search_queries[:depth_config["max_queries"]],
                key_questions=parsed.get("key_questions", []),
                search_focus=parsed.get("search_focus", request.focus_areas),
                expected_sections=expected_sections,
                report_format=request.report_format,
                estimated_time_minutes=parsed.get(
                    "estimated_time_minutes",
                    depth_config["timeout_minutes"]
                ),
                estimated_cost_jpy=estimated_cost,
                tokens_used=result.get("total_tokens", 0),
            )

        except Exception as e:
            logger.warning(f"Plan generation with LLM failed: {e}")
            # フォールバック計画
            search_queries = self._generate_fallback_queries(request)
            return ResearchPlan(
                query=request.query,
                research_type=request.research_type,
                depth=request.depth,
                search_queries=search_queries,
                expected_sections=default_sections,
                report_format=request.report_format,
                estimated_time_minutes=depth_config["timeout_minutes"],
                estimated_cost_jpy=self._estimate_cost(
                    num_queries=len(search_queries),
                    depth=request.depth,
                ),
            )

    def _generate_fallback_queries(self, request: ResearchRequest) -> List[str]:
        """フォールバック検索クエリを生成"""
        queries = [request.query]

        if request.research_type == ResearchType.COMPANY:
            queries.extend([
                f"{request.query} 企業概要",
                f"{request.query} 事業内容",
                f"{request.query} 最新ニュース",
            ])
        elif request.research_type == ResearchType.COMPETITOR:
            queries.extend([
                f"{request.query} サービス 特徴",
                f"{request.query} 価格 料金",
                f"{request.query} 評判 口コミ",
            ])
        elif request.research_type == ResearchType.MARKET:
            queries.extend([
                f"{request.query} 市場規模",
                f"{request.query} トレンド 動向",
                f"{request.query} 主要プレイヤー",
            ])
        elif request.research_type == ResearchType.TECHNOLOGY:
            queries.extend([
                f"{request.query} 技術 仕組み",
                f"{request.query} ユースケース 事例",
                f"{request.query} メリット デメリット",
            ])
        else:
            queries.extend([
                f"{request.query} 概要",
                f"{request.query} 最新情報",
            ])

        return queries

    # =========================================================================
    # 情報収集
    # =========================================================================

    async def _gather_information(
        self,
        plan: ResearchPlan,
        request: ResearchRequest,
    ) -> List[ResearchSource]:
        """情報を収集"""
        sources = []
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

        async def search_with_limit(query: str) -> Optional[ResearchSource]:
            async with semaphore:
                return await self._search_single(query, request)

        # 並列検索
        tasks = [search_with_limit(q) for q in plan.search_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, ResearchSource):
                sources.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"Search failed: {result}")

        # 社内ナレッジ検索（オプション）
        if request.include_internal:
            internal_sources = await self._search_internal(plan.query, request)
            sources.extend(internal_sources)

        # 関連性でソート
        sources.sort(key=lambda s: s.relevance_score, reverse=True)

        return sources

    async def _search_single(
        self,
        query: str,
        request: ResearchRequest,
    ) -> Optional[ResearchSource]:
        """単一クエリで検索"""
        try:
            model = (
                PERPLEXITY_PRO_MODEL
                if request.quality_level == QualityLevel.HIGH_QUALITY
                else PERPLEXITY_DEFAULT_MODEL
            )

            result = await self._perplexity_client.search(
                query=query,
                model=model,
                system_prompt="Provide accurate, well-sourced information. Include relevant facts, dates, and numbers.",
            )

            if not result.get("success"):
                return None

            # ソースを構築
            citations = result.get("citations", [])
            source = ResearchSource(
                source_type=SourceType.WEB,
                title=query,
                content=result.get("response", ""),
                snippet=result.get("response", "")[:500],
                relevance_score=0.8,  # Perplexityの応答は概ね関連性が高い
                credibility_score=0.7,
                metadata={
                    "citations": citations,
                    "model": result.get("model"),
                    "tokens_used": result.get("total_tokens", 0),
                },
            )

            return source

        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            return None

    async def _search_internal(
        self,
        query: str,
        request: ResearchRequest,
    ) -> List[ResearchSource]:
        """社内ナレッジを検索"""
        # TODO: RAGシステムとの連携を実装
        # 現時点では未実装（将来対応）
        logger.info("Internal knowledge search not yet implemented")
        return []

    # =========================================================================
    # 分析
    # =========================================================================

    async def _analyze_sources(
        self,
        sources: List[ResearchSource],
        plan: ResearchPlan,
        request: ResearchRequest,
    ) -> Dict[str, Any]:
        """情報を分析"""
        if not sources:
            return {
                "confidence": 0.0,
                "coverage": 0.0,
                "key_points": [],
            }

        # ソースの内容を結合
        combined_content = "\n\n".join([
            f"【{s.title}】\n{s.content[:2000]}"
            for s in sources[:10]  # 上位10件を使用
        ])

        # 信頼度と網羅性を計算
        confidence = self._calculate_confidence(sources)
        coverage = self._calculate_coverage(sources, plan)

        return {
            "confidence": confidence,
            "coverage": coverage,
            "combined_content": combined_content,
            "source_count": len(sources),
        }

    def _calculate_confidence(self, sources: List[ResearchSource]) -> float:
        """信頼度を計算"""
        if not sources:
            return 0.0

        # 平均信頼性スコア
        avg_credibility = sum(s.credibility_score for s in sources) / len(sources)

        # ソース数によるボーナス
        source_bonus = min(len(sources) / 10, 0.2)

        return min(avg_credibility + source_bonus, 1.0)

    def _calculate_coverage(
        self,
        sources: List[ResearchSource],
        plan: ResearchPlan,
    ) -> float:
        """網羅性を計算"""
        if not sources or not plan.search_queries:
            return 0.0

        # 検索クエリに対するカバー率
        covered_queries = sum(
            1 for s in sources
            if any(q.lower() in s.content.lower() for q in plan.search_queries)
        )

        return min(covered_queries / len(plan.search_queries), 1.0)

    # =========================================================================
    # レポート生成
    # =========================================================================

    async def _generate_report(
        self,
        analysis: Dict[str, Any],
        plan: ResearchPlan,
        request: ResearchRequest,
    ) -> str:
        """レポートを生成"""
        prompt = RESEARCH_ANALYSIS_PROMPT.format(
            query=plan.query,
            sources=analysis.get("combined_content", ""),
            report_format=plan.report_format.value,
            sections="\n".join(f"- {s}" for s in plan.expected_sections),
        )

        try:
            result = await self._call_llm(
                prompt=prompt,
                temperature=0.3,
                task_type="content",
                quality_level=request.quality_level,
            )

            report = result.get("text", "")

            # タイトルを追加
            full_report = f"# リサーチレポート: {plan.query}\n\n"
            full_report += f"生成日: {datetime.now().strftime('%Y年%m月%d日')}\n\n"
            full_report += report

            return full_report

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            raise ResearchReportGenerationError(original_error=e)

    async def _generate_summary(
        self,
        report_content: str,
        request: ResearchRequest,
    ) -> Dict[str, Any]:
        """エグゼクティブサマリーを生成"""
        prompt = RESEARCH_SUMMARY_PROMPT.format(report=report_content[:8000])

        try:
            result = await self._call_llm_json(
                prompt=prompt,
                temperature=0.2,
                task_type="summary",
                quality_level=request.quality_level,
            )
            parsed = result.get("parsed", {})

            return {
                "summary": parsed.get("summary", ""),
                "key_findings": parsed.get("key_findings", []),
                "recommendations": parsed.get("recommendations", []),
            }

        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            # フォールバック: レポートの最初の部分を使用
            return {
                "summary": report_content[:500] if report_content else "",
                "key_findings": [],
                "recommendations": [],
            }

    # =========================================================================
    # コスト計算
    # =========================================================================

    def _estimate_cost(
        self,
        num_queries: int,
        depth: ResearchDepth,
    ) -> float:
        """推定コストを計算"""
        depth_config = RESEARCH_DEPTH_CONFIG.get(
            depth.value,
            RESEARCH_DEPTH_CONFIG[ResearchDepth.STANDARD.value]
        )

        # Perplexity検索コスト
        search_cost = num_queries * RESEARCH_COST_PER_QUERY.get(
            PERPLEXITY_DEFAULT_MODEL, 0.2
        )

        # レポート生成コスト（推定）
        report_cost = RESEARCH_REPORT_COST_PER_1K_TOKENS * 2  # 約2000トークン想定

        return search_cost + report_cost

    def _calculate_actual_cost(
        self,
        plan: ResearchPlan,
        sources: List[ResearchSource],
    ) -> float:
        """実際のコストを計算"""
        # 検索コスト
        search_cost = 0.0
        for source in sources:
            tokens = source.metadata.get("tokens_used", 0)
            model = source.metadata.get("model", PERPLEXITY_DEFAULT_MODEL)
            cost_per_query = RESEARCH_COST_PER_QUERY.get(model, 0.2)
            search_cost += cost_per_query

        # レポート生成コスト
        report_cost = RESEARCH_REPORT_COST_PER_1K_TOKENS * 2

        return search_cost + report_cost + plan.tokens_used * 0.003

    # =========================================================================
    # Google Docs保存
    # =========================================================================

    async def _save_to_google_docs(
        self,
        report_content: str,
        title: str,
        folder_id: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Google Docsにレポートを保存"""
        # TODO: Google Docs API連携実装
        # 現時点では未実装（将来対応）
        logger.info(f"Google Docs save not yet implemented: {title}")
        return None

    # =========================================================================
    # ChatWork送信
    # =========================================================================

    async def _send_to_chatwork(
        self,
        result: ResearchResult,
        room_id: str,
    ) -> bool:
        """ChatWorkにレポートを送信"""
        # TODO: ChatWork API連携実装
        # 現時点では未実装（将来対応）
        logger.info(f"ChatWork send not yet implemented: room={room_id}")
        return False


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_research_engine(
    pool,
    organization_id: UUID,
    api_key: Optional[str] = None,
    perplexity_api_key: Optional[str] = None,
) -> ResearchEngine:
    """
    ResearchEngineを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key（レポート生成用）
        perplexity_api_key: Perplexity API Key（検索用）

    Returns:
        ResearchEngine: リサーチエンジン
    """
    return ResearchEngine(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        perplexity_api_key=perplexity_api_key,
    )
