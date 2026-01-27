# lib/capabilities/multimodal/image_processor.py
"""
Phase M1: Multimodal入力能力 - 画像処理プロセッサー

このモジュールは、画像の解析・テキスト抽出機能を提供します。

ユースケース:
- 領収書の読み取り → 経費精算
- 名刺の読み取り → 連絡先登録
- 設計図・図面の分析 → レビュー支援
- スクリーンショットの理解 → 問い合わせ対応

設計書: docs/20_next_generation_capabilities.md セクション5.3
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
import logging
import io
import json
import re

from .constants import (
    InputType,
    ProcessingStatus,
    ImageType,
    ContentConfidenceLevel,
    SUPPORTED_IMAGE_FORMATS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_IMAGE_DIMENSION,
)
from .exceptions import (
    ValidationError,
    UnsupportedFormatError,
    FileTooLargeError,
    ImageProcessingError,
    ImageDecodeError,
    ImageDimensionError,
    VisionAPIError,
    wrap_multimodal_error,
)
from .models import (
    ProcessingMetadata,
    ExtractedEntity,
    ImageMetadata,
    ImageAnalysisResult,
    MultimodalInput,
    MultimodalOutput,
)
from .base import BaseMultimodalProcessor


logger = logging.getLogger(__name__)


# =============================================================================
# ImageProcessor
# =============================================================================


class ImageProcessor(BaseMultimodalProcessor):
    """
    画像処理プロセッサー

    画像を解析し、テキスト抽出・構造化データ抽出を行う。

    使用例:
        processor = ImageProcessor(pool, org_id)
        result = await processor.process(MultimodalInput(
            input_type=InputType.IMAGE,
            organization_id=org_id,
            image_data=image_bytes,
            instruction="領収書の内容を読み取って",
        ))
        print(result.image_result.structured_data)
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
            input_type=InputType.IMAGE,
        )

    # =========================================================================
    # 公開API
    # =========================================================================

    @wrap_multimodal_error
    async def process(self, input_data: MultimodalInput) -> MultimodalOutput:
        """
        画像を処理

        処理フロー:
        1. 入力検証
        2. 画像メタデータ抽出
        3. Vision APIで解析
        4. エンティティ抽出
        5. 結果構築

        Args:
            input_data: 入力データ

        Returns:
            MultimodalOutput: 処理結果
        """
        # メタデータ初期化
        metadata = self._create_processing_metadata()
        self._log_processing_start("image")

        try:
            # Step 1: 入力検証
            self.validate(input_data)

            # 画像データ取得
            image_data = await self._get_image_data(input_data)

            # Step 2: 画像メタデータ抽出
            image_metadata = self._extract_image_metadata(image_data)
            logger.debug(
                f"Image metadata: {image_metadata.width}x{image_metadata.height}, "
                f"format={image_metadata.format}"
            )

            # Step 3: 画像サイズの検証
            self._validate_image_dimensions(image_metadata)

            # Step 4: 画像の前処理（必要に応じてリサイズ）
            processed_data = self._preprocess_image(image_data, image_metadata)

            # Step 5: Vision APIで解析
            vision_result = await self._analyze_with_vision_api(
                image_data=processed_data,
                instruction=input_data.instruction,
            )

            # Step 6: 結果をパース
            parsed_result = self._parse_vision_result(vision_result["content"])

            # Step 7: エンティティ抽出（Vision APIの結果 + パターンマッチング）
            entities = self._merge_entities(
                vision_entities=parsed_result.get("entities", []),
                extracted_text=parsed_result.get("extracted_text", ""),
            )

            # Step 8: 画像タイプ判定
            image_type = self._determine_image_type(parsed_result.get("image_type", "unknown"))

            # Step 9: 確信度計算
            confidence = parsed_result.get("confidence", 0.7)
            confidence_level = self._calculate_confidence_level(confidence)

            # Step 10: メタデータ更新
            metadata.model_used = vision_result.get("model")
            metadata.input_tokens = vision_result.get("input_tokens", 0)
            metadata.output_tokens = vision_result.get("output_tokens", 0)
            metadata.api_calls_count = 1

            # Step 11: 結果構築
            image_result = ImageAnalysisResult(
                success=True,
                image_type=image_type,
                description=parsed_result.get("description", ""),
                extracted_text=parsed_result.get("extracted_text"),
                text_confidence=parsed_result.get("text_confidence", confidence),
                entities=entities,
                structured_data=parsed_result.get("structured_data", {}),
                image_metadata=image_metadata,
                overall_confidence=confidence,
                confidence_level=confidence_level,
                metadata=self._complete_processing_metadata(metadata, success=True),
                summary_for_user=self._generate_user_summary(parsed_result, image_type),
            )

            # ログ
            self._log_processing_complete(
                success=True,
                processing_time_ms=image_result.metadata.processing_time_ms,
                details={
                    "image_type": image_type.value,
                    "entities_count": len(entities),
                },
            )

            # 処理ログ保存
            await self._save_processing_log(
                metadata=image_result.metadata,
                input_hash=self._compute_hash(image_data),
                output_summary=image_result.summary_for_user[:200],
            )

            return MultimodalOutput(
                success=True,
                input_type=InputType.IMAGE,
                image_result=image_result,
                summary=image_result.summary_for_user,
                extracted_text=image_result.extracted_text or "",
                entities=entities,
                metadata=image_result.metadata,
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
                input_type=InputType.IMAGE,
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
        if input_data.input_type != InputType.IMAGE:
            raise ValidationError(
                message=f"Invalid input type: expected IMAGE, got {input_data.input_type.value}",
                field="input_type",
                input_type=InputType.IMAGE,
            )

        # データ存在検証
        if input_data.image_data is None and input_data.file_path is None:
            raise ValidationError(
                message="Either image_data or file_path must be provided",
                field="image_data",
                input_type=InputType.IMAGE,
            )

        # ファイルサイズ検証（image_dataがある場合）
        if input_data.image_data:
            if len(input_data.image_data) > MAX_IMAGE_SIZE_BYTES:
                raise FileTooLargeError(
                    actual_size_bytes=len(input_data.image_data),
                    max_size_bytes=MAX_IMAGE_SIZE_BYTES,
                    input_type=InputType.IMAGE,
                )

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    async def _get_image_data(self, input_data: MultimodalInput) -> bytes:
        """画像データを取得"""
        if input_data.image_data:
            return input_data.image_data

        if input_data.file_path:
            try:
                with open(input_data.file_path, 'rb') as f:
                    data = f.read()

                # ファイルサイズ検証
                if len(data) > MAX_IMAGE_SIZE_BYTES:
                    raise FileTooLargeError(
                        actual_size_bytes=len(data),
                        max_size_bytes=MAX_IMAGE_SIZE_BYTES,
                        input_type=InputType.IMAGE,
                    )

                return data
            except IOError as e:
                raise ImageDecodeError(f"Failed to read image file: {e}")

        raise ValidationError(
            message="No image data provided",
            field="image_data",
            input_type=InputType.IMAGE,
        )

    def _extract_image_metadata(self, image_data: bytes) -> ImageMetadata:
        """画像メタデータを抽出"""
        try:
            from PIL import Image

            with io.BytesIO(image_data) as buffer:
                img = Image.open(buffer)

                metadata = ImageMetadata(
                    width=img.width,
                    height=img.height,
                    format=img.format.lower() if img.format else self._detect_format(image_data),
                    file_size_bytes=len(image_data),
                    color_mode=img.mode,
                    has_transparency=img.mode in ('RGBA', 'LA', 'P'),
                )

                # DPI
                if hasattr(img, 'info') and 'dpi' in img.info:
                    metadata.dpi = img.info['dpi']

                # EXIF
                if hasattr(img, '_getexif') and img._getexif():
                    try:
                        exif = img._getexif()
                        if exif:
                            metadata.exif_data = {k: v for k, v in exif.items() if isinstance(v, (str, int, float))}
                    except Exception:
                        pass

                return metadata

        except ImportError:
            # PILがない場合は最小限の情報
            logger.warning("PIL not available, using basic metadata extraction")
            return ImageMetadata(
                file_size_bytes=len(image_data),
                format=self._detect_format(image_data),
            )
        except Exception as e:
            raise ImageDecodeError(f"Failed to extract image metadata: {e}")

    def _detect_format(self, data: bytes) -> str:
        """画像フォーマットを検出"""
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "png"
        elif data[:2] == b'\xff\xd8':
            return "jpeg"
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            return "gif"
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "webp"
        elif data[:2] == b'BM':
            return "bmp"
        else:
            return "unknown"

    def _validate_image_dimensions(self, metadata: ImageMetadata) -> None:
        """画像サイズを検証"""
        if metadata.width > MAX_IMAGE_DIMENSION or metadata.height > MAX_IMAGE_DIMENSION:
            raise ImageDimensionError(
                width=metadata.width,
                height=metadata.height,
                max_dimension=MAX_IMAGE_DIMENSION,
            )

    def _preprocess_image(self, image_data: bytes, metadata: ImageMetadata) -> bytes:
        """
        画像を前処理

        - 大きすぎる画像はリサイズ
        - フォーマット変換（必要に応じて）
        """
        try:
            from PIL import Image

            # リサイズが必要かチェック
            max_dim = 2048  # Vision APIの推奨サイズ
            if metadata.width <= max_dim and metadata.height <= max_dim:
                return image_data

            # リサイズ
            with io.BytesIO(image_data) as buffer:
                img = Image.open(buffer)

                # アスペクト比を維持してリサイズ
                ratio = min(max_dim / metadata.width, max_dim / metadata.height)
                new_size = (int(metadata.width * ratio), int(metadata.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

                # 保存
                output = io.BytesIO()
                format_to_save = 'JPEG' if metadata.format.lower() in ('jpeg', 'jpg') else 'PNG'
                img.save(output, format=format_to_save, quality=85)
                return output.getvalue()

        except ImportError:
            # PILがない場合はそのまま返す
            return image_data
        except Exception as e:
            logger.warning(f"Image preprocessing failed, using original: {e}")
            return image_data

    async def _analyze_with_vision_api(
        self,
        image_data: bytes,
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Vision APIで画像を解析"""
        prompt = self._get_image_analysis_prompt(instruction)

        result = await self._vision_client.analyze_with_fallback(
            image_data=image_data,
            prompt=prompt,
        )

        return result

    def _parse_vision_result(self, content: str) -> Dict[str, Any]:
        """Vision APIの結果をパース"""
        try:
            # Step 1: コンテンツ全体がJSONの場合（最も一般的）
            content_stripped = content.strip()
            if content_stripped.startswith('{') and content_stripped.endswith('}'):
                try:
                    return json.loads(content_stripped)
                except json.JSONDecodeError:
                    pass

            # Step 2: Markdownコードブロック内のJSON
            json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Step 3: テキスト中に埋め込まれたJSON（最初の{から最後の}まで）
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    pass

            # Step 4: JSON抽出失敗時はテキストから情報を構築
            return {
                "image_type": "unknown",
                "description": content[:500],
                "extracted_text": self._extract_text_from_response(content),
                "entities": [],
                "structured_data": {},
                "confidence": 0.5,
            }

        except Exception as e:
            logger.warning(f"Failed to parse vision result: {e}")
            return {
                "image_type": "unknown",
                "description": content[:500] if content else "",
                "confidence": 0.3,
            }

    def _extract_text_from_response(self, content: str) -> Optional[str]:
        """レスポンスからテキストを抽出"""
        # 「テキスト:」や「OCR:」の後の内容を抽出
        patterns = [
            r'(?:テキスト|text|OCR)[:\s]+(.+?)(?:\n\n|\Z)',
            r'(?:抽出|extracted)[:\s]+(.+?)(?:\n\n|\Z)',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        return None

    def _merge_entities(
        self,
        vision_entities: List[Dict],
        extracted_text: str,
    ) -> List[ExtractedEntity]:
        """Vision APIとパターンマッチングのエンティティをマージ"""
        entities = []

        # Vision APIからのエンティティ
        for ve in vision_entities:
            entities.append(ExtractedEntity(
                entity_type=ve.get("type", "other"),
                value=ve.get("value", ""),
                confidence=ve.get("confidence", 0.8),
            ))

        # パターンマッチングからのエンティティ
        if extracted_text:
            pattern_entities = self._extract_entities_from_text(extracted_text)
            # 重複を避けてマージ
            existing_values = {e.value for e in entities}
            for pe in pattern_entities:
                if pe.value not in existing_values:
                    entities.append(pe)
                    existing_values.add(pe.value)

        return entities

    def _determine_image_type(self, type_str: str) -> ImageType:
        """画像タイプを判定"""
        type_str = type_str.lower()
        type_mapping = {
            "photo": ImageType.PHOTO,
            "photograph": ImageType.PHOTO,
            "screenshot": ImageType.SCREENSHOT,
            "document": ImageType.DOCUMENT,
            "receipt": ImageType.DOCUMENT,
            "invoice": ImageType.DOCUMENT,
            "business_card": ImageType.DOCUMENT,
            "名刺": ImageType.DOCUMENT,
            "領収書": ImageType.DOCUMENT,
            "diagram": ImageType.DIAGRAM,
            "flowchart": ImageType.DIAGRAM,
            "chart": ImageType.CHART,
            "graph": ImageType.CHART,
            "グラフ": ImageType.CHART,
        }
        return type_mapping.get(type_str, ImageType.UNKNOWN)

    def _generate_user_summary(
        self,
        parsed_result: Dict[str, Any],
        image_type: ImageType,
    ) -> str:
        """ユーザー向けサマリーを生成"""
        parts = []

        # 画像タイプに応じたサマリー
        if image_type == ImageType.DOCUMENT:
            if "structured_data" in parsed_result and parsed_result["structured_data"]:
                data = parsed_result["structured_data"]
                if "amount" in data:
                    parts.append(f"金額: {data['amount']}")
                if "date" in data:
                    parts.append(f"日付: {data['date']}")
                if "store_name" in data or "company" in data:
                    name = data.get("store_name") or data.get("company")
                    parts.append(f"名前: {name}")
        else:
            if parsed_result.get("description"):
                parts.append(parsed_result["description"][:200])

        if parsed_result.get("extracted_text"):
            text_preview = parsed_result["extracted_text"][:100]
            if len(parsed_result["extracted_text"]) > 100:
                text_preview += "..."
            parts.append(f"テキスト: {text_preview}")

        return "\n".join(parts) if parts else "画像を解析したウル"


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_image_processor(
    pool,
    organization_id: str,
    api_key: Optional[str] = None,
) -> ImageProcessor:
    """
    ImageProcessorを作成するファクトリー関数

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key

    Returns:
        ImageProcessor
    """
    return ImageProcessor(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
    )
