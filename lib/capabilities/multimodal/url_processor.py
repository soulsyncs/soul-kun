# lib/capabilities/multimodal/url_processor.py
"""
Phase M1: Multimodal入力能力 - URL処理プロセッサー

このモジュールは、URLの取得・解析・要約機能を提供します。

処理フロー:
1. URLセキュリティチェック
2. コンテンツ取得
3. HTML本文抽出
4. メタデータ抽出
5. LLMで分析・要約
6. 会社文脈との関連付け

ユースケース:
- 記事の要約 → 共有支援
- 競合サイトの分析 → レポート作成
- ドキュメントの読み込み → ナレッジ参照

設計書: docs/20_next_generation_capabilities.md セクション5.5
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urljoin
import logging
import re
import json
import socket
import ipaddress

import httpx

from .constants import (
    InputType,
    ProcessingStatus,
    URLType,
    ContentConfidenceLevel,
    SUPPORTED_URL_PROTOCOLS,
    BLOCKED_DOMAINS,
    BLOCKED_IP_PREFIXES,
    MAX_URL_CONTENT_SIZE_BYTES,
    URL_FETCH_TIMEOUT_SECONDS,
    USER_AGENT,
    HTML_EXCLUDE_TAGS,
    HTML_METADATA_TAGS,
    MAX_EXTRACTED_TEXT_LENGTH,
    MAX_SUMMARY_LENGTH,
)
from .exceptions import (
    ValidationError,
    URLProcessingError,
    URLBlockedError,
    URLFetchError,
    URLTimeoutError,
    URLParseError,
    URLContentExtractionError,
    wrap_multimodal_error,
)
from .models import (
    ProcessingMetadata,
    ExtractedEntity,
    URLMetadata,
    URLAnalysisResult,
    MultimodalInput,
    MultimodalOutput,
)
from .base import BaseMultimodalProcessor


logger = logging.getLogger(__name__)


# =============================================================================
# URLProcessor
# =============================================================================


class URLProcessor(BaseMultimodalProcessor):
    """
    URL処理プロセッサー

    URLからコンテンツを取得し、解析・要約を行う。

    使用例:
        processor = URLProcessor(pool, org_id)
        result = await processor.process(MultimodalInput(
            input_type=InputType.URL,
            organization_id=org_id,
            url="https://example.com/article",
            instruction="この記事を要約して",
        ))
        print(result.url_result.summary)
    """

    def __init__(
        self,
        pool,
        organization_id: str,
        api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: OpenRouter API Key
        """
        super().__init__(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
            input_type=InputType.URL,
        )

    # =========================================================================
    # 公開API
    # =========================================================================

    @wrap_multimodal_error
    async def process(self, input_data: MultimodalInput) -> MultimodalOutput:
        """
        URLを処理

        処理フロー:
        1. 入力検証
        2. URLセキュリティチェック
        3. コンテンツ取得
        4. HTMLパース・本文抽出
        5. メタデータ抽出
        6. LLMで分析
        7. 会社文脈との関連付け
        8. エンティティ抽出

        Args:
            input_data: 入力データ

        Returns:
            MultimodalOutput: 処理結果
        """
        # メタデータ初期化
        metadata = self._create_processing_metadata()
        self._log_processing_start("url", {"url_domain": self._get_domain(input_data.url)})

        try:
            # Step 1: 入力検証
            self.validate(input_data)
            url = input_data.url
            assert url is not None  # validate() ensures url is not None

            # Step 2: URLセキュリティチェック
            self._check_url_security(url)

            # Step 3: コンテンツ取得
            html_content, url_metadata = await self._fetch_content(url)

            # Step 4: HTMLパース・本文抽出
            main_content, headings, links, images = self._extract_content(html_content)

            if not main_content.strip():
                raise URLContentExtractionError(url, "本文を抽出できませんでした")

            # コンテンツサイズ制限
            if len(main_content) > MAX_EXTRACTED_TEXT_LENGTH:
                main_content = main_content[:MAX_EXTRACTED_TEXT_LENGTH]

            # Step 5: URLタイプ判定
            url_type = self._determine_url_type(url, url_metadata, main_content)

            # Step 6: LLMで分析
            summary, key_points, analysis_entities = await self._analyze_content(
                content=main_content,
                url_metadata=url_metadata,
                instruction=input_data.instruction,
            )

            # Step 7: 会社文脈との関連付け
            relevance, relevance_score = await self._find_company_relevance(
                content=main_content,
                summary=summary,
                context=input_data.brain_context,
            )

            # Step 8: エンティティ抽出（LLM + パターンマッチング）
            pattern_entities = self._extract_entities_from_text(main_content)
            entities = self._merge_url_entities(analysis_entities, pattern_entities)

            # Step 9: 確信度計算
            confidence = self._calculate_url_confidence(url_metadata, main_content)
            confidence_level = self._calculate_confidence_level(confidence)

            # Step 10: メタデータ更新
            metadata.api_calls_count = 1  # 分析LLM
            if relevance:
                metadata.api_calls_count += 1  # 関連性LLM

            # Step 11: 結果構築
            url_result = URLAnalysisResult(
                success=True,
                url_type=url_type,
                url_metadata=url_metadata,
                main_content=main_content,
                headings=headings,
                links=links[:50],  # リンクは最大50件
                images=images[:20],  # 画像は最大20件
                entities=entities,
                summary=summary,
                key_points=key_points,
                relevance_to_company=relevance,
                relevance_score=relevance_score,
                overall_confidence=confidence,
                confidence_level=confidence_level,
                metadata=self._complete_processing_metadata(metadata, success=True),
            )

            # ログ
            self._log_processing_complete(
                success=True,
                processing_time_ms=url_result.metadata.processing_time_ms,
                details={
                    "url_type": url_type.value,
                    "content_length": len(main_content),
                    "entities_count": len(entities),
                },
            )

            # 処理ログ保存
            await self._save_processing_log(
                metadata=url_result.metadata,
                input_hash=None,  # URLはハッシュ不要
                output_summary=summary[:200] if summary else None,
            )

            return MultimodalOutput(
                success=True,
                input_type=InputType.URL,
                url_result=url_result,
                summary=summary,
                extracted_text=main_content,
                entities=entities,
                metadata=url_result.metadata,
            )

        except Exception as e:
            # エラーハンドリング
            error_message = str(e)
            error_code = getattr(e, 'error_code', 'UNKNOWN_ERROR')

            self._log_processing_complete(
                success=False,
                processing_time_ms=int((datetime.now() - metadata.started_at).total_seconds() * 1000),
                details={"error": error_message},
            )

            return MultimodalOutput(
                success=False,
                input_type=InputType.URL,
                error_message=error_message,
                error_code=error_code,
                metadata=self._complete_processing_metadata(
                    metadata,
                    success=False,
                    error_message=error_message,
                    error_code=error_code,
                ),
            )

    def validate(self, input_data: MultimodalInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ

        Raises:
            ValidationError: 検証に失敗した場合
        """
        # 組織ID検証
        self._validate_organization_id()

        # 入力タイプ検証
        if input_data.input_type != InputType.URL:
            raise ValidationError(
                message=f"Invalid input type: expected URL, got {input_data.input_type.value}",
                field="input_type",
                input_type=InputType.URL,
            )

        # URL存在検証
        if not input_data.url:
            raise ValidationError(
                message="URL must be provided",
                field="url",
                input_type=InputType.URL,
            )

        # URL形式検証
        try:
            parsed = urlparse(input_data.url)
            if not parsed.scheme or not parsed.netloc:
                raise URLParseError(input_data.url)
            if parsed.scheme.lower() not in SUPPORTED_URL_PROTOCOLS:
                raise ValidationError(
                    message=f"Unsupported protocol: {parsed.scheme}",
                    field="url",
                    input_type=InputType.URL,
                )
        except Exception as e:
            if isinstance(e, (ValidationError, URLParseError)):
                raise
            raise URLParseError(input_data.url)

    # =========================================================================
    # セキュリティチェック
    # =========================================================================

    def _check_url_security(self, url: str) -> None:
        """URLセキュリティチェック"""
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()

        # ポート除去
        if ':' in hostname:
            hostname = hostname.split(':')[0]

        # ブロックドメインチェック
        for blocked in BLOCKED_DOMAINS:
            if hostname == blocked or hostname.endswith('.' + blocked):
                raise URLBlockedError(url, f"ブロックされたドメイン: {blocked}")

        # IPアドレスチェック
        try:
            # DNS解決
            ip = socket.gethostbyname(hostname)

            # プライベートIPチェック
            for prefix in BLOCKED_IP_PREFIXES:
                if ip.startswith(prefix):
                    raise URLBlockedError(url, "プライベートIPアドレス")

            # 追加チェック
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                raise URLBlockedError(url, "プライベート/ループバックIP")

        except socket.gaierror:
            # DNS解決失敗は許容（存在しないドメインは後でエラー）
            pass
        except URLBlockedError:
            raise
        except Exception as e:
            logger.warning(f"IP check failed for {hostname}: {e}")

    def _get_domain(self, url: Optional[str]) -> str:
        """URLからドメインを取得"""
        if not url:
            return "unknown"
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"

    # =========================================================================
    # コンテンツ取得
    # =========================================================================

    async def _fetch_content(self, url: str) -> Tuple[str, URLMetadata]:
        """URLからコンテンツを取得"""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=URL_FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                response = await client.get(url, headers=headers)

                # ステータスコードチェック
                if response.status_code >= 400:
                    raise URLFetchError(url, status_code=response.status_code)

                # コンテンツサイズチェック
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_URL_CONTENT_SIZE_BYTES:
                    raise URLFetchError(url, reason="コンテンツが大きすぎます")

                html_content = response.text

                # 実際のサイズチェック
                if len(html_content.encode()) > MAX_URL_CONTENT_SIZE_BYTES:
                    html_content = html_content[:MAX_URL_CONTENT_SIZE_BYTES // 2]

                # メタデータ構築
                url_metadata = URLMetadata(
                    url=url,
                    final_url=str(response.url),
                    domain=urlparse(str(response.url)).netloc,
                    content_type=response.headers.get("content-type"),
                    content_length=len(html_content),
                    status_code=response.status_code,
                    redirected=str(response.url) != url,
                    redirect_count=len(response.history),
                )

                return html_content, url_metadata

        except httpx.TimeoutException:
            raise URLTimeoutError(url, URL_FETCH_TIMEOUT_SECONDS)
        except httpx.HTTPError as e:
            raise URLFetchError(url, reason=str(e))
        except URLProcessingError:
            raise
        except Exception as e:
            raise URLFetchError(url, reason=str(e))

    # =========================================================================
    # HTMLパース
    # =========================================================================

    def _extract_content(
        self,
        html: str,
    ) -> Tuple[str, List[str], List[Dict[str, str]], List[Dict[str, str]]]:
        """HTMLからコンテンツを抽出"""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, 'html.parser')

            # 不要な要素を削除
            for tag in HTML_EXCLUDE_TAGS:
                for element in soup.find_all(tag):
                    element.decompose()

            # メタデータ抽出
            self._extract_html_metadata(soup)

            # 本文抽出
            main_content = self._extract_main_content(soup)

            # 見出し抽出
            headings = self._extract_headings(soup)

            # リンク抽出
            links = self._extract_links(soup)

            # 画像抽出
            images = self._extract_images(soup)

            return main_content, headings, links, images

        except ImportError:
            logger.warning("BeautifulSoup not available, using basic extraction")
            return self._extract_content_basic(html)

    def _extract_content_basic(
        self,
        html: str,
    ) -> Tuple[str, List[str], List[Dict[str, str]], List[Dict[str, str]]]:
        """基本的なHTMLパース（BeautifulSoupなし）"""
        # タグを削除
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text, [], [], []

    def _extract_html_metadata(self, soup) -> Dict[str, str]:
        """HTMLメタデータを抽出"""
        metadata = {}

        # タイトル
        title = soup.find('title')
        if title:
            metadata['title'] = title.get_text(strip=True)

        # OGタグなど
        for name, selector in HTML_METADATA_TAGS.items():
            if '[' in selector:
                # 属性セレクター
                tag = soup.select_one(selector)
            else:
                tag = soup.find(selector)

            if tag:
                content = tag.get('content') or tag.get_text(strip=True)
                if content:
                    metadata[name] = content

        return metadata

    def _extract_main_content(self, soup) -> str:
        """本文を抽出"""
        # 優先的に探す要素
        main_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.post-content',
            '.article-content',
            '.entry-content',
            '#content',
            '#main',
        ]

        for selector in main_selectors:
            main = soup.select_one(selector)
            if main:
                text = str(main.get_text(separator='\n', strip=True))
                if len(text) > 200:  # 有意なコンテンツ
                    return text

        # フォールバック: body全体
        body = soup.find('body')
        if body:
            return str(body.get_text(separator='\n', strip=True))

        return str(soup.get_text(separator='\n', strip=True))

    def _extract_headings(self, soup) -> List[str]:
        """見出しを抽出"""
        headings = []
        for tag in ['h1', 'h2', 'h3']:
            for h in soup.find_all(tag):
                text = h.get_text(strip=True)
                if text and len(text) < 200:
                    headings.append(text)
        return headings[:30]

    def _extract_links(self, soup) -> List[Dict[str, str]]:
        """リンクを抽出"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)
            if href and text and not href.startswith('#'):
                links.append({
                    "text": text[:100],
                    "href": href,
                })
        return links

    def _extract_images(self, soup) -> List[Dict[str, str]]:
        """画像を抽出"""
        images = []
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            alt = img.get('alt', '')
            if src:
                images.append({
                    "src": src,
                    "alt": alt[:100] if alt else "",
                })
        return images

    # =========================================================================
    # コンテンツ分析
    # =========================================================================

    def _determine_url_type(
        self,
        url: str,
        metadata: URLMetadata,
        content: str,
    ) -> URLType:
        """URLタイプを判定"""
        domain = metadata.domain.lower()
        url_lower = url.lower()

        # ドメインベースの判定
        news_domains = ['news', 'nikkei', 'asahi', 'yomiuri', 'mainichi', 'nhk']
        blog_domains = ['blog', 'note.com', 'medium.com', 'qiita.com', 'zenn.dev']
        video_domains = ['youtube', 'vimeo', 'dailymotion']
        social_domains = ['twitter', 'facebook', 'linkedin', 'instagram']
        doc_domains = ['notion', 'confluence', 'docs.google']

        for nd in news_domains:
            if nd in domain:
                return URLType.NEWS

        for bd in blog_domains:
            if bd in domain:
                return URLType.BLOG

        for vd in video_domains:
            if vd in domain:
                return URLType.VIDEO

        for sd in social_domains:
            if sd in domain:
                return URLType.SOCIAL

        for dd in doc_domains:
            if dd in domain:
                return URLType.DOCUMENT

        # コンテンツベースの判定
        if '/news/' in url_lower or '/article/' in url_lower:
            return URLType.NEWS
        if '/blog/' in url_lower or '/post/' in url_lower:
            return URLType.BLOG

        return URLType.WEBPAGE

    async def _analyze_content(
        self,
        content: str,
        url_metadata: URLMetadata,
        instruction: Optional[str] = None,
    ) -> Tuple[str, List[str], List[ExtractedEntity]]:
        """LLMでコンテンツを分析"""
        prompt = self._get_url_analysis_prompt(content, instruction)

        try:
            # テキスト分析用にVision APIを使用（画像なし）
            # 本来はModel Orchestratorを使うべきだが、現時点では直接呼び出し
            result = await self._call_text_llm(prompt)

            parsed = self._parse_analysis_result(result)

            summary = parsed.get("summary", "")
            if len(summary) > MAX_SUMMARY_LENGTH:
                summary = summary[:MAX_SUMMARY_LENGTH]

            key_points = parsed.get("key_points", [])

            entities = []
            for e in parsed.get("entities", []):
                entities.append(ExtractedEntity(
                    entity_type=e.get("type", "other"),
                    value=e.get("value", ""),
                    confidence=0.8,
                ))

            return summary, key_points, entities

        except Exception as e:
            logger.warning(f"Content analysis failed: {e}")
            # フォールバック
            sentences = re.split(r'[。．\n]', content)
            summary = "。".join(sentences[:3]) + "。"
            return summary[:MAX_SUMMARY_LENGTH], [], []

    async def _call_text_llm(self, prompt: str) -> str:
        """テキストLLMを呼び出す"""
        import os
        import httpx

        api_key = self._api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise URLProcessingError("API key not configured", url="")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2000,
            "temperature": 0.3,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"])

    def _parse_analysis_result(self, content: str) -> Dict[str, Any]:
        """分析結果をパース"""
        try:
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                parsed: Dict[str, Any] = json.loads(json_match.group(1))
                return parsed

            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1:
                parsed2: Dict[str, Any] = json.loads(content[start:end + 1])
                return parsed2

        except Exception:
            pass

        return {"summary": content[:500], "key_points": []}

    async def _find_company_relevance(
        self,
        content: str,
        summary: str,
        context: Optional[Any] = None,
    ) -> Tuple[Optional[str], float]:
        """会社との関連性を判定"""
        # TODO: BrainContextから会社情報を取得して関連性を判定
        # 現時点では簡易実装
        return None, 0.0

    def _merge_url_entities(
        self,
        analysis_entities: List[ExtractedEntity],
        pattern_entities: List[ExtractedEntity],
    ) -> List[ExtractedEntity]:
        """エンティティをマージ"""
        entities = list(analysis_entities)
        existing_values = {e.value for e in entities}

        for pe in pattern_entities:
            if pe.value not in existing_values:
                entities.append(pe)
                existing_values.add(pe.value)

        return entities

    def _calculate_url_confidence(
        self,
        metadata: URLMetadata,
        content: str,
    ) -> float:
        """URLの確信度を計算"""
        confidence = 0.7  # ベース

        # コンテンツ量による調整
        if len(content) > 5000:
            confidence += 0.1
        elif len(content) < 500:
            confidence -= 0.2

        # リダイレクトによる調整
        if metadata.redirect_count > 2:
            confidence -= 0.1

        return max(0.1, min(1.0, confidence))


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_url_processor(
    pool,
    organization_id: str,
    api_key: Optional[str] = None,
) -> URLProcessor:
    """
    URLProcessorを作成するファクトリー関数

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key

    Returns:
        URLProcessor
    """
    return URLProcessor(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
    )
