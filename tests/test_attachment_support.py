"""Tests for image support functionality."""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.app import _build_document_attachments, _build_image_attachments
from bridge.utils.html import extract_image_urls


class TestExtractImageUrls:
    """Tests for extract_image_urls function."""

    def test_extract_single_image_url(self):
        """Should extract a single image URL from HTML."""
        html = '<div class="intercom-container"><img src="https://example.com/image.png"></div>'
        urls = extract_image_urls(html)
        assert urls == ["https://example.com/image.png"]

    def test_extract_multiple_image_urls(self):
        """Should extract multiple image URLs from HTML."""
        html = """
            <img src="https://example.com/image1.png">
            <img src="https://example.com/image2.jpg">
        """
        urls = extract_image_urls(html)
        assert urls == ["https://example.com/image1.png", "https://example.com/image2.jpg"]

    def test_extract_image_url_with_single_quotes(self):
        """Should extract image URL with single quotes."""
        html = "<img src='https://example.com/image.png'>"
        urls = extract_image_urls(html)
        assert urls == ["https://example.com/image.png"]

    def test_extract_image_url_with_attributes(self):
        """Should extract image URL when img tag has other attributes."""
        html = '<img class="photo" src="https://example.com/image.png" alt="Photo">'
        urls = extract_image_urls(html)
        assert urls == ["https://example.com/image.png"]

    def test_extract_intercom_cdn_url(self):
        """Should extract Intercom CDN image URL."""
        html = '<img src="https://downloads.intercomcdn.com/i/o/123456/image.jpeg">'
        urls = extract_image_urls(html)
        assert urls == ["https://downloads.intercomcdn.com/i/o/123456/image.jpeg"]

    def test_empty_html_returns_empty_list(self):
        """Should return empty list for empty HTML."""
        assert extract_image_urls("") == []
        assert extract_image_urls(None) == []

    def test_no_images_returns_empty_list(self):
        """Should return empty list when no images in HTML."""
        html = "<p>Hello world</p>"
        urls = extract_image_urls(html)
        assert urls == []


class TestBuildImageAttachments:
    """Tests for _build_image_attachments function."""

    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def sample_image_data(self):
        """Sample image data for testing."""
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # PNG header bytes

    @pytest.mark.asyncio
    async def test_build_png_attachment(self, mock_http_client, sample_image_data):
        """Should build attachment with base64 data and correct media type."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_image_data
        response.headers = {"content-type": "image/png"}
        mock_http_client.get = AsyncMock(return_value=response)

        urls = ["https://example.com/image.png"]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["type"] == "image"
        assert attachments[0]["media_type"] == "image/png"
        assert attachments[0]["data"] == base64.b64encode(sample_image_data).decode("utf-8")
        assert "url" not in attachments[0]

    @pytest.mark.asyncio
    async def test_build_jpeg_attachment(self, mock_http_client, sample_image_data):
        """Should build attachment with image/jpeg media type."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_image_data
        response.headers = {"content-type": "image/jpeg"}
        mock_http_client.get = AsyncMock(return_value=response)

        urls = ["https://example.com/image.jpg"]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_infers_media_type_from_url(self, mock_http_client, sample_image_data):
        """Should infer media type from URL if not in headers."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_image_data
        response.headers = {}  # No content-type header
        mock_http_client.get = AsyncMock(return_value=response)

        urls = ["https://example.com/image.gif"]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["media_type"] == "image/gif"

    @pytest.mark.asyncio
    async def test_handles_html_escaped_url(self, mock_http_client, sample_image_data):
        """Should unescape HTML entities in URL."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_image_data
        response.headers = {"content-type": "image/jpeg"}
        mock_http_client.get = AsyncMock(return_value=response)

        # URL with &amp; instead of &
        urls = ["https://example.com/image.jpg?a=1&amp;b=2"]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert len(attachments) == 1
        # Verify the URL was unescaped when calling get
        mock_http_client.get.assert_called_once_with("https://example.com/image.jpg?a=1&b=2")

    @pytest.mark.asyncio
    async def test_skips_failed_downloads(self, mock_http_client):
        """Should skip images that fail to download."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 404
        mock_http_client.get = AsyncMock(return_value=response)

        urls = ["https://example.com/notfound.png"]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert attachments == []

    @pytest.mark.asyncio
    async def test_handles_download_exception(self, mock_http_client):
        """Should handle exceptions during download."""
        mock_http_client.get = AsyncMock(side_effect=Exception("Network error"))

        urls = ["https://example.com/image.png"]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert attachments == []

    @pytest.mark.asyncio
    async def test_build_multiple_attachments(self, mock_http_client, sample_image_data):
        """Should build multiple attachments for multiple URLs."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_image_data
        response.headers = {"content-type": "image/png"}
        mock_http_client.get = AsyncMock(return_value=response)

        urls = [
            "https://example.com/image1.png",
            "https://example.com/image2.png",
        ]
        attachments = await _build_image_attachments(urls, mock_http_client)

        assert len(attachments) == 2

    @pytest.mark.asyncio
    async def test_build_empty_list(self, mock_http_client):
        """Should return empty list for empty URL list."""
        attachments = await _build_image_attachments([], mock_http_client)
        assert attachments == []


