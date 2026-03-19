"""Tests for Studio Chat client and event processing."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bridge.models import (
    AssistantConfig,
    StudioChatConfig,
    StudioChatEvent,
    StudioChatEventType,
    StudioChatResponse,
)
from bridge.studio_chat.client import (
    StudioChatClient,
    StudioChatConflictError,
    StudioChatError,
    StudioChatUnavailableError,
)
from bridge.studio_chat.events import process_events


class TestStudioChatClient:
    """Tests for the Studio Chat client."""

    @pytest.fixture
    def client(self, sample_studio_chat_config: StudioChatConfig) -> StudioChatClient:
        """Create a Studio Chat client with a mock HTTP client."""
        mock_http_client = AsyncMock(spec=httpx.AsyncClient)
        return StudioChatClient(sample_studio_chat_config, mock_http_client)

    async def test_send_message_success(self, client: StudioChatClient):
        """Test successful message sending."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "events": [
                {"event_type": "message", "data": {"content": "Hello!"}},
            ],
            "explanation": "Greeting response",
        }

        client.client.post = AsyncMock(return_value=mock_response)

        result = await client.send_message(
            playbook_id="test-playbook",
            conversation_id="conv-123",
            user_message="Hi there",
            context={"platform": "intercom"},
        )

        assert len(result.events) == 1
        assert result.events[0].event_type == StudioChatEventType.MESSAGE
        assert result.explanation == "Greeting response"

        # Verify the request
        client.client.post.assert_called_once()
        call_args = client.client.post.call_args
        # URL is the first positional argument
        assert "test-playbook" in call_args.args[0]
        assert call_args.kwargs["json"]["user_message"] == "Hi there"
        assert call_args.kwargs["json"]["conversation_id"] == "conv-123"

    async def test_send_message_with_tags(self, client: StudioChatClient):
        """Test that tags are included in payload when provided."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "events": [],
        }

        client.client.post = AsyncMock(return_value=mock_response)

        await client.send_message(
            playbook_id="test-playbook",
            conversation_id="conv-123",
            user_message="Hi",
            tags=["vip", "billing"],
        )

        call_args = client.client.post.call_args
        assert call_args.kwargs["json"]["tags"] == ["vip", "billing"]

    async def test_send_message_without_tags(self, client: StudioChatClient):
        """Test that tags field is omitted when not provided."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "events": [],
        }

        client.client.post = AsyncMock(return_value=mock_response)

        await client.send_message(
            playbook_id="test-playbook",
            conversation_id="conv-123",
            user_message="Hi",
        )

        call_args = client.client.post.call_args
        assert "tags" not in call_args.kwargs["json"]

    async def test_send_message_conflict(self, client: StudioChatClient):
        """Test 409 Conflict handling."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.is_success = False

        client.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(StudioChatConflictError):
            await client.send_message(
                playbook_id="test-playbook",
                conversation_id="conv-123",
                user_message="Hi",
            )

    async def test_send_message_unavailable(self, client: StudioChatClient):
        """Test 503 Service Unavailable handling."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.is_success = False
        mock_response.headers = {"Retry-After": "30"}

        client.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(StudioChatUnavailableError) as exc_info:
            await client.send_message(
                playbook_id="test-playbook",
                conversation_id="conv-123",
                user_message="Hi",
            )

        assert exc_info.value.retry_after == 30

    async def test_send_message_gateway_timeout(self, client: StudioChatClient):
        """Test 504 Gateway Timeout handling (agent timed out)."""
        mock_response = MagicMock()
        mock_response.status_code = 504
        mock_response.is_success = False

        client.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(StudioChatUnavailableError) as exc_info:
            await client.send_message(
                playbook_id="test-playbook",
                conversation_id="conv-123",
                user_message="Hi",
            )

        # 504 should not have retry_after
        assert exc_info.value.retry_after is None

    async def test_send_message_timeout(self, client: StudioChatClient):
        """Test timeout handling."""
        client.client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

        with pytest.raises(StudioChatUnavailableError):
            await client.send_message(
                playbook_id="test-playbook",
                conversation_id="conv-123",
                user_message="Hi",
            )

    async def test_send_message_error(self, client: StudioChatClient):
        """Test generic error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.is_success = False
        mock_response.text = "Internal Server Error"

        client.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(StudioChatError):
            await client.send_message(
                playbook_id="test-playbook",
                conversation_id="conv-123",
                user_message="Hi",
            )


class TestEventProcessing:
    """Tests for event processing."""

    @pytest.fixture
    def mock_intercom_actions(self) -> AsyncMock:
        """Create mock Intercom actions."""
        mock = AsyncMock()
        mock.send_text = AsyncMock()
        mock.send_note = AsyncMock()
        mock.send_image = AsyncMock()
        mock.add_tag = AsyncMock()
        return mock

    async def test_process_message_event(
        self,
        sample_assistant_config: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        """Test processing a message event."""
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "Hello, how can I help?"},
                )
            ]
        )

        result = await process_events(
            response=response,
            assistant=sample_assistant_config,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.messages_sent == 1
        mock_intercom_actions.send_text.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="test-admin-id",
            message="Hello, how can I help?",
        )

    async def test_process_note_event(
        self,
        sample_assistant_config: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        """Test processing a note event."""
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.NOTE,
                    data={"content": "Internal note for team"},
                )
            ]
        )

        result = await process_events(
            response=response,
            assistant=sample_assistant_config,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.notes_sent == 1
        mock_intercom_actions.send_note.assert_called_once()

    async def test_process_label_event(
        self,
        sample_assistant_config: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        """Test processing a label event."""
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.LABEL,
                    data={"label": "sales-inquiry"},
                )
            ]
        )

        result = await process_events(
            response=response,
            assistant=sample_assistant_config,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.tags_added == 1
        mock_intercom_actions.add_tag.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="test-admin-id",
            tag_name="sales-inquiry",
        )

    async def test_process_handoff_event(
        self,
        sample_assistant_config: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        """Test processing a handoff event."""
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.HANDOFF_AGENT,
                    data={"reason": "User requested human agent"},
                )
            ]
        )

        result = await process_events(
            response=response,
            assistant=sample_assistant_config,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.handoff_requested is True
        assert result.handoff_reason == "User requested human agent"

    async def test_process_multiple_events(
        self,
        sample_assistant_config: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        """Test processing multiple events in sequence."""
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "First message"},
                ),
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "Second message"},
                ),
                StudioChatEvent(
                    event_type=StudioChatEventType.LABEL,
                    data={"label": "some-tag"},
                ),
            ]
        )

        result = await process_events(
            response=response,
            assistant=sample_assistant_config,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.messages_sent == 2
        assert result.tags_added == 1
        assert mock_intercom_actions.send_text.call_count == 2
