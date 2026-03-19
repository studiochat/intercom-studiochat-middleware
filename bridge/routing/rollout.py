"""Rollout control for gradual feature deployment."""

import hashlib

from loguru import logger

from ..models import AssistantConfig


def _get_bucket(conversation_id: str) -> int:
    """
    Get a deterministic bucket (0-99) for a conversation ID.

    Uses MD5 hash to ensure the same conversation always gets the same bucket.
    This provides consistent routing even across restarts.
    """
    hash_bytes = hashlib.md5(conversation_id.encode()).digest()
    # Use first 4 bytes as an integer and mod by 100
    hash_int = int.from_bytes(hash_bytes[:4], byteorder="big")
    return hash_int % 100


def should_route_to_assistant(assistant: AssistantConfig, conversation_id: str) -> bool:
    """
    Determine if a conversation should be routed to the AI assistant.

    Uses deterministic hashing so the same conversation always gets the same result.
    This prevents conversations from switching between AI and human mid-flow.

    Args:
        assistant: The assistant configuration with rollout settings
        conversation_id: The Intercom conversation ID

    Returns:
        True if the conversation should be handled by the assistant
    """
    percentage = assistant.rollout.percentage

    # Short-circuit for common cases
    if percentage <= 0:
        logger.debug(
            "Rollout disabled for {}: playbook={}",
            conversation_id,
            assistant.playbook_id,
        )
        return False

    if percentage >= 100:
        return True

    bucket = _get_bucket(conversation_id)
    should_route = bucket < percentage

    logger.debug(
        "Rollout decision for {}: playbook={}, bucket={}, percentage={}, routed={}",
        conversation_id,
        assistant.playbook_id,
        bucket,
        percentage,
        should_route,
    )

    return should_route
