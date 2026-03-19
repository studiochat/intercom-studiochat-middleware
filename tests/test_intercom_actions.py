"""Tests for Intercom actions with handoff lock."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bridge.handoff_lock import is_locked, mark_handoff
from bridge.intercom.actions import IntercomActions
from bridge.intercom.client import IntercomClient
from bridge.models import (
    Action,
    ActionType,
    AssistantConfig,
    FallbackConfig,
    HandoffConfig,
    IntercomConfig,
    RolloutConfig,
    RoutingRule,
    RoutingRuleType,
)


@pytest.fixture
def mock_intercom_client():
    """Mock Intercom client with all methods mocked."""
    config = IntercomConfig(access_token="test-token")
    http_client = MagicMock(spec=httpx.AsyncClient)
    client = IntercomClient(config, http_client)

    # Mock all client methods
    client.reply_to_conversation = AsyncMock(return_value={"id": "part-123"})
    client.attach_file_to_conversation = AsyncMock(return_value={"id": "part-456"})
    client.add_tag_to_conversation = AsyncMock(return_value={})
    client.get_or_create_tag = AsyncMock(return_value="tag-id-123")
    client.assign_conversation = AsyncMock(return_value={})
    client.unassign_admin = AsyncMock(return_value={})

    return client


@pytest.fixture
def intercom_actions(mock_intercom_client):
    """IntercomActions instance with mocked client."""
    return IntercomActions(mock_intercom_client)


@pytest.fixture
def sample_assistant():
    """Sample assistant configuration for testing."""
    return AssistantConfig(
        playbook_id="test-playbook",
        admin_id="admin-123",
        rollout=RolloutConfig(percentage=100),
        routing_rules=[
            RoutingRule(type=RoutingRuleType.INBOX, inbox_id="inbox-1"),
        ],
        handoff=HandoffConfig(
            actions=[
                Action(type=ActionType.ADD_TAG, tag_name="handoff-tag"),
                Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="human-inbox"),
            ]
        ),
        fallback=FallbackConfig(
            actions=[
                Action(type=ActionType.ADD_TAG, tag_name="fallback-tag"),
                Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="fallback-inbox"),
            ]
        ),
    )


class TestSendTextWithLock:
    """Tests for send_text with handoff lock."""

    @pytest.mark.asyncio
    async def test_send_text_succeeds_when_not_locked(self, intercom_actions, mock_intercom_client):
        """send_text should send message when conversation is not locked."""
        await intercom_actions.send_text(
            conversation_id="conv-123",
            admin_id="admin-456",
            message="Hello!",
        )

        mock_intercom_client.reply_to_conversation.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="admin-456",
            message="Hello!",
            message_type="comment",
        )

    @pytest.mark.asyncio
    async def test_send_text_skips_when_locked(self, intercom_actions, mock_intercom_client):
        """send_text should skip when conversation is locked."""
        mark_handoff("conv-locked")

        await intercom_actions.send_text(
            conversation_id="conv-locked",
            admin_id="admin-456",
            message="Hello!",
        )

        # Should not call the client
        mock_intercom_client.reply_to_conversation.assert_not_called()


class TestSendNoteWithLock:
    """Tests for send_note with handoff lock."""

    @pytest.mark.asyncio
    async def test_send_note_succeeds_when_not_locked(self, intercom_actions, mock_intercom_client):
        """send_note should send when conversation is not locked."""
        await intercom_actions.send_note(
            conversation_id="conv-123",
            admin_id="admin-456",
            note="Internal note",
        )

        mock_intercom_client.reply_to_conversation.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="admin-456",
            message="Internal note",
            message_type="note",
        )

    @pytest.mark.asyncio
    async def test_send_note_skips_when_locked(self, intercom_actions, mock_intercom_client):
        """send_note should skip when conversation is locked."""
        mark_handoff("conv-locked")

        await intercom_actions.send_note(
            conversation_id="conv-locked",
            admin_id="admin-456",
            note="Internal note",
        )

        mock_intercom_client.reply_to_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_note_with_bypass_lock(self, intercom_actions, mock_intercom_client):
        """send_note should send when bypass_lock=True even if locked."""
        mark_handoff("conv-locked")

        await intercom_actions.send_note(
            conversation_id="conv-locked",
            admin_id="admin-456",
            note="Handoff note",
            bypass_lock=True,
        )

        # Should call even though locked
        mock_intercom_client.reply_to_conversation.assert_called_once()


class TestSendImageWithLock:
    """Tests for send_image with handoff lock."""

    @pytest.mark.asyncio
    async def test_send_image_succeeds_when_not_locked(
        self, intercom_actions, mock_intercom_client
    ):
        """send_image should send when conversation is not locked."""
        await intercom_actions.send_image(
            conversation_id="conv-123",
            admin_id="admin-456",
            image_url="https://example.com/image.png",
        )

        mock_intercom_client.attach_file_to_conversation.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="admin-456",
            file_url="https://example.com/image.png",
        )

    @pytest.mark.asyncio
    async def test_send_image_skips_when_locked(self, intercom_actions, mock_intercom_client):
        """send_image should skip when conversation is locked."""
        mark_handoff("conv-locked")

        await intercom_actions.send_image(
            conversation_id="conv-locked",
            admin_id="admin-456",
            image_url="https://example.com/image.png",
        )

        mock_intercom_client.attach_file_to_conversation.assert_not_called()


class TestExecuteHandoffSetsLock:
    """Tests for execute_handoff setting the lock."""

    @pytest.mark.asyncio
    async def test_execute_handoff_sets_lock(self, intercom_actions, sample_assistant):
        """execute_handoff should mark the conversation as locked."""
        assert is_locked("conv-handoff") is False

        await intercom_actions.execute_handoff(
            conversation_id="conv-handoff",
            assistant=sample_assistant,
            reason="User requested human",
        )

        assert is_locked("conv-handoff") is True

    @pytest.mark.asyncio
    async def test_execute_handoff_still_executes_actions(
        self, intercom_actions, mock_intercom_client, sample_assistant
    ):
        """execute_handoff should execute its actions despite the lock."""
        await intercom_actions.execute_handoff(
            conversation_id="conv-handoff",
            assistant=sample_assistant,
            reason="User requested human",
        )

        # Handoff note should be sent
        assert mock_intercom_client.reply_to_conversation.call_count >= 1

        # Tag should be added
        mock_intercom_client.add_tag_to_conversation.assert_called()

        # Transfer should happen (unassign + assign to team)
        assert mock_intercom_client.unassign_admin.call_count == 1
        assert mock_intercom_client.assign_conversation.call_count == 1


class TestExecuteFallbackSetsLock:
    """Tests for execute_fallback setting the lock."""

    @pytest.mark.asyncio
    async def test_execute_fallback_sets_lock(self, intercom_actions, sample_assistant):
        """execute_fallback should mark the conversation as locked."""
        assert is_locked("conv-fallback") is False

        await intercom_actions.execute_fallback(
            conversation_id="conv-fallback",
            assistant=sample_assistant,
        )

        assert is_locked("conv-fallback") is True

    @pytest.mark.asyncio
    async def test_execute_fallback_still_executes_actions(
        self, intercom_actions, mock_intercom_client, sample_assistant
    ):
        """execute_fallback should execute its actions despite the lock."""
        await intercom_actions.execute_fallback(
            conversation_id="conv-fallback",
            assistant=sample_assistant,
        )

        # Tag should be added
        mock_intercom_client.add_tag_to_conversation.assert_called()

        # Transfer should happen
        mock_intercom_client.unassign_admin.assert_called()
        mock_intercom_client.assign_conversation.assert_called()


class TestParallelRequestScenario:
    """Tests simulating parallel request scenarios."""

    @pytest.mark.asyncio
    async def test_parallel_request_skips_after_handoff(
        self, intercom_actions, mock_intercom_client, sample_assistant
    ):
        """
        Simulates: Request B starts handoff, Request A tries to send messages.
        Request A's messages should be skipped.
        """
        # Request B starts handoff first
        await intercom_actions.execute_handoff(
            conversation_id="conv-parallel",
            assistant=sample_assistant,
            reason="Handoff reason",
        )

        # Reset mock to track only Request A's calls
        mock_intercom_client.reply_to_conversation.reset_mock()

        # Request A tries to send messages (should be skipped)
        await intercom_actions.send_text(
            conversation_id="conv-parallel",
            admin_id="admin-456",
            message="Message 1",
        )
        await intercom_actions.send_text(
            conversation_id="conv-parallel",
            admin_id="admin-456",
            message="Message 2",
        )
        await intercom_actions.send_image(
            conversation_id="conv-parallel",
            admin_id="admin-456",
            image_url="https://example.com/img.png",
        )

        # None of these should have been sent
        mock_intercom_client.reply_to_conversation.assert_not_called()
        mock_intercom_client.attach_file_to_conversation.assert_not_called()
