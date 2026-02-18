"""
Generation handlers for CapabilityBridge.

文書生成・画像生成・動画生成・ディープリサーチのハンドラー群。
各関数はCapabilityBridgeインスタンスのpool/org_idを受け取り、
capability_bridge.pyから委譲される。
"""

import logging
from typing import Any, Dict
from uuid import UUID

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


def _parse_org_uuid(org_id: str) -> UUID:
    """org_id文字列をUUIDに変換するヘルパー"""
    if isinstance(org_id, UUID):
        return org_id
    try:
        return UUID(org_id)
    except (ValueError, TypeError, AttributeError):
        import uuid as uuid_mod
        return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(org_id))


def _safe_parse_uuid(value) -> "UUID | None":
    """文字列をUUIDに安全に変換するヘルパー"""
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        import uuid as uuid_mod
        return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(value))


def _get_google_docs_credentials() -> "Dict[str, Any] | None":
    """Google Docs専用SAの認証情報をSecret Managerから取得"""
    try:
        from google.cloud import secretmanager
        import json as _json

        client = secretmanager.SecretManagerServiceClient()
        name = "projects/soulkun-production/secrets/google-docs-sa-key/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return _json.loads(response.payload.data.decode("utf-8"))
    except Exception as e:
        logger.warning("Google Docs SA key not available, using ADC: %s", str(e)[:100])
        return None


