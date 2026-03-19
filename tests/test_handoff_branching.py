"""Tests for handoff branching functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.intercom.actions import IntercomActions
from bridge.models import (
    Action,
    ActionType,
    AssistantConfig,
    HandoffBranch,
    HandoffConfig,
    RolloutConfig,
)


@pytest.fixture
def mock_intercom_client():
    """Create a mock Intercom client."""
    client = MagicMock()
    client.reply_to_conversation = AsyncMock()
    client.get_or_create_tag = AsyncMock(return_value="tag-123")
    client.add_tag_to_conversation = AsyncMock()
    client.assign_conversation = AsyncMock()
    client.unassign_admin = AsyncMock()
    return client


@pytest.fixture
def assistant_with_branches() -> AssistantConfig:
    """Assistant with tag-based handoff branches."""
    return AssistantConfig(
        playbook_id="test-playbook",
        admin_id="admin-123",
        rollout=RolloutConfig(percentage=100),
        handoff=HandoffConfig(
            branches=[
                HandoffBranch(
                    tag="sales",
                    actions=[
                        Action(type=ActionType.ADD_TAG, tag_name="handoff-sales"),
                        Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="sales-inbox"),
                    ],
                ),
                HandoffBranch(
                    tag="support",
                    actions=[
                        Action(type=ActionType.ADD_TAG, tag_name="handoff-support"),
                        Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="support-inbox"),
                    ],
                ),
                HandoffBranch(
                    tag="billing",
                    actions=[
                        Action(type=ActionType.ASSIGN_TO_ADMIN, admin_id="billing-admin"),
                    ],
                ),
            ],
            actions=[
                Action(type=ActionType.ADD_TAG, tag_name="handoff-default"),
                Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="default-inbox"),
            ],
        ),
    )


@pytest.fixture
def assistant_without_branches() -> AssistantConfig:
    """Assistant with simple handoff (no branches)."""
    return AssistantConfig(
        playbook_id="test-playbook",
        admin_id="admin-123",
        rollout=RolloutConfig(percentage=100),
        handoff=HandoffConfig(
            actions=[
                Action(type=ActionType.ADD_TAG, tag_name="handoff-tag"),
                Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="human-inbox"),
            ],
        ),
    )


class TestHandoffBranching:
    """Tests for handoff branching logic."""

    @pytest.mark.asyncio
    async def test_handoff_matches_first_branch(
        self, mock_intercom_client, assistant_with_branches
    ):
        """When conversation has a matching tag, use that branch's actions."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Customer requested",
            conversation_tags=["sales", "vip"],  # "sales" should match first branch
        )

        # Should have added handoff note + handoff-sales tag
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-sales" in tag_names
        assert "handoff-default" not in tag_names

        # Should have transferred to sales inbox
        assign_calls = mock_intercom_client.assign_conversation.call_args_list
        assert any(call[1].get("team_id") == "sales-inbox" for call in assign_calls)

    @pytest.mark.asyncio
    async def test_handoff_matches_second_branch(
        self, mock_intercom_client, assistant_with_branches
    ):
        """When first branch doesn't match, check second branch."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Technical issue",
            conversation_tags=["support"],  # "support" should match second branch
        )

        # Should have added handoff-support tag
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-support" in tag_names

        # Should have transferred to support inbox
        assign_calls = mock_intercom_client.assign_conversation.call_args_list
        assert any(call[1].get("team_id") == "support-inbox" for call in assign_calls)

    @pytest.mark.asyncio
    async def test_handoff_uses_default_when_no_branch_matches(
        self, mock_intercom_client, assistant_with_branches
    ):
        """When no tags match any branch, use default actions."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Unknown issue",
            conversation_tags=["unrelated-tag", "another-tag"],  # No matching branch
        )

        # Should have added handoff-default tag
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-default" in tag_names
        assert "handoff-sales" not in tag_names
        assert "handoff-support" not in tag_names

        # Should have transferred to default inbox
        assign_calls = mock_intercom_client.assign_conversation.call_args_list
        assert any(call[1].get("team_id") == "default-inbox" for call in assign_calls)

    @pytest.mark.asyncio
    async def test_handoff_uses_default_when_no_tags(
        self, mock_intercom_client, assistant_with_branches
    ):
        """When conversation has no tags, use default actions."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Issue",
            conversation_tags=[],  # No tags
        )

        # Should use default actions
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-default" in tag_names

    @pytest.mark.asyncio
    async def test_handoff_uses_default_when_tags_none(
        self, mock_intercom_client, assistant_with_branches
    ):
        """When conversation_tags is None, use default actions."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Issue",
            conversation_tags=None,  # None instead of list
        )

        # Should use default actions
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-default" in tag_names

    @pytest.mark.asyncio
    async def test_handoff_first_matching_branch_wins(
        self, mock_intercom_client, assistant_with_branches
    ):
        """When conversation has multiple matching tags, first branch wins."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Multiple issues",
            conversation_tags=["support", "sales"],  # Both match, "sales" is first branch
        )

        # "sales" branch should win since it's defined first in branches list
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-sales" in tag_names
        assert "handoff-support" not in tag_names

    @pytest.mark.asyncio
    async def test_handoff_without_branches_uses_actions(
        self, mock_intercom_client, assistant_without_branches
    ):
        """When no branches defined, always use actions (backward compatibility)."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_without_branches,
            reason="Issue",
            conversation_tags=["any-tag"],
        )

        # Should use the simple actions
        tag_calls = mock_intercom_client.get_or_create_tag.call_args_list
        tag_names = [call[0][0] for call in tag_calls]
        assert "handoff-tag" in tag_names

        # Should have transferred to human inbox
        assign_calls = mock_intercom_client.assign_conversation.call_args_list
        assert any(call[1].get("team_id") == "human-inbox" for call in assign_calls)

    @pytest.mark.asyncio
    async def test_handoff_branch_with_assign_to_admin(
        self, mock_intercom_client, assistant_with_branches
    ):
        """Test branch that assigns to admin instead of inbox."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Billing inquiry",
            conversation_tags=["billing"],
        )

        # Should have assigned to billing admin
        assign_calls = mock_intercom_client.assign_conversation.call_args_list
        assert any(call[1].get("assignee_id") == "billing-admin" for call in assign_calls)

    @pytest.mark.asyncio
    async def test_handoff_always_sends_note(self, mock_intercom_client, assistant_with_branches):
        """Handoff note is always sent regardless of branch."""
        actions = IntercomActions(mock_intercom_client)

        await actions.execute_handoff(
            conversation_id="conv-123",
            assistant=assistant_with_branches,
            reason="Test reason",
            conversation_tags=["sales"],
        )

        # Note should be sent (via reply_to_conversation)
        note_calls = [
            c
            for c in mock_intercom_client.reply_to_conversation.call_args_list
            if c[1].get("message_type") == "note"
        ]
        assert len(note_calls) >= 1
        # Note should contain the reason
        assert any("Test reason" in c[1].get("message", "") for c in note_calls)


class TestTransferToInbox:
    """Tests for transfer_to_inbox."""

    @pytest.mark.asyncio
    async def test_transfer_to_inbox_unassigns_then_assigns_team(self, mock_intercom_client):
        """Test that transfer_to_inbox unassigns admin then assigns to team."""
        mock_intercom_client.unassign_admin = AsyncMock()
        actions = IntercomActions(mock_intercom_client)

        await actions.transfer_to_inbox(
            conversation_id="conv-123",
            admin_id="admin-1",
            inbox_id="team-456",
        )

        # Step 1: Should have called unassign_admin
        mock_intercom_client.unassign_admin.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="admin-1",
        )

        # Step 2: Should have called assign_conversation to team
        mock_intercom_client.assign_conversation.assert_called_once_with(
            conversation_id="conv-123",
            admin_id="admin-1",
            team_id="team-456",
        )

    @pytest.mark.asyncio
    async def test_execute_actions_transfer_to_inbox(self, mock_intercom_client):
        """Test that execute_actions with transfer_to_inbox works correctly."""
        mock_intercom_client.unassign_admin = AsyncMock()
        actions = IntercomActions(mock_intercom_client)

        action_list = [
            Action(
                type=ActionType.TRANSFER_TO_INBOX,
                inbox_id="team-789",
            ),
        ]

        await actions.execute_actions(
            conversation_id="conv-123",
            admin_id="admin-1",
            actions=action_list,
        )

        # Should have called unassign_admin once
        mock_intercom_client.unassign_admin.assert_called_once()

        # Should have called assign_conversation once
        mock_intercom_client.assign_conversation.assert_called_once()
