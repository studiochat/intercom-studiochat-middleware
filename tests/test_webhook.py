"""Tests for webhook parsing."""

import pytest

from bridge.intercom.webhook import (
    WebhookParseError,
    parse_webhook,
)


def test_parse_webhook_user_replied(sample_webhook_payload: dict):
    """Test parsing a conversation.user.replied webhook."""
    result = parse_webhook(sample_webhook_payload)

    assert result is not None
    assert result.topic == "conversation.user.replied"
    assert result.conversation_id == "test-conversation-id"
    # With security model: message is None (fetched from API), hint stored for verification
    assert result.message is None
    assert result.webhook_message_hint == "Hello, I need help with my order"
    assert result.team_assignee_id == "test-inbox-id"
    assert result.contact is not None
    assert result.contact.name == "Test User"
    assert result.contact.email == "test@example.com"
    assert "existing-tag" in result.tags


def test_parse_webhook_unsupported_topic():
    """Test that unsupported topics return None."""
    payload = {
        "topic": "conversation.created",
        "data": {"item": {"id": "conv-123"}},
    }

    result = parse_webhook(payload)
    assert result is None


def test_parse_webhook_missing_topic():
    """Test error when topic is missing."""
    payload = {"data": {"item": {"id": "conv-123"}}}

    with pytest.raises(WebhookParseError) as exc_info:
        parse_webhook(payload)

    assert "topic" in str(exc_info.value)


def test_parse_webhook_missing_conversation_id():
    """Test error when conversation ID is missing."""
    payload = {
        "topic": "conversation.user.replied",
        "data": {"item": {}},
    }

    with pytest.raises(WebhookParseError) as exc_info:
        parse_webhook(payload)

    assert "conversation ID" in str(exc_info.value)


def test_parse_webhook_whatsapp_reaction():
    """Test that WhatsApp reactions are filtered from webhook hint."""
    payload = {
        "topic": "conversation.user.replied",
        "data": {
            "item": {
                "id": "conv-123",
                "tags": {"tags": []},
                "contacts": {"contacts": []},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            # WhatsApp reaction format
                            "body": '<p>Reacted to "Hello" with 👍</p>',
                        }
                    ]
                },
            }
        },
    }

    result = parse_webhook(payload)
    # Webhook data is returned but hint is None (reaction filtered)
    assert result is not None
    assert result.webhook_message_hint is None


def test_parse_webhook_admin_message_ignored():
    """Test that messages from admins are filtered from webhook hint."""
    payload = {
        "topic": "conversation.user.replied",
        "data": {
            "item": {
                "id": "conv-123",
                "tags": {"tags": []},
                "contacts": {"contacts": []},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "admin"},
                            "body": "<p>Admin response</p>",
                        }
                    ]
                },
            }
        },
    }

    result = parse_webhook(payload)
    # Webhook data is returned but hint is None (admin message filtered)
    assert result is not None
    assert result.webhook_message_hint is None