async def handle_document_generation(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    文書生成ハンドラー

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ
            - document_type: 文書タイプ（report/summary/proposal）
            - topic: トピック
            - outline: アウトライン（オプション）
            - output_format: 出力形式（google_docs/markdown）

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import DocumentGenerator
        from lib.capabilities.generation.models import (
            DocumentRequest,
            GenerationInput,
        )
        from lib.capabilities.generation.constants import (
            DocumentType,
            GenerationType,
            OutputFormat,
        )

        document_type_str = params.get("document_type", "report")
        topic = params.get("topic", "")
        outline = params.get("outline")
        output_format_str = params.get("output_format", "google_docs")

        if not topic:
            return HandlerResult(
                success=False,
                message="何について文書を作成すればいいか教えてほしいウル🐺",
            )

        org_uuid = _parse_org_uuid(org_id)

        # 文書タイプのマッピング
        doc_type_map: Dict[str, DocumentType] = {
            "report": DocumentType.REPORT,
            "summary": DocumentType.SUMMARY,
            "proposal": DocumentType.PROPOSAL,
            "minutes": DocumentType.MINUTES,
            "manual": DocumentType.MANUAL,
        }
        doc_type = doc_type_map.get(document_type_str, DocumentType.REPORT)

        # 出力形式のマッピング
        format_map: Dict[str, OutputFormat] = {
            "google_docs": OutputFormat.GOOGLE_DOCS,
            "markdown": OutputFormat.MARKDOWN,
        }
        out_format = format_map.get(output_format_str, OutputFormat.GOOGLE_DOCS)

        google_creds_json = _get_google_docs_credentials()

        generator = DocumentGenerator(
            pool=pool,
            organization_id=org_uuid,
            google_credentials_json=google_creds_json,
        )

        instruction = topic
        if outline:
            instruction = f"{topic}\n\nアウトライン:\n{outline}"
        doc_request = DocumentRequest(
            title=topic,
            organization_id=org_uuid,
            document_type=doc_type,
            output_format=out_format,
            instruction=instruction,
            require_confirmation=False,
        )

        result = await generator.generate(GenerationInput(
            generation_type=GenerationType.DOCUMENT,
            organization_id=org_uuid,
            document_request=doc_request,
        ))

        if result.success:
            message = "文書を作成したウル！🐺\n\n"
            doc_result = result.document_result
            doc_url = doc_result.document_url if doc_result else None
            doc_id = doc_result.document_id if doc_result else None
            if doc_url:
                message += f"📄 {doc_url}"
            return HandlerResult(
                success=True,
                message=message,
                data={"document_url": doc_url, "document_id": doc_id},
            )
        else:
            return HandlerResult(
                success=False,
                message=f"文書の作成に失敗したウル🐺 {result.error_message}",
            )

    except ImportError:
        return HandlerResult(
            success=False,
            message="文書生成機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[Generation] Document generation failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="文書の作成中にエラーが発生したウル🐺",
        )


async def handle_image_generation(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    画像生成ハンドラー

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ
            - prompt: 画像の説明
            - style: スタイル（オプション）
            - size: サイズ（オプション）

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import ImageGenerator
        from lib.capabilities.generation.models import (
            ImageRequest,
            GenerationInput,
        )
        from lib.capabilities.generation.constants import GenerationType

        prompt = params.get("prompt", "")
        style = params.get("style")
        size = params.get("size", "1024x1024")

        if not prompt:
            return HandlerResult(
                success=False,
                message="どんな画像を作ればいいか教えてほしいウル🐺",
            )

        org_uuid = _parse_org_uuid(org_id)

        generator = ImageGenerator(
            pool=pool,
            organization_id=org_uuid,
        )

        from lib.capabilities.generation.constants import ImageStyle, ImageSize

        style_map: Dict[str, ImageStyle] = {
            "vivid": ImageStyle.VIVID,
            "natural": ImageStyle.NATURAL,
            "anime": ImageStyle.ANIME,
            "realistic": ImageStyle.PHOTOREALISTIC,
            "photorealistic": ImageStyle.PHOTOREALISTIC,
            "illustration": ImageStyle.ILLUSTRATION,
            "minimalist": ImageStyle.MINIMALIST,
            "corporate": ImageStyle.CORPORATE,
        }
        size_map: Dict[str, ImageSize] = {
            "1024x1024": ImageSize.SQUARE_1024,
            "1792x1024": ImageSize.LANDSCAPE_1792,
            "1024x1792": ImageSize.PORTRAIT_1024,
        }

        image_request = ImageRequest(
            organization_id=org_uuid,
            prompt=prompt,
            style=style_map.get(style, ImageStyle.VIVID) if style else ImageStyle.VIVID,
            size=size_map.get(size, ImageSize.SQUARE_1024),
            send_to_chatwork=True,
            chatwork_room_id=room_id,
        )

        result = await generator.generate(GenerationInput(
            generation_type=GenerationType.IMAGE,
            organization_id=org_uuid,
            image_request=image_request,
        ))

        if result.success:
            message = "画像を作成したウル！🐺\n\n"
            img_result = result.image_result
            img_url = img_result.image_url if img_result else None
            if img_url:
                message += f"🖼️ {img_url}"
            return HandlerResult(
                success=True,
                message=message,
                data={"image_url": img_url},
            )
        else:
            return HandlerResult(
                success=False,
                message=f"画像の作成に失敗したウル🐺 {result.error_message}",
            )

    except ImportError:
        return HandlerResult(
            success=False,
            message="画像生成機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[Generation] Image generation failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="画像の作成中にエラーが発生したウル🐺",
        )


async def handle_video_generation(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    動画生成ハンドラー

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ
            - prompt: 動画の説明
            - duration: 長さ（秒）
            - style: スタイル

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import VideoGenerator
        from lib.capabilities.generation.models import (
            VideoRequest,
            GenerationInput,
        )
        from lib.capabilities.generation.constants import GenerationType

        prompt = params.get("prompt", "")
        duration = params.get("duration", 5)

        if not prompt:
            return HandlerResult(
                success=False,
                message="どんな動画を作ればいいか教えてほしいウル🐺",
            )

        org_uuid = _parse_org_uuid(org_id)

        generator = VideoGenerator(
            pool=pool,
            organization_id=org_uuid,
        )

        from lib.capabilities.generation.constants import VideoDuration

        duration_map: Dict[int, VideoDuration] = {
            5: VideoDuration.SHORT_5S,
            10: VideoDuration.STANDARD_10S,
        }

        video_request = VideoRequest(
            organization_id=org_uuid,
            prompt=prompt,
            duration=duration_map.get(int(duration), VideoDuration.SHORT_5S),
        )

        result = await generator.generate(GenerationInput(
            generation_type=GenerationType.VIDEO,
            organization_id=org_uuid,
            video_request=video_request,
        ))

        if result.success:
            message = "動画を作成したウル！🐺\n\n"
            vid_result = result.video_result
            vid_url = vid_result.video_url if vid_result else None
            if vid_url:
                message += f"🎬 {vid_url}"
            return HandlerResult(
                success=True,
                message=message,
                data={"video_url": vid_url},
            )
        else:
            return HandlerResult(
                success=False,
                message=f"動画の作成に失敗したウル🐺 {result.error_message}",
            )

    except ImportError:
        return HandlerResult(
            success=False,
            message="動画生成機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[Generation] Video generation failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="動画の作成中にエラーが発生したウル🐺",
        )


async def handle_deep_research(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    ディープリサーチハンドラー

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ
            - query: 調査クエリ
            - depth: 調査深度 (quick/standard/deep/comprehensive)
            - research_type: 調査タイプ (general/competitor/market/technology)

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import (
            ResearchEngine,
            ResearchRequest,
            ResearchDepth,
            ResearchType,
            GenerationInput,
            GenerationType,
        )

        query = params.get("query", "")
        depth_str = params.get("depth", "standard")
        research_type_str = params.get("research_type", "general")

        if not query:
            return HandlerResult(
                success=False,
                message="何について調べればいいか教えてほしいウル🐺",
            )

        depth_map = {
            "quick": ResearchDepth.QUICK,
            "standard": ResearchDepth.STANDARD,
            "deep": ResearchDepth.DEEP,
            "comprehensive": ResearchDepth.COMPREHENSIVE,
        }
        depth = depth_map.get(depth_str, ResearchDepth.STANDARD)

        type_map = {
            "general": ResearchType.TOPIC,
            "competitor": ResearchType.COMPETITOR,
            "market": ResearchType.MARKET,
            "technology": ResearchType.TECHNOLOGY,
        }
        research_type = type_map.get(research_type_str, ResearchType.TOPIC)

        org_uuid = _parse_org_uuid(org_id)

        engine = ResearchEngine(
            pool=pool,
            organization_id=org_uuid,
        )

        request = ResearchRequest(
            organization_id=org_uuid,
            query=query,
            depth=depth,
            research_type=research_type,
            user_id=_safe_parse_uuid(account_id),
            chatwork_room_id=room_id,
            save_to_drive=True,
        )

        result = await engine.generate(GenerationInput(
            generation_type=GenerationType.RESEARCH,
            organization_id=org_uuid,
            research_request=request,
        ))

        if result.success and result.research_result:
            res = result.research_result
            message = "調査が完了したウル！🐺\n\n"
            message += f"📊 **調査結果: {query[:30]}...**\n\n"
            if res.executive_summary:
                message += f"**要約:**\n{res.executive_summary}\n\n"
            if res.key_findings:
                message += "**主な発見:**\n"
                for i, finding in enumerate(res.key_findings[:5], 1):
                    message += f"{i}. {finding}\n"
                message += "\n"
            if res.document_url:
                message += f"📄 詳細レポート: {res.document_url}\n"
            if res.actual_cost_jpy:
                message += f"\n💰 調査コスト: ¥{res.actual_cost_jpy:.0f}"

            return HandlerResult(
                success=True,
                message=message,
                data={
                    "document_url": res.document_url,
                    "sources_count": res.sources_count,
                    "cost_jpy": res.actual_cost_jpy,
                },
            )
        else:
            return HandlerResult(
                success=False,
                message="調査に失敗したウル🐺",
            )

    except ImportError:
        return HandlerResult(
            success=False,
            message="ディープリサーチ機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[Generation] Deep research failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="調査中にエラーが発生したウル🐺",
        )
