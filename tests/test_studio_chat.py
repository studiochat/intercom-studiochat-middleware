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


class TestMarkHandoff:
    """Tests for the mark_handoff method on StudioChatClient."""

    @pytest.fixture
    def client(self, sample_studio_chat_config: StudioChatConfig) -> StudioChatClient:
        """Create a Studio Chat client with a mock HTTP client."""
        mock_http_client = AsyncMock(spec=httpx.AsyncClient)
        return StudioChatClient(sample_studio_chat_config, mock_http_client)

    async def test_mark_handoff_success(self, client: StudioChatClient):
        """Test successful handoff notification."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        client.client.post = AsyncMock(return_value=mock_response)

        await client.mark_handoff(
            playbook_id="test-playbook",
            conversation_id="conv-123",
            error_type="unsupported_media",
        )

        client.client.post.assert_called_once()
        call_args = client.client.post.call_args
        assert "test-playbook" in call_args.args[0]
        assert "conv-123" in call_args.args[0]
        assert "/handoff" in call_args.args[0]
        assert call_args.kwargs["json"] == {"error_type": "unsupported_media"}

    async def test_mark_handoff_default_error_type(self, client: StudioChatClient):
        """Test that error_type defaults to external_handoff."""
        mock_response = MagicMock()
        mock_response.is_success = True

        client.client.post = AsyncMock(return_value=mock_response)

        await client.mark_handoff(
            playbook_id="test-playbook",
            conversation_id="conv-123",
        )

        call_args = client.client.post.call_args
        assert call_args.kwargs["json"] == {"error_type": "external_handoff"}

    async def test_mark_handoff_failure_does_not_raise(self, client: StudioChatClient):
        """Test that a failed response is logged but does not raise."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500

        client.client.post = AsyncMock(return_value=mock_response)

        # Should not raise
        await client.mark_handoff(
            playbook_id="test-playbook",
            conversation_id="conv-123",
        )

    async def test_mark_handoff_network_error_does_not_raise(self, client: StudioChatClient):
        """Test that network errors are caught and do not raise."""
        client.client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        # Should not raise
        await client.mark_handoff(
            playbook_id="test-playbook",
            conversation_id="conv-123",
        )

    async def test_mark_handoff_timeout_does_not_raise(self, client: StudioChatClient):
        """Test that timeouts are caught and do not raise."""
        client.client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

        # Should not raise
        await client.mark_handoff(
            playbook_id="test-playbook",
            conversation_id="conv-123",
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


class TestFeedbackNote:
    """Tests for the per-assistant feedback note (deep-link) feature."""

    @pytest.fixture
    def mock_intercom_actions(self) -> AsyncMock:
        mock = AsyncMock()
        mock.send_text = AsyncMock()
        mock.send_note = AsyncMock()
        mock.send_image = AsyncMock()
        mock.add_tag = AsyncMock()
        return mock

    @pytest.fixture
    def assistant_with_feedback(self, sample_assistant_config: AssistantConfig) -> AssistantConfig:
        return sample_assistant_config.model_copy(update={"include_feedback_note": True})

    async def test_feedback_note_sent_when_flag_on_and_deep_link_present(
        self,
        assistant_with_feedback: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "Hi there"},
                )
            ],
            deep_link="https://app.studiochat.io/activity/chatlogs/conv-123?r=2",
        )

        result = await process_events(
            response=response,
            assistant=assistant_with_feedback,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.feedback_note_sent is True
        # The note should include the deep_link URL as an HTML anchor so
        # Intercom renders it as a clickable link.
        mock_intercom_actions.send_note.assert_called_once()
        call_kwargs = mock_intercom_actions.send_note.call_args.kwargs
        assert call_kwargs["conversation_id"] == "conv-123"
        assert call_kwargs["admin_id"] == "test-admin-id"
        assert (
            'href="https://app.studiochat.io/activity/chatlogs/conv-123?r=2"' in call_kwargs["note"]
        )

    async def test_feedback_note_skipped_when_flag_off(
        self,
        sample_assistant_config: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "Hi"},
                )
            ],
            deep_link="https://app.studiochat.io/activity/chatlogs/conv-123?r=0",
        )

        result = await process_events(
            response=response,
            assistant=sample_assistant_config,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.feedback_note_sent is False
        mock_intercom_actions.send_note.assert_not_called()

    async def test_feedback_note_skipped_when_deep_link_missing(
        self,
        assistant_with_feedback: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "Hi"},
                )
            ],
            # deep_link omitted
        )

        result = await process_events(
            response=response,
            assistant=assistant_with_feedback,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.feedback_note_sent is False
        mock_intercom_actions.send_note.assert_not_called()

    async def test_feedback_note_skipped_on_handoff(
        self,
        assistant_with_feedback: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        # Response with both a message and a handoff — a human is taking
        # over, so the feedback link would be noise for them.
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.MESSAGE,
                    data={"content": "Te derivo a un humano."},
                ),
                StudioChatEvent(
                    event_type=StudioChatEventType.HANDOFF_AGENT,
                    data={"reason": "User asked for human"},
                ),
            ],
            deep_link="https://app.studiochat.io/activity/chatlogs/conv-123?r=0",
        )

        result = await process_events(
            response=response,
            assistant=assistant_with_feedback,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.handoff_requested is True
        assert result.feedback_note_sent is False
        mock_intercom_actions.send_note.assert_not_called()

    async def test_feedback_note_skipped_when_no_content_delivered(
        self,
        assistant_with_feedback: AssistantConfig,
        mock_intercom_actions: AsyncMock,
    ):
        # Response with only a tag — nothing was surfaced to the user, so
        # a "feedback on this response" link would point at nothing.
        response = StudioChatResponse(
            events=[
                StudioChatEvent(
                    event_type=StudioChatEventType.LABEL,
                    data={"label": "internal-tag"},
                ),
            ],
            deep_link="https://app.studiochat.io/activity/chatlogs/conv-123?r=0",
        )

        result = await process_events(
            response=response,
            assistant=assistant_with_feedback,
            conversation_id="conv-123",
            intercom_actions=mock_intercom_actions,
        )

        assert result.feedback_note_sent is False
        mock_intercom_actions.send_note.assert_not_called()

    def test_deep_link_parsed_from_api_response(self):
        # Backwards-compat: the field is optional, extra fields are ignored.
        response = StudioChatResponse.model_validate(
            {
                "events": [],
                "explanation": "…",
                "first_seen": False,
                "deep_link": "https://app.studiochat.io/activity/chatlogs/abc?r=1",
            }
        )
        assert response.deep_link == "https://app.studiochat.io/activity/chatlogs/abc?r=1"

    def test_deep_link_defaults_to_none_when_absent(self):
        response = StudioChatResponse.model_validate({"events": []})
        assert response.deep_link is None
