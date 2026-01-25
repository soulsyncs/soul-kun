"""
lib/document_processor.py のテスト

ドキュメント処理モジュールのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock

from lib.document_processor import (
    DocumentProcessor,
    TextChunker,
    Chunk,
    ExtractedDocument,
    extract_text,
    extract_with_metadata,
    TextExtractor,
    TextFileExtractor,
    HTMLExtractor,
)


class TestTextChunker:
    """TextChunker のテスト"""

    def test_basic_chunking(self):
        """基本的なチャンク分割"""
        chunker = TextChunker(chunk_size=100, chunk_overlap=20)
        text = "これはテスト文章です。" * 20  # 約200文字

        chunks = chunker.split(text)

        assert len(chunks) >= 2
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(c.char_count <= 100 + 50 for c in chunks)  # セパレータで多少変動

    def test_chunk_overlap(self):
        """チャンクのオーバーラップ"""
        chunker = TextChunker(chunk_size=50, chunk_overlap=10)
        text = "A" * 100

        chunks = chunker.split(text)

        # オーバーラップがある場合、連続するチャンクの終わりと始まりが重なる
        if len(chunks) >= 2:
            assert chunks[1].start_position < chunks[0].end_position

    def test_chunk_content_hash(self):
        """チャンクのハッシュ生成"""
        chunker = TextChunker(chunk_size=100, chunk_overlap=0)
        text = "テスト文章"

        chunks = chunker.split(text)

        assert len(chunks) == 1
        assert chunks[0].content_hash is not None
        assert len(chunks[0].content_hash) == 64  # SHA-256

    def test_chunk_index_sequential(self):
        """チャンクインデックスが連番"""
        chunker = TextChunker(chunk_size=50, chunk_overlap=10)
        text = "テスト" * 100

        chunks = chunker.split(text)

        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_empty_text(self):
        """空のテキスト"""
        chunker = TextChunker(chunk_size=100, chunk_overlap=20)

        chunks = chunker.split("")

        assert chunks == []

    def test_short_text_no_split(self):
        """短いテキストは分割されない"""
        chunker = TextChunker(chunk_size=100, chunk_overlap=20)
        text = "短いテキスト"

        chunks = chunker.split(text)

        assert len(chunks) == 1
        assert chunks[0].content == text


class TestTextFileExtractor:
    """TextFileExtractor のテスト"""

    def test_extract_text(self):
        """テキスト抽出"""
        extractor = TextFileExtractor()
        content = "テストテキスト\n2行目".encode('utf-8')

        result = extractor.extract(content)

        assert isinstance(result, str)
        assert result == "テストテキスト\n2行目"

    def test_extract_with_encoding(self):
        """エンコーディング処理"""
        extractor = TextFileExtractor()
        content = "日本語テスト".encode('shift_jis')

        result = extractor.extract(content)

        # UTF-8以外のエンコーディングも処理される
        assert result is not None
        assert "日本語テスト" in result


class TestHTMLExtractor:
    """HTMLExtractor のテスト"""

    def test_extract_text(self):
        """HTML からテキスト抽出"""
        extractor = HTMLExtractor()
        content = b"<html><body><h1>Title</h1><p>Content</p></body></html>"

        result = extractor.extract(content)

        assert isinstance(result, str)
        assert "Title" in result
        assert "Content" in result
        assert "<h1>" not in result  # タグは除去

    def test_extract_removes_scripts(self):
        """スクリプトタグが除去される"""
        extractor = HTMLExtractor()
        content = b"<html><script>alert('test')</script><p>Content</p></html>"

        result = extractor.extract(content)

        assert "alert" not in result
        assert "Content" in result


class TestDocumentProcessor:
    """DocumentProcessor のテスト"""

    def test_process_txt_file(self, sample_text_content):
        """TXTファイルの処理"""
        processor = DocumentProcessor(chunk_size=200, chunk_overlap=50)
        content = sample_text_content.encode('utf-8')

        doc, chunks = processor.process(content, "txt")

        assert isinstance(doc, ExtractedDocument)
        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_process_html_file(self):
        """HTMLファイルの処理"""
        processor = DocumentProcessor(chunk_size=200, chunk_overlap=50)
        content = b"<html><body><p>Test content here</p></body></html>"

        doc, chunks = processor.process(content, "html")

        assert "Test content" in doc.text

    def test_process_unsupported_format(self):
        """未サポート形式でエラー"""
        processor = DocumentProcessor()

        with pytest.raises(ValueError, match="サポートされていないファイル形式"):
            processor.process(b"content", "xyz")

    def test_supported_formats(self):
        """サポートされる形式"""
        from lib.document_processor import EXTRACTOR_MAP

        assert "pdf" in EXTRACTOR_MAP
        assert "docx" in EXTRACTOR_MAP
        assert "txt" in EXTRACTOR_MAP
        assert "md" in EXTRACTOR_MAP
        assert "html" in EXTRACTOR_MAP


class TestExtractText:
    """extract_text 便利関数のテスト"""

    def test_extract_text_function(self):
        """extract_text関数のテスト"""
        content = "テスト".encode('utf-8')

        text = extract_text(content, "txt")

        assert text == "テスト"


class TestExtractWithMetadata:
    """extract_with_metadata 便利関数のテスト"""

    def test_extract_with_metadata_function(self):
        """extract_with_metadata関数のテスト"""
        content = "テスト".encode('utf-8')

        doc = extract_with_metadata(content, "txt")

        assert isinstance(doc, ExtractedDocument)
        assert doc.text == "テスト"


class TestChunk:
    """Chunk データクラスのテスト"""

    def test_chunk_creation(self):
        """チャンク作成"""
        chunk = Chunk(
            content="テスト",
            index=0,
            start_position=0,
            end_position=4,
            char_count=4,
        )

        assert chunk.content == "テスト"
        assert chunk.index == 0
        assert chunk.char_count == 4

    def test_chunk_optional_fields(self):
        """オプションフィールド"""
        chunk = Chunk(
            content="テスト",
            index=0,
            start_position=0,
            end_position=4,
            char_count=4,
            page_number=1,
            section_title="第1章",
            section_hierarchy=["第1章", "1.1 概要"],
        )

        assert chunk.page_number == 1
        assert chunk.section_title == "第1章"
        assert len(chunk.section_hierarchy) == 2


class TestExtractedDocument:
    """ExtractedDocument データクラスのテスト"""

    def test_extracted_document_creation(self):
        """ドキュメント作成"""
        doc = ExtractedDocument(
            text="テスト",
            total_pages=1,
            metadata={"author": "test"}
        )

        assert doc.text == "テスト"
        assert doc.total_pages == 1
        assert doc.metadata["author"] == "test"
