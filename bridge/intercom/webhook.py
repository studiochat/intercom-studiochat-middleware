"""Intercom webhook parsing and validation.

Security Model
--------------
IMPORTANT: Intercom webhooks are NOT signed. They cannot be trusted as source of truth.

The webhook is only a NOTIFICATION that something happened. We MUST:
1. Use the webhook as a hint/trigger only
2. Always fetch the actual data from the Intercom API
3. Verify the API data matches the webhook hint (log warning if mismatch)
4. Process ONLY the data from the API (never trust webhook payload directly)

This protects against:
- Spoofed webhooks from attackers
- Race conditions where webhook data is stale
- Data inconsistencies between webhook and actual state

Webhook Strategy
----------------
This module handles two webhook topics from Intercom:

1. conversation.user.replied
   - Fires when a user sends a message
   - Message in payload is stored as hint for verification
   - Actual message is ALWAYS fetched from API
   - Problem: When using Inbox Rules, team_assignee_id may not be set yet

2. conversation.admin.assigned
   - Fires when a conversation is assigned to an inbox (team) or admin
   - Message not in payload - fetched from API
   - Solves the Inbox Rules timing issue: we process after assignment happens

Duplicate Prevention
--------------------
When the bot replies to a conversation, Intercom fires another
conversation.admin.assigned webhook because the bot auto-assigns itself.

We differentiate the two webhooks by checking admin_assignee_id:
- First webhook (process): admin_assignee_id=None, team_assignee_id=<inbox_id>
  → Fresh assignment to inbox, no admin has handled it yet
- Second webhook (ignore): admin_assignee_id=<bot_id>, team_assignee_id=<inbox_id>
  → Bot replied and auto-assigned itself, already handled
"""

from typing import Any

from loguru import logger

from ..constants import (
    SUPPORTED_WEBHOOK_TOPICS,
    TOPIC_ADMIN_ASSIGNED,
    TOPIC_USER_REPLIED,
    USER_AUTHOR_TYPES,
)
from ..models import IntercomContact, IntercomWebhookData
from ..utils.html import is_whatsapp_error, is_whatsapp_reaction, strip_html_tags


class WebhookParseError(Exception):
    """Raised when webhook parsing fails."""

    pass


def parse_webhook(payload: dict[str, Any]) -> IntercomWebhookData | None:
    """
    Parse an Intercom webhook payload.

    Args:
        payload: The raw webhook JSON payload

    Returns:
        Parsed IntercomWebhookData, or None if the webhook should be ignored

    Raises:
        WebhookParseError: If the payload is invalid
    """
    topic = payload.get("topic")

    if not topic:
        raise WebhookParseError("Missing 'topic' in webhook payload")

    if topic not in SUPPORTED_WEBHOOK_TOPICS:
        logger.debug("Unsupported webhook topic: {}", topic)
        return None

    data = payload.get("data", {})
    item = data.get("item", {})

    conversation_id = item.get("id")
    if not conversation_id:
        raise WebhookParseError("Missing conversation ID in webhook payload")

    # Dispatch to topic-specific parser
    if topic == TOPIC_USER_REPLIED:
        return _parse_user_replied(topic, item, conversation_id)
    elif topic == TOPIC_ADMIN_ASSIGNED:
        return _parse_admin_assigned(topic, item, conversation_id)

    return None


