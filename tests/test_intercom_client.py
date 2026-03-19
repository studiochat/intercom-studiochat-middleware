"""Tests for Intercom client."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bridge.intercom.client import (
    INTERCOM_API_BASE,
    IntercomClient,
    IntercomError,
)
from bridge.models import IntercomConfig


@pytest.fixture
def intercom_config():
    """Sample Intercom configuration."""
    return IntercomConfig(access_token="test-token")


@pytest.fixture
def mock_http_client():
    """Mock HTTP client."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def intercom_client(intercom_config, mock_http_client):
    """Intercom client with mocked HTTP client."""
    return IntercomClient(intercom_config, mock_http_client)


class TestIntercomClientHeaders:
    """Tests for header generation."""

    def test_headers_include_auth(self, intercom_client):
        """Test that headers include authorization."""
        headers = intercom_client._get_headers()
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert "Intercom-Version" in headers


class TestGetContact:
    """Tests for get_contact method."""

    @pytest.mark.asyncio
    async def test_get_contact_success(self, intercom_client, mock_http_client):
        """Test successful contact retrieval."""
        contact_data = {
            "id": "contact-123",
            "email": "user@example.com",
            "name": "Test User",
            "phone": "+1234567890",
            "external_id": "ext-123",
            "custom_attributes": {
                "Plan Type": "premium",
                "Subscription Status": "active",
            },
        }

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = contact_data
        mock_response.text = '{"id": "contact-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        result = await intercom_client.get_contact("contact-123")

        assert result == contact_data
        mock_http_client.request.assert_called_once()
        call_kwargs = mock_http_client.request.call_args
        assert call_kwargs.kwargs["method"] == "GET"
        assert call_kwargs.kwargs["url"] == f"{INTERCOM_API_BASE}/contacts/contact-123"

    @pytest.mark.asyncio
    async def test_get_contact_not_found(self, intercom_client, mock_http_client):
        """Test contact not found error."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 404
        mock_response.text = '{"type": "error.list", "errors": [{"code": "not_found"}]}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(IntercomError) as exc_info:
            await intercom_client.get_contact("nonexistent")

        assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_contact_request_error(self, intercom_client, mock_http_client):
        """Test contact retrieval with network error."""
        mock_http_client.request = AsyncMock(side_effect=httpx.RequestError("Connection failed"))

        with pytest.raises(IntercomError) as exc_info:
            await intercom_client.get_contact("contact-123")

        assert "Request failed" in str(exc_info.value)


class TestGetConversation:
    """Tests for get_conversation method."""

    @pytest.mark.asyncio
    async def test_get_conversation_success(self, intercom_client, mock_http_client):
        """Test successful conversation retrieval."""
        conversation_data = {
            "id": "conv-123",
            "state": "open",
            "custom_attributes": {
                "Ticket Priority": "high",
                "Department": "Sales",
            },
            "tags": {"tags": [{"name": "vip"}]},
        }

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = conversation_data
        mock_response.text = '{"id": "conv-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        result = await intercom_client.get_conversation("conv-123")

        assert result == conversation_data
        mock_http_client.request.assert_called_once()
        call_kwargs = mock_http_client.request.call_args
        assert call_kwargs.kwargs["method"] == "GET"
        assert call_kwargs.kwargs["url"] == f"{INTERCOM_API_BASE}/conversations/conv-123"

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, intercom_client, mock_http_client):
        """Test conversation not found error."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 404
        mock_response.text = '{"type": "error.list", "errors": [{"code": "not_found"}]}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(IntercomError) as exc_info:
            await intercom_client.get_conversation("nonexistent")

        assert "404" in str(exc_info.value)