class TestBuildDocumentAttachments:
    """Tests for _build_document_attachments function."""

    @pytest.fixture
    def mock_http_client(self):
        """Create a mock HTTP client."""
        return MagicMock()

    @pytest.fixture
    def sample_pdf_data(self):
        """Sample PDF data for testing."""
        return b"%PDF-1.4 sample content"

    @pytest.mark.asyncio
    async def test_build_pdf_attachment(self, mock_http_client, sample_pdf_data):
        """Should build attachment with base64 data and correct media type."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_pdf_data
        response.headers = {"content-type": "application/pdf"}
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [
            {
                "url": "https://example.com/doc.pdf",
                "content_type": "application/pdf",
                "filename": "doc.pdf",
            }
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["type"] == "document"
        assert attachments[0]["media_type"] == "application/pdf"
        assert attachments[0]["data"] == base64.b64encode(sample_pdf_data).decode("utf-8")
        assert attachments[0]["filename"] == "doc.pdf"
        assert "url" not in attachments[0]

    @pytest.mark.asyncio
    async def test_build_txt_attachment(self, mock_http_client):
        """Should build attachment with text/plain media type."""
        txt_data = b"Hello world, this is a text file."
        response = MagicMock()
        response.is_success = True
        response.content = txt_data
        response.headers = {"content-type": "text/plain"}
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [
            {
                "url": "https://example.com/notes.txt",
                "content_type": "text/plain",
                "filename": "notes.txt",
            }
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["type"] == "document"
        assert attachments[0]["media_type"] == "text/plain"
        assert attachments[0]["filename"] == "notes.txt"

    @pytest.mark.asyncio
    async def test_uses_intercom_content_type(self, mock_http_client, sample_pdf_data):
        """Should prefer content_type from Intercom attachment over response header."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_pdf_data
        response.headers = {"content-type": "application/octet-stream"}
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [
            {
                "url": "https://example.com/doc.pdf",
                "content_type": "application/pdf",
                "filename": "",
            }
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["media_type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_infers_media_type_from_url(self, mock_http_client, sample_pdf_data):
        """Should infer media type from URL when content_type is missing."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_pdf_data
        response.headers = {}
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [{"url": "https://example.com/doc.pdf", "content_type": "", "filename": ""}]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert len(attachments) == 1
        assert attachments[0]["media_type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_skips_failed_downloads(self, mock_http_client):
        """Should skip documents that fail to download."""
        response = MagicMock()
        response.is_success = False
        response.status_code = 404
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [
            {
                "url": "https://example.com/notfound.pdf",
                "content_type": "application/pdf",
                "filename": "",
            }
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert attachments == []

    @pytest.mark.asyncio
    async def test_handles_download_exception(self, mock_http_client):
        """Should handle exceptions during download."""
        mock_http_client.get = AsyncMock(side_effect=Exception("Network error"))

        docs = [
            {
                "url": "https://example.com/doc.pdf",
                "content_type": "application/pdf",
                "filename": "",
            }
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert attachments == []

    @pytest.mark.asyncio
    async def test_build_multiple_attachments(self, mock_http_client, sample_pdf_data):
        """Should build multiple attachments."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_pdf_data
        response.headers = {"content-type": "application/pdf"}
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [
            {
                "url": "https://example.com/a.pdf",
                "content_type": "application/pdf",
                "filename": "a.pdf",
            },
            {
                "url": "https://example.com/b.pdf",
                "content_type": "application/pdf",
                "filename": "b.pdf",
            },
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert len(attachments) == 2

    @pytest.mark.asyncio
    async def test_build_empty_list(self, mock_http_client):
        """Should return empty list for empty input."""
        attachments = await _build_document_attachments([], mock_http_client)
        assert attachments == []

    @pytest.mark.asyncio
    async def test_omits_filename_when_empty(self, mock_http_client, sample_pdf_data):
        """Should not include filename key when it's empty."""
        response = MagicMock()
        response.is_success = True
        response.content = sample_pdf_data
        response.headers = {"content-type": "application/pdf"}
        mock_http_client.get = AsyncMock(return_value=response)

        docs = [
            {
                "url": "https://example.com/doc.pdf",
                "content_type": "application/pdf",
                "filename": "",
            }
        ]
        attachments = await _build_document_attachments(docs, mock_http_client)

        assert len(attachments) == 1
        assert "filename" not in attachments[0]
