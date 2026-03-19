"""Pytest configuration and fixtures."""

import pytest

from bridge.handoff_lock import clear_all_locks
from bridge.models import (
    Action,
    ActionType,
    AppConfig,
    AssistantConfig,
    FallbackConfig,
    HandoffConfig,
    IntercomConfig,
    IntercomContact,
    IntercomWebhookData,
    LoggingConfig,
    RolloutConfig,
    RoutingRule,
    RoutingRuleType,
    StudioChatConfig,
)


@pytest.fixture(autouse=True)
def clear_handoff_locks_fixture():
    """Clear all handoff locks before each test to prevent cross-test pollution."""
    clear_all_locks()
    yield
    clear_all_locks()


@pytest.fixture
def sample_studio_chat_config() -> StudioChatConfig:
    """Sample Studio Chat configuration."""
    return StudioChatConfig(
        base_url="https://api.studio.test",
        api_key="test-api-key",
        timeout_seconds=30,
    )


@pytest.fixture
def sample_intercom_config() -> IntercomConfig:
    """Sample Intercom configuration."""
    return IntercomConfig(
        access_token="test-access-token",
    )


@pytest.fixture
def sample_assistant_config() -> AssistantConfig:
    """Sample assistant configuration."""
    return AssistantConfig(
        playbook_id="test-playbook-id",
        admin_id="test-admin-id",
        rollout=RolloutConfig(percentage=100),
        routing_rules=[
            RoutingRule(type=RoutingRuleType.INBOX, inbox_id="test-inbox-id"),
        ],
        handoff=HandoffConfig(
            actions=[
                Action(type=ActionType.ADD_TAG, tag_name="handoff-tag"),
                Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="human-inbox-id"),
            ]
        ),
        fallback=FallbackConfig(
            actions=[
                Action(type=ActionType.ADD_TAG, tag_name="fallback-tag"),
                Action(
                    type=ActionType.ADD_NOTE,
                    template="AI unavailable. Reason: {reason}",
                ),
            ]
        ),
    )


@pytest.fixture
def sample_app_config(
    sample_studio_chat_config: StudioChatConfig,
    sample_intercom_config: IntercomConfig,
    sample_assistant_config: AssistantConfig,
) -> AppConfig:
    """Sample application configuration."""
    return AppConfig(
        studio_chat=sample_studio_chat_config,
        intercom=sample_intercom_config,
        logging=LoggingConfig(level="DEBUG", format="text"),
        assistants=[sample_assistant_config],
    )


@pytest.fixture
def sample_webhook_data() -> IntercomWebhookData:
    """Sample webhook data for testing."""
    return IntercomWebhookData(
        topic="conversation.user.replied",
        conversation_id="test-conversation-id",
        message="Hello, I need help with my order",
        contact=IntercomContact(
            id="test-contact-id",
            name="Test User",
            email="test@example.com",
        ),
        admin_assignee_id=None,
        team_assignee_id="test-inbox-id",
        tags=["existing-tag"],
    )


@pytest.fixture
def sample_webhook_payload() -> dict:
    """Sample raw webhook payload."""
    return {
        "topic": "conversation.user.replied",
        "data": {
            "item": {
                "id": "test-conversation-id",
                "admin_assignee_id": None,
                "team_assignee_id": "test-inbox-id",
                "tags": {"tags": [{"name": "existing-tag"}]},
                "contacts": {
                    "contacts": [
                        {
                            "id": "test-contact-id",
                            "name": "Test User",
                            "email": "test@example.com",
                        }
                    ]
                },
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with my order</p>",
                        }
                    ]
                },
            }
        },
    }
