"""
Google Workspace handlers for CapabilityBridge.

Google Sheets（読み込み・書き込み・作成）および
Google Slides（読み込み・作成）のハンドラー群。
"""

import logging
from typing import Any, Dict

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


async def handle_read_spreadsheet(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    スプレッドシート読み込みハンドラー

    Args:
        params: パラメータ
            - spreadsheet_id: スプレッドシートID
            - range: 読み込み範囲（例: "Sheet1!A1:D10"）

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import GoogleSheetsClient

        spreadsheet_id = params.get("spreadsheet_id", "")
        range_name = params.get("range", "")

        if not spreadsheet_id:
            return HandlerResult(
                success=False,
                message="スプレッドシートのIDを教えてほしいウル🐺",
            )

        client = GoogleSheetsClient()
        data = await client.read_sheet(
            spreadsheet_id=spreadsheet_id,
            range_notation=range_name or "Sheet1",
        )

        if data:
            markdown = client.to_markdown_table(data)
            message = f"スプレッドシートの内容ウル！🐺\n\n{markdown}"
            return HandlerResult(
                success=True,
                message=message,
                data={"rows": len(data), "data": data},
            )
        else:
            return HandlerResult(
                success=True,
                message="スプレッドシートにデータがなかったウル🐺",
                data={"rows": 0, "data": []},
            )

    except ImportError:
        return HandlerResult(
            success=False,
            message="スプレッドシート機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[GoogleWorkspace] Read spreadsheet failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="スプレッドシートの読み込みに失敗したウル🐺",
        )


async def handle_write_spreadsheet(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    スプレッドシート書き込みハンドラー

    Args:
        params: パラメータ
            - spreadsheet_id: スプレッドシートID
            - range: 書き込み範囲
            - data: 書き込みデータ（2次元配列）

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import GoogleSheetsClient

        spreadsheet_id = params.get("spreadsheet_id", "")
        range_name = params.get("range", "Sheet1!A1")
        data = params.get("data", [])

        if not spreadsheet_id:
            return HandlerResult(
                success=False,
                message="スプレッドシートのIDを教えてほしいウル🐺",
            )

        if not data:
            return HandlerResult(
                success=False,
                message="書き込むデータを教えてほしいウル🐺",
            )

        client = GoogleSheetsClient()
        result = await client.write_sheet(
            spreadsheet_id=spreadsheet_id,
            range_notation=range_name,
            values=data,
        )

        return HandlerResult(
            success=True,
            message=f"スプレッドシートに書き込んだウル！🐺\n更新セル数: {result.get('updatedCells', 0)}",
            data=result,
        )

    except ImportError:
        return HandlerResult(
            success=False,
            message="スプレッドシート機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[GoogleWorkspace] Write spreadsheet failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="スプレッドシートへの書き込みに失敗したウル🐺",
        )


async def handle_create_spreadsheet(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    スプレッドシート作成ハンドラー

    Args:
        params: パラメータ
            - title: スプレッドシート名
            - sheets: シート名のリスト（オプション）

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import GoogleSheetsClient

        title = params.get("title", "新規スプレッドシート")
        sheets = params.get("sheets", ["Sheet1"])

        client = GoogleSheetsClient()
        result = await client.create_spreadsheet(
            title=title,
            sheet_names=sheets,
        )

        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{result['spreadsheet_id']}"
        return HandlerResult(
            success=True,
            message=f"スプレッドシートを作成したウル！🐺\n\n📊 {spreadsheet_url}",
            data={
                "spreadsheet_id": result["spreadsheet_id"],
                "url": spreadsheet_url,
            },
        )

    except ImportError:
        return HandlerResult(
            success=False,
            message="スプレッドシート機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[GoogleWorkspace] Create spreadsheet failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="スプレッドシートの作成に失敗したウル🐺",
        )


async def handle_read_presentation(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    プレゼンテーション読み込みハンドラー

    Args:
        params: パラメータ
            - presentation_id: プレゼンテーションID

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import GoogleSlidesClient

        presentation_id = params.get("presentation_id", "")

        if not presentation_id:
            return HandlerResult(
                success=False,
                message="プレゼンテーションのIDを教えてほしいウル🐺",
            )

        client = GoogleSlidesClient()
        info = await client.get_presentation_info(presentation_id)
        content = await client.get_presentation_content(presentation_id)

        markdown = client.to_markdown(content)
        message = f"📽️ **{info.get('title', 'プレゼンテーション')}**\n\n"
        message += f"スライド数: {info.get('slides_count', 0)}\n\n"
        message += f"{markdown}"

        return HandlerResult(
            success=True,
            message=message,
            data={
                "title": info.get("title"),
                "slides_count": info.get("slides_count"),
                "content": content,
            },
        )

    except ImportError:
        return HandlerResult(
            success=False,
            message="プレゼンテーション機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[GoogleWorkspace] Read presentation failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="プレゼンテーションの読み込みに失敗したウル🐺",
        )


async def handle_create_presentation(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    プレゼンテーション作成ハンドラー

    Args:
        params: パラメータ
            - title: プレゼンテーション名
            - slides: スライド内容のリスト

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.generation import GoogleSlidesClient

        title = params.get("title", "新規プレゼンテーション")
        slides = params.get("slides", [])

        client = GoogleSlidesClient()

        result = await client.create_presentation(title=title)
        presentation_id = result["presentationId"]

        for slide_data in slides:
            slide_title = slide_data.get("title", "")
            slide_body = slide_data.get("body", "")
            if slide_title or slide_body:
                await client.add_slide(
                    presentation_id=presentation_id,
                    layout="TITLE_AND_BODY",
                    title=slide_title,
                    body=slide_body,
                )

        presentation_url = f"https://docs.google.com/presentation/d/{presentation_id}"
        return HandlerResult(
            success=True,
            message=f"プレゼンテーションを作成したウル！🐺\n\n📽️ {presentation_url}",
            data={
                "presentation_id": presentation_id,
                "url": presentation_url,
            },
        )

    except ImportError:
        return HandlerResult(
            success=False,
            message="プレゼンテーション機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[GoogleWorkspace] Create presentation failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="プレゼンテーションの作成に失敗したウル🐺",
        )
