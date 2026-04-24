"""Event processor for Studio Chat responses."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from ..constants import FEEDBACK_NOTE_TEMPLATE, MESSAGE_DELAY_SECONDS
from ..models import AssistantConfig, StudioChatEventType, StudioChatResponse

if TYPE_CHECKING:
    from ..intercom.actions import IntercomActions


@dataclass
class ProcessingResult:
    """Result of processing Studio Chat events."""

    messages_sent: int = 0
    notes_sent: int = 0
    tags_added: int = 0
    handoff_requested: bool = False
    handoff_reason: str | None = None
    feedback_note_sent: bool = False


async def process_events(
    response: StudioChatResponse,
    assistant: AssistantConfig,
    conversation_id: str,
    intercom_actions: "IntercomActions",
) -> ProcessingResult:
    """
    Process events from Studio Chat response and execute corresponding Intercom actions.

    Args:
        response: The Studio Chat response containing events
        assistant: The assistant configuration
        conversation_id: The Intercom conversation ID
        intercom_actions: Intercom actions client for sending messages

    Returns:
        ProcessingResult with counts of actions taken
    """
    result = ProcessingResult()

    for event in response.events:
        logger.debug("Processing event: type={}", event.event_type)

        match event.event_type:
            case StudioChatEventType.MESSAGE:
                content = event.data.get("content", "")
                if content:
                    await intercom_actions.send_text(
                        conversation_id=conversation_id,
                        admin_id=assistant.admin_id,
                        message=content,
                    )
                    result.messages_sent += 1
                    # Small delay between messages for natural pacing
                    await asyncio.sleep(MESSAGE_DELAY_SECONDS)

            case StudioChatEventType.NOTE:
                content = event.data.get("content", "")
                if content:
                    await intercom_actions.send_note(
                        conversation_id=conversation_id,
                        admin_id=assistant.admin_id,
                        note=content,
                    )
                    result.notes_sent += 1

            case StudioChatEventType.LABEL:
                label = event.data.get("label", "")
                if label:
                    await intercom_actions.add_tag(
                        conversation_id=conversation_id,
                        admin_id=assistant.admin_id,
                        tag_name=label,
                    )
                    result.tags_added += 1

            case StudioChatEventType.HANDOFF_AGENT:
                result.handoff_requested = True
                result.handoff_reason = event.data.get("reason", "No reason provided")
                logger.info("Handoff requested")

            case StudioChatEventType.PRIORITY:
                priority = event.data.get("priority", "")
                logger.info("Priority update: {}", priority)
                # Priority updates could be implemented if needed

            case StudioChatEventType.IMAGE:
                image_url = event.data.get("url", "")
                if image_url:
                    await intercom_actions.send_image(
                        conversation_id=conversation_id,
                        admin_id=assistant.admin_id,
                        image_url=image_url,
                    )
                    result.messages_sent += 1

            case _:
                logger.warning("Unknown event type: {}", event.event_type)

    # Optional per-assistant feedback note pointing to the Studio Chat UI.
    # Only fires when:
    #   - the assistant opts in (include_feedback_note)
    #   - the BE returned a deep_link for this response
    #   - we actually delivered something to the user (skip empty / no-op
    #     responses so we don't clutter the thread with dead links)
    #   - we didn't request a handoff (a human is taking over — the note
    #     would be noise for them)
    if (
        assistant.include_feedback_note
        and response.deep_link
        and (result.messages_sent > 0 or result.notes_sent > 0)
        and not result.handoff_requested
    ):
        note_html = FEEDBACK_NOTE_TEMPLATE.format(url=response.deep_link)
        await intercom_actions.send_note(
            conversation_id=conversation_id,
            admin_id=assistant.admin_id,
            note=note_html,
        )
        result.feedback_note_sent = True
        logger.info("Feedback note sent with deep link")

    logger.info(
        "Events processed: msgs={}, notes={}, tags={}, handoff={}, feedback_note={}",
        result.messages_sent,
        result.notes_sent,
        result.tags_added,
        result.handoff_requested,
        result.feedback_note_sent,
    )

    return result