def _parse_user_replied(
    topic: str, item: dict[str, Any], conversation_id: str
) -> IntercomWebhookData | None:
    """Parse a conversation.user.replied webhook.

    Security: The message from the webhook is stored as a hint for verification,
    but the actual message is always fetched from the API (webhooks are not signed).
    """
    # Extract admin and team assignee
    admin_assignee_id = (
        str(item.get("admin_assignee_id")) if item.get("admin_assignee_id") is not None else None
    )
    team_assignee_id = (
        str(item.get("team_assignee_id")) if item.get("team_assignee_id") is not None else None
    )

    # Extract tags
    tags_data = item.get("tags", {}).get("tags", [])
    tags = [tag.get("name", "") for tag in tags_data if tag.get("name")]

    # Extract contact
    contact = _extract_contact(item)

    # Extract user message as hint (for verification against API)
    webhook_message_hint = _extract_user_message(item)

    # If webhook indicates no message, still return data to fetch from API
    # The API fetch will determine if there's actually a message to process

    return IntercomWebhookData(
        topic=topic,
        conversation_id=conversation_id,
        message=None,  # Always fetch from API
        contact=contact,
        admin_assignee_id=admin_assignee_id,
        team_assignee_id=team_assignee_id,
        tags=tags,
        webhook_message_hint=webhook_message_hint,
    )


def _parse_admin_assigned(
    topic: str, item: dict[str, Any], conversation_id: str
) -> IntercomWebhookData | None:
    """
    Parse a conversation.admin.assigned webhook.

    This webhook fires when a conversation is assigned to an admin or team.
    The message is not included, so we need to fetch it separately.

    We only process assignments where admin_assignee_id is None (team-only assignment).
    When admin_assignee_id is set, it means an admin (like our bot) already handled it.
    """
    admin_assignee_id_raw = item.get("admin_assignee_id")
    team_assignee_id_raw = item.get("team_assignee_id")

    # Only process team assignments without an admin assignee
    # If admin_assignee_id is set, the bot already replied and auto-assigned itself
    if admin_assignee_id_raw is not None:
        logger.debug(
            "Ignoring admin assigned: conversation={}, admin={}, team={}",
            conversation_id,
            admin_assignee_id_raw,
            team_assignee_id_raw,
        )
        return None

    # Extract admin and team assignee
    admin_assignee_id = None
    team_assignee_id = str(team_assignee_id_raw) if team_assignee_id_raw is not None else None

    # Extract tags
    tags_data = item.get("tags", {}).get("tags", [])
    tags = [tag.get("name", "") for tag in tags_data if tag.get("name")]

    # Extract contact
    contact = _extract_contact(item)

    return IntercomWebhookData(
        topic=topic,
        conversation_id=conversation_id,
        message=None,  # Always fetch from API (webhooks are not signed)
        contact=contact,
        admin_assignee_id=admin_assignee_id,
        team_assignee_id=team_assignee_id,
        tags=tags,
    )


def _extract_contact(item: dict[str, Any]) -> IntercomContact | None:
    """Extract contact information from webhook item."""
    contacts_data = item.get("contacts", {}).get("contacts", [])
    if contacts_data:
        first_contact = contacts_data[0]
        return IntercomContact(
            id=first_contact.get("id", ""),
            name=first_contact.get("name"),
            email=first_contact.get("email"),
        )
    return None


def _extract_user_message(item: dict[str, Any]) -> str | None:
    """
    Extract the user message from a conversation.user.replied webhook.

    Args:
        item: The conversation item from the webhook

    Returns:
        The extracted message text, or None if no valid message
    """
    # Get conversation parts
    conversation_parts = item.get("conversation_parts", {}).get("conversation_parts", [])

    if not conversation_parts:
        logger.debug("No conversation parts")
        return None

    # Get the most recent part
    latest_part = conversation_parts[-1]

    # Check if this is from a user (not an admin)
    author = latest_part.get("author", {})
    author_type = author.get("type", "")

    if author_type not in USER_AUTHOR_TYPES:
        logger.debug("Message not from user: author_type={}", author_type)
        return None

    # Get the body
    body = latest_part.get("body", "")

    if not body:
        return None

    # Filter out WhatsApp reactions and errors
    if is_whatsapp_reaction(body):
        logger.debug("Ignoring WhatsApp reaction")
        return None

    if is_whatsapp_error(body):
        logger.debug("Ignoring WhatsApp error")
        return None

    # Convert HTML to plain text
    return strip_html_tags(body)
