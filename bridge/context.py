"""Context enrichment for Studio Chat API calls."""

from typing import Any

from loguru import logger

from .intercom import IntercomClient
from .models import AssistantConfig, ContextConfig, IntercomWebhookData


def get_nested_value(data: dict[str, Any], path: str) -> Any:
    """
    Get a nested value from a dictionary using dot notation.

    Supports keys with spaces and special characters.
    Example: "custom_attributes.Plan Type" -> data["custom_attributes"]["Plan Type"]

    Args:
        data: The dictionary to extract from
        path: Dot-separated path to the value

    Returns:
        The value at the path, or None if not found
    """
    if not data or not path:
        return None

    # Split only on first dot to handle keys with spaces
    parts = path.split(".", 1)
    key = parts[0]

    value = data.get(key)

    if len(parts) == 1:
        return value

    if value is None:
        return None

    if isinstance(value, dict):
        return get_nested_value(value, parts[1])

    return None


def extract_attributes(
    data: dict[str, Any],
    attribute_paths: list[str],
) -> dict[str, Any]:
    """
    Extract multiple attributes from data using dot notation paths.

    Args:
        data: Source data dictionary
        attribute_paths: List of dot-notation paths to extract

    Returns:
        Dictionary with extracted values (only non-None values included)
    """
    result: dict[str, Any] = {}

    for path in attribute_paths:
        value = get_nested_value(data, path)
        if value is not None:
            # Use the last part of the path as the key, or full path for nested
            if "." in path:
                # For nested paths, flatten to the leaf key name
                key = path.split(".")[-1]
            else:
                key = path
            # Normalize key: lowercase and replace spaces with underscores
            key = key.lower().replace(" ", "_")
            result[key] = value

    return result


async def build_context(
    webhook_data: IntercomWebhookData,
    assistant: AssistantConfig,
    intercom_client: IntercomClient,
    source_channel_type: str | None = None,
) -> dict[str, Any]:
    """
    Build enriched context for Studio Chat API.

    Fetches additional contact and conversation data from Intercom
    based on the assistant's context configuration.

    Args:
        webhook_data: Parsed webhook data
        assistant: Assistant configuration with context settings
        intercom_client: Intercom API client
        source_channel_type: Channel type from source (whatsapp, email, etc.)

    Returns:
        Context dictionary to send to Studio Chat
    """
    context_config: ContextConfig = assistant.context
    context: dict[str, Any] = {}

    # Add static values first
    context.update(context_config.static)

    # Always include source channel type
    if source_channel_type:
        # Remap "conversation" to "intercom_in_app" for clarity
        channel = (
            "intercom_in_app" if source_channel_type == "conversation" else source_channel_type
        )
        context["source_channel"] = channel

    # Fetch and extract contact attributes if configured
    if context_config.contact_attributes and webhook_data.contact:
        try:
            contact_data = await intercom_client.get_contact(webhook_data.contact.id)
            contact_attrs = extract_attributes(contact_data, context_config.contact_attributes)
            if contact_attrs:
                context["contact"] = contact_attrs
                logger.debug(
                    "Contact context enriched for {}: {}",
                    webhook_data.contact.id,
                    list(contact_attrs.keys()),
                )
        except Exception as e:
            logger.warning("Contact enrichment failed for {}: {}", webhook_data.contact.id, e)

    # Fetch and extract conversation attributes if configured
    if context_config.conversation_attributes:
        try:
            conversation_data = await intercom_client.get_conversation(webhook_data.conversation_id)
            conv_attrs = extract_attributes(
                conversation_data, context_config.conversation_attributes
            )
            if conv_attrs:
                context["conversation"] = conv_attrs
                logger.debug(
                    "Conversation context enriched for {}: {}",
                    webhook_data.conversation_id,
                    list(conv_attrs.keys()),
                )
        except Exception as e:
            logger.warning(
                "Conversation enrichment failed for {}: {}", webhook_data.conversation_id, e
            )

    # Fallback: include basic contact info from webhook if no enrichment configured
    if "contact" not in context and webhook_data.contact:
        basic_contact: dict[str, Any] = {}
        if webhook_data.contact.name:
            basic_contact["name"] = webhook_data.contact.name
        if webhook_data.contact.email:
            basic_contact["email"] = webhook_data.contact.email
        if basic_contact:
            context["contact"] = basic_contact

    return context