class TestReplyToConversation:
    """Tests for reply_to_conversation method."""

    @pytest.mark.asyncio
    async def test_reply_success(self, intercom_client, mock_http_client):
        """Test successful reply."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "part-123"}
        mock_response.text = '{"id": "part-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        result = await intercom_client.reply_to_conversation(
            conversation_id="conv-123",
            admin_id="admin-456",
            message="Hello!",
        )

        assert result == {"id": "part-123"}
        call_kwargs = mock_http_client.request.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert call_kwargs.kwargs["json"]["admin_id"] == "admin-456"
        assert call_kwargs.kwargs["json"]["body"] == "Hello!"
        assert call_kwargs.kwargs["json"]["message_type"] == "comment"

    @pytest.mark.asyncio
    async def test_reply_as_note(self, intercom_client, mock_http_client):
        """Test reply as private note."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "part-123"}
        mock_response.text = '{"id": "part-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        await intercom_client.reply_to_conversation(
            conversation_id="conv-123",
            admin_id="admin-456",
            message="Internal note",
            message_type="note",
        )

        call_kwargs = mock_http_client.request.call_args
        assert call_kwargs.kwargs["json"]["message_type"] == "note"


class TestGetOrCreateTag:
    """Tests for get_or_create_tag method."""

    @pytest.mark.asyncio
    async def test_get_existing_tag(self, intercom_client, mock_http_client):
        """Test finding an existing tag."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "data": [
                {"id": "tag-1", "name": "other-tag"},
                {"id": "tag-2", "name": "ai-handoff"},
            ]
        }
        mock_response.text = '{"data": []}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        result = await intercom_client.get_or_create_tag("ai-handoff")

        assert result == "tag-2"
        # Only one call to GET /tags
        assert mock_http_client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_create_new_tag(self, intercom_client, mock_http_client):
        """Test creating a new tag."""
        # First call returns empty tag list
        get_response = MagicMock()
        get_response.is_success = True
        get_response.json.return_value = {"data": []}
        get_response.text = '{"data": []}'

        # Second call creates the tag
        create_response = MagicMock()
        create_response.is_success = True
        create_response.json.return_value = {"id": "new-tag-id", "name": "new-tag"}
        create_response.text = '{"id": "new-tag-id"}'

        mock_http_client.request = AsyncMock(side_effect=[get_response, create_response])

        result = await intercom_client.get_or_create_tag("new-tag")

        assert result == "new-tag-id"
        assert mock_http_client.request.call_count == 2


class TestAssignConversation:
    """Tests for assign_conversation method."""

    @pytest.mark.asyncio
    async def test_assign_to_admin(self, intercom_client, mock_http_client):
        """Test assigning to an admin."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "conv-123"}
        mock_response.text = '{"id": "conv-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        await intercom_client.assign_conversation(
            conversation_id="conv-123",
            admin_id="admin-1",
            assignee_id="admin-2",
        )

        call_kwargs = mock_http_client.request.call_args
        assert call_kwargs.kwargs["json"]["assignee_id"] == "admin-2"
        assert call_kwargs.kwargs["json"]["type"] == "admin"

    @pytest.mark.asyncio
    async def test_assign_to_team(self, intercom_client, mock_http_client):
        """Test assigning to a team (inbox)."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "conv-123"}
        mock_response.text = '{"id": "conv-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        await intercom_client.assign_conversation(
            conversation_id="conv-123",
            admin_id="admin-1",
            team_id="team-456",
        )

        call_kwargs = mock_http_client.request.call_args
        # Intercom API uses assignee_id for both admin and team assignments
        assert call_kwargs.kwargs["json"]["assignee_id"] == "team-456"
        assert call_kwargs.kwargs["json"]["type"] == "team"


class TestAttachFile:
    """Tests for attach_file_to_conversation method."""

    @pytest.mark.asyncio
    async def test_attach_file_success(self, intercom_client, mock_http_client):
        """Test attaching a file."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"id": "part-123"}
        mock_response.text = '{"id": "part-123"}'
        mock_http_client.request = AsyncMock(return_value=mock_response)

        await intercom_client.attach_file_to_conversation(
            conversation_id="conv-123",
            admin_id="admin-456",
            file_url="https://example.com/image.png",
        )

        call_kwargs = mock_http_client.request.call_args
        assert call_kwargs.kwargs["json"]["attachment_urls"] == ["https://example.com/image.png"]
