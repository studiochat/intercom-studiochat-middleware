"""Tests for shadow mode (shadow_mode)."""

import os
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bridge.app import _is_shadow
from bridge.handoff_lock import is_locked
from bridge.intercom.actions import IntercomActions
from bridge.intercom.client import IntercomClient
from bridge.models import (
    Action,
    ActionType,
    AssistantConfig,
    HandoffConfig,
    IntercomConfig,
)


def _assistant(shadow_mode: bool = False) -> AssistantConfig:
    return AssistantConfig(
        playbook_id="p",
        admin_id="admin-1",
        shadow_mode=shadow_mode,
    )


class TestIsShadow:
    def test_default_is_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHADOW_MODE", None)
            assert _is_shadow(_assistant()) is False

    def test_assistant_flag_true(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHADOW_MODE", None)
            assert _is_shadow(_assistant(shadow_mode=True)) is True

    def test_env_var_true_overrides_assistant_flag(self):
        with mock.patch.dict(os.environ, {"SHADOW_MODE": "true"}):
            assert _is_shadow(_assistant(shadow_mode=False)) is True

    @pytest.mark.parametrize("value", ["1", "yes", "on", "TRUE", "True"])
    def test_env_var_truthy_values(self, value):
        with mock.patch.dict(os.environ, {"SHADOW_MODE": value}):
            assert _is_shadow(_assistant()) is True

    @pytest.mark.parametrize("value", ["false", "", "random", "0", "no"])
    def test_env_var_falsy_values_fall_back_to_flag(self, value):
        with mock.patch.dict(os.environ, {"SHADOW_MODE": value}):
            assert _is_shadow(_assistant(shadow_mode=False)) is False
            assert _is_shadow(_assistant(shadow_mode=True)) is True


class TestAssistantConfigField:
    def test_default_is_false(self):
        assert AssistantConfig(playbook_id="p", admin_id="a").shadow_mode is False

    def test_can_be_enabled(self):
        cfg = AssistantConfig(playbook_id="p", admin_id="a", shadow_mode=True)
        assert cfg.shadow_mode is True


@pytest.fixture
def mock_client():
    config = IntercomConfig(access_token="test-token")
    http_client = MagicMock(spec=httpx.AsyncClient)
    client = IntercomClient(config, http_client)
    client.reply_to_conversation = AsyncMock(return_value={"id": "part-123"})
    client.attach_file_to_conversation = AsyncMock(return_value={"id": "part-456"})
    client.add_tag_to_conversation = AsyncMock(return_value={})
    client.get_or_create_tag = AsyncMock(return_value="tag-id-123")
    client.assign_conversation = AsyncMock(return_value={})
    client.unassign_admin = AsyncMock(return_value={})
    return client


class TestSkipOutboundSuppressesWrites:
    """With skip_outbound=True, no method should touch the Intercom client."""

    @pytest.mark.asyncio
    async def test_send_text_suppressed(self, mock_client):
        actions = IntercomActions(mock_client, skip_outbound=True)
        await actions.send_text(conversation_id="c1", admin_id="a", message="hello")
        mock_client.reply_to_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_note_suppressed(self, mock_client):
        actions = IntercomActions(mock_client, skip_outbound=True)
        await actions.send_note(conversation_id="c1", admin_id="a", note="n")
        mock_client.reply_to_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_tag_suppressed_without_creating_tag(self, mock_client):
        actions = IntercomActions(mock_client, skip_outbound=True)
        await actions.add_tag(conversation_id="c1", admin_id="a", tag_name="t")
        mock_client.get_or_create_tag.assert_not_called()
        mock_client.add_tag_to_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_to_inbox_suppressed(self, mock_client):
        actions = IntercomActions(mock_client, skip_outbound=True)
        await actions.transfer_to_inbox(conversation_id="c1", admin_id="a", inbox_id="42")
        mock_client.unassign_admin.assert_not_called()
        mock_client.assign_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_to_admin_suppressed(self, mock_client):
        actions = IntercomActions(mock_client, skip_outbound=True)
        await actions.assign_to_admin(conversation_id="c1", admin_id="a", assignee_id="b")
        mock_client.assign_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_handoff_writes_nothing_and_no_lock(self, mock_client):
        actions = IntercomActions(mock_client, skip_outbound=True)
        assistant = AssistantConfig(
            playbook_id="p",
            admin_id="a",
            shadow_mode=True,
            handoff=HandoffConfig(
                actions=[
                    Action(type=ActionType.ADD_TAG, tag_name="handoff"),
                    Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="99"),
                    Action(type=ActionType.ADD_NOTE, template="Handoff {reason}"),
                ]
            ),
        )
        await actions.execute_handoff(conversation_id="c1", assistant=assistant, reason="test")
        mock_client.reply_to_conversation.assert_not_called()
        mock_client.assign_conversation.assert_not_called()
        mock_client.unassign_admin.assert_not_called()
        mock_client.get_or_create_tag.assert_not_called()
        # Shadow mode must not lock the conversation, so observation continues.
        assert is_locked("c1") is False

    @pytest.mark.asyncio
    async def test_real_mode_still_sends(self, mock_client):
        """Sanity check: default (non-shadow) actions still hit the client."""
        actions = IntercomActions(mock_client, skip_outbound=False)
        await actions.send_text(conversation_id="c-real", admin_id="a", message="hi")
        mock_client.reply_to_conversation.assert_called_once()
