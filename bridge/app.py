"""FastAPI application for Intercom Studio Chat Bridge.

Architecture Overview
---------------------
This application bridges Intercom conversations with Studio Chat AI assistants.

Request Flow:
1. Intercom sends webhook to /webhooks/intercom
2. We return 200 immediately (Intercom has 5-second timeout, retries otherwise)
3. Background task processes the webhook:
   - For assignment webhooks: fetch conversation to get user message
   - Match routing rules to find the right assistant
   - Send message to Studio Chat API
   - Send AI response back to Intercom

Why Background Processing:
- Intercom webhooks timeout after 5 seconds and retry
- Full processing (fetch conversation + AI response + reply) takes ~5-10 seconds
- Without background processing, we'd get duplicate webhooks from retries

Message Extraction:
- For conversation.admin.assigned webhooks, the message is NOT in the payload
- We fetch the full conversation via GET /conversations/{id}
- Extract the last user message that hasn't been replied to yet
- Check both conversation_parts (follow-up messages) and source (initial message)
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from loguru import logger

from .config import ConfigError, load_config
from .constants import (
    DEFAULT_HTTP_MAX_CONNECTIONS,
    DEFAULT_HTTP_MAX_KEEPALIVE,
    DEFAULT_HTTP_TIMEOUT_CONNECT,
    DEFAULT_MEDIA_HANDOFF_MESSAGE,
    DEFAULT_MEDIA_HANDOFF_MESSAGES,
    FIRST_SEEN_NOTE_TEMPLATE,
    MEDIA_HANDOFF_REASONS,
    PART_TYPE_COMMENT,
    STUDIO_CHAT_CHATLOG_URL_TEMPLATE,
    USER_AUTHOR_TYPES,
)
from .context import build_context
from .intercom import IntercomActions, IntercomClient, parse_webhook
from .intercom.webhook import WebhookParseError
from .models import AppConfig, StudioChatResponse
from .routing import find_matching_assistant, should_route_to_assistant
from .studio_chat import StudioChatClient, process_events
from .studio_chat.client import (
    StudioChatConflictError,
    StudioChatError,
    StudioChatUnavailableError,
)
from .utils import bind_context, clear_context
from .utils.html import (
    extract_image_urls,
    is_audio_message,
    is_image_message,
    is_video_message,
    is_whatsapp_error,
    is_whatsapp_reaction,
    strip_html_tags,
)
from .utils.logging import setup_logging

# Configure logging format based on environment
setup_logging()


@dataclass
class MessageExtractionResult:
    """Result of extracting a user message from a conversation."""

    message: str | None = None
    has_media: bool = False
    media_type: str | None = None  # "image", "audio", "video", "attachment"
    image_urls: list[str] | None = None  # URLs of images in the message
    admin_assignee_id: str | None = None  # Current admin assigned to conversation
    tags: list[str] = field(default_factory=list)  # Tags from API-fetched conversation
    source_channel_type: str | None = (
        None  # Channel type from source (conversation, whatsapp, email, etc.)
    )


# Global state
_http_client: httpx.AsyncClient | None = None
_config: AppConfig | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get the shared HTTP client."""
    if _http_client is None:
        raise RuntimeError("HTTP client not initialized")
    return _http_client


def get_config() -> AppConfig:
    """Get the application configuration."""
    if _config is None:
        raise RuntimeError("Configuration not loaded")
    return _config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown."""
    global _http_client, _config

    # Load configuration
    try:
        _config = load_config()
        # Reconfigure logging with level from config
        setup_logging(level=_config.logging.level)
        logger.info(
            "Configuration loaded: assistants={}, log_level={}",
            len(_config.assistants),
            _config.logging.level,
        )
        logger.debug("Debug logging enabled")
    except ConfigError as e:
        logger.error("Configuration error: {}", str(e))
        raise

    # Create HTTP client with connection pooling
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            timeout=_config.studio_chat.timeout_seconds,
            connect=DEFAULT_HTTP_TIMEOUT_CONNECT,
        ),
        limits=httpx.Limits(
            max_connections=DEFAULT_HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=DEFAULT_HTTP_MAX_KEEPALIVE,
        ),
    )

    logger.info("Application started")

    yield

    # Cleanup
    if _http_client:
        await _http_client.aclose()
        logger.info("HTTP client closed")


# Create FastAPI app
app = FastAPI(
    title="Intercom Studio Chat Bridge",
    description="Lightweight middleware connecting Intercom with AI Studio assistants",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Response:
    """Log HTTP requests."""
    response: Response = await call_next(request)
    logger.info("{} {} {}", request.method, request.url.path, response.status_code)
    return response


@app.get("/health")
async def health_check() -> dict[str, str]:
    """
    Liveness probe - checks if the service is running.

    Returns 200 if the service is alive. Use this for Kubernetes
    liveness probes or basic load balancer health checks.
    """
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check() -> Response:
    """
    Readiness probe - checks if the service can handle requests.

    Validates:
    - Configuration is loaded
    - Studio Chat API is reachable

    Returns 200 if ready, 503 if not ready.
    Use this for Kubernetes readiness probes.
    """
    import json

    config = get_config()
    http_client = get_http_client()

    checks: dict[str, Any] = {
        "config": {"status": "ok", "assistants": len(config.assistants)},
        "studio_chat": {"status": "unknown"},
    }

    # Check Studio Chat API connectivity
    try:
        response = await http_client.get(
            f"{config.studio_chat.base_url}/readiness",
            timeout=5.0,
        )
        if response.is_success:
            data = response.json()
            checks["studio_chat"] = {
                "status": "ok",
                "api_version": data.get("version"),
            }
        else:
            checks["studio_chat"] = {
                "status": "error",
                "error": f"HTTP {response.status_code}",
            }
    except Exception as e:
        checks["studio_chat"] = {
            "status": "error",
            "error": str(e),
        }

    # Determine overall status
    all_ok = all(check.get("status") == "ok" for check in checks.values())
    status_code = 200 if all_ok else 503

    return Response(
        content=json.dumps({"status": "ready" if all_ok else "not_ready", "checks": checks}),
        status_code=status_code,
        media_type="application/json",
    )


async def _fetch_and_verify_conversation(
    webhook_data: Any,
    intercom_client: IntercomClient,
) -> MessageExtractionResult:
    """
    Fetch conversation from API and extract/verify the user message.

    Security: Intercom webhooks are NOT signed. We always fetch from API
    and verify against the webhook hint. If they don't match, we reject.

    Args:
        webhook_data: Parsed webhook data with conversation_id and optional hint
        intercom_client: Client for Intercom API calls

    Returns:
        MessageExtractionResult with message text and/or media info
    """
    conversation_id = webhook_data.conversation_id

    logger.info("Fetching conversation")

    try:
        conversation = await intercom_client.get_conversation(conversation_id)
    except Exception as e:
        logger.error("Conversation fetch failed: {}", e)
        return MessageExtractionResult()

    # Log conversation structure for debugging
    conv_parts = conversation.get("conversation_parts", {}).get("conversation_parts", [])
    source = conversation.get("source", {})
    admin_assignee_id = conversation.get("admin_assignee_id")
    logger.info(
        "Conversation fetched: parts={}, has_source={}, source_author={}, admin_assignee={}",
        len(conv_parts),
        bool(source),
        source.get("author", {}).get("type"),
        admin_assignee_id,
    )

    # Log available fields (keys only, no values) for observability
    logger.info("Conversation fields: {}", sorted(conversation.keys()))
    if source:
        logger.info("Source fields: {}", sorted(source.keys()))
        logger.info(
            "Source channel: delivered_as={}, type={}",
            source.get("delivered_as"),
            source.get("type"),
        )
    conv_custom_attrs = conversation.get("custom_attributes")
    if isinstance(conv_custom_attrs, dict) and conv_custom_attrs:
        logger.info("Conversation custom_attributes fields: {}", sorted(conv_custom_attrs.keys()))

    contacts_list = conversation.get("contacts", {}).get("contacts", [])
    if contacts_list:
        contact_id = contacts_list[0].get("id")
        if contact_id:
            try:
                full_contact = await intercom_client.get_contact(contact_id)
                logger.info("Contact fields: {}", sorted(full_contact.keys()))
                contact_custom_attrs = full_contact.get("custom_attributes")
                if isinstance(contact_custom_attrs, dict) and contact_custom_attrs:
                    logger.info(
                        "Contact custom_attributes fields: {}",
                        sorted(contact_custom_attrs.keys()),
                    )
            except Exception as e:
                logger.warning("Failed to fetch contact for field logging: {}", e)

    # Extract message from API (source of truth)
    result = _extract_last_user_message(conversation)
    # Include admin assignee from fetched conversation (trusted source)
    result.admin_assignee_id = str(admin_assignee_id) if admin_assignee_id else None

    # Extract tags from fetched conversation (trusted source, not webhook)
    api_tags_data = conversation.get("tags", {}).get("tags", [])
    result.tags = [tag.get("name", "") for tag in api_tags_data if tag.get("name")]

    # Extract source channel type (whatsapp, conversation, email, etc.)
    result.source_channel_type = source.get("type")

    if result.has_media:
        logger.info("Media message detected: type={}", result.media_type)
        return result

    if not result.message:
        logger.info("No user message in conversation")
        return MessageExtractionResult()

    # Verify against webhook hint if available (security check)
    if webhook_data.webhook_message_hint:
        if webhook_data.webhook_message_hint != result.message:
            logger.error(
                "Webhook/API message mismatch: webhook_len={}, api_len={}",
                len(webhook_data.webhook_message_hint),
                len(result.message),
            )
            # Security: Don't process if webhook doesn't match API (possible spoofing)
            return MessageExtractionResult()

    logger.info("Message extracted: len={}", len(result.message))
    return result


async def _send_to_studio_chat(
    conversation_id: str,
    message: str,
    context: dict[str, Any],
    assistant: Any,
    studio_chat_client: StudioChatClient,
    intercom_actions: IntercomActions,
    attachments: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
) -> StudioChatResponse | None:
    """
    Send message to Studio Chat and handle errors with fallback.

    Args:
        conversation_id: The conversation ID
        message: User message to send
        context: Enriched context for the AI
        assistant: Assistant configuration
        studio_chat_client: Client for Studio Chat API
        intercom_actions: Actions executor for fallback
        attachments: Optional list of attachments (e.g., images) to send
        tags: Optional list of conversation tags from Intercom

    Returns:
        StudioChatResponse if successful, None if failed (fallback executed)
    """
    try:
        return await studio_chat_client.send_message(
            playbook_id=assistant.playbook_id,
            conversation_id=conversation_id,
            user_message=message,
            context=context,
            attachments=attachments,
            tags=tags,
        )
    except StudioChatConflictError:
        # New message arrived while processing, ignore this response
        logger.info("Conflict ignored")
        return None
    except StudioChatUnavailableError as e:
        logger.warning("Studio Chat unavailable: retry_after={}", e.retry_after)
        await intercom_actions.execute_fallback(
            conversation_id=conversation_id,
            assistant=assistant,
        )
        return None
    except StudioChatError as e:
        logger.error("Studio Chat error: {}", e)
        await intercom_actions.execute_fallback(
            conversation_id=conversation_id,
            assistant=assistant,
        )
        return None


async def _add_first_seen_note(
    conversation_id: str,
    admin_id: str | int,
    intercom_actions: IntercomActions,
) -> None:
    """Add private note with Studio Chat chatlog link on first message."""
    chatlog_url = STUDIO_CHAT_CHATLOG_URL_TEMPLATE.format(conversation_id=conversation_id)
    note = FIRST_SEEN_NOTE_TEMPLATE.format(url=chatlog_url)

    try:
        await intercom_actions.send_note(
            conversation_id=conversation_id,
            admin_id=admin_id,
            note=note,
        )
    except Exception as e:
        logger.warning("First seen note failed: {}", e)


async def process_webhook(
    webhook_data: Any,
    assistant: Any,
    http_client: httpx.AsyncClient,
    config: AppConfig,
) -> None:
    """
    Process webhook in the background.

    This is the main orchestrator for webhook processing. It coordinates:
    1. Fetching and verifying the conversation from Intercom API
    2. Checking rollout rules
    3. Building context and sending to Studio Chat
    4. Processing the AI response and executing actions

    Security: Intercom webhooks are NOT signed. The webhook is only a notification.
    We ALWAYS fetch the actual message from the API and verify against the webhook hint.
    """
    conversation_id = webhook_data.conversation_id

    # Bind context for all log messages in this request
    bind_context(
        conversation_id=conversation_id,
        playbook_id=assistant.playbook_id,
    )

    try:
        # Create clients
        intercom_client = IntercomClient(config.intercom, http_client)
        intercom_actions = IntercomActions(intercom_client)
        studio_chat_client = StudioChatClient(config.studio_chat, http_client)

        # Step 1: Fetch and verify conversation from API
        extraction_result = await _fetch_and_verify_conversation(webhook_data, intercom_client)

        # Step 1a: Handle non-image media messages - trigger immediate handoff
        # Images are now supported and will be sent to Studio Chat
        if extraction_result.has_media and extraction_result.media_type != "image":
            media_type = extraction_result.media_type or "attachment"
            logger.info("Non-image media triggers handoff: type={}", media_type)

            # Get custom message from config or use default
            custom_messages = assistant.handoff.media_handoff_messages
            if media_type in custom_messages:
                handoff_message = custom_messages[media_type]
            elif media_type in DEFAULT_MEDIA_HANDOFF_MESSAGES:
                handoff_message = DEFAULT_MEDIA_HANDOFF_MESSAGES[media_type]
            else:
                handoff_message = DEFAULT_MEDIA_HANDOFF_MESSAGE

            # Send user-facing message before handoff
            await intercom_actions.send_text(
                conversation_id=conversation_id,
                admin_id=assistant.admin_id,
                message=handoff_message,
            )

            # Execute handoff actions
            reason = MEDIA_HANDOFF_REASONS.get(media_type, "📎")
            await intercom_actions.execute_handoff(
                conversation_id=conversation_id,
                assistant=assistant,
                reason=reason,
                conversation_tags=webhook_data.tags,
            )
            return

        # For images, we need either a message or image URLs
        # For non-images, we need a message
        has_image = extraction_result.media_type == "image" and extraction_result.image_urls
        if not extraction_result.message and not has_image:
            return

        # Use message if available, otherwise default for image-only messages
        message = extraction_result.message or ""
        webhook_data.message = message if message else None

        # Step 2: Check rollout
        if not should_route_to_assistant(assistant, conversation_id):
            logger.info("Rollout excluded")
            await intercom_actions.execute_fallback(
                conversation_id=conversation_id,
                assistant=assistant,
            )
            return

        # Step 2a: Ensure conversation is assigned to AI admin
        # Don't rely on Intercom's "self-assigned by replying" setting
        if not extraction_result.admin_assignee_id:
            try:
                await intercom_actions.assign_self(
                    conversation_id=conversation_id,
                    admin_id=assistant.admin_id,
                )
            except Exception as e:
                logger.warning("Failed to assign conversation to admin: {}", e)

        # Step 3: Build context and send to Studio Chat
        context = await build_context(
            webhook_data=webhook_data,
            assistant=assistant,
            intercom_client=intercom_client,
            source_channel_type=extraction_result.source_channel_type,
        )

        # Build attachments for images (download and encode to base64)
        attachments = None
        if extraction_result.image_urls:
            attachments = await _build_image_attachments(extraction_result.image_urls, http_client)
            if attachments:
                logger.info("Sending {} image(s) to Studio Chat", len(attachments))

        # Build tags list if configured (from API-fetched conversation, not webhook)
        tags = extraction_result.tags if assistant.send_tags else None

        response = await _send_to_studio_chat(
            conversation_id=conversation_id,
            message=message,
            context=context,
            assistant=assistant,
            studio_chat_client=studio_chat_client,
            intercom_actions=intercom_actions,
            attachments=attachments,
            tags=tags,
        )
        if not response:
            return

        # Step 4: Add first-seen note if applicable
        if response.first_seen:
            await _add_first_seen_note(conversation_id, assistant.admin_id, intercom_actions)

        # Step 5: Process AI response events
        result = await process_events(
            response=response,
            assistant=assistant,
            conversation_id=conversation_id,
            intercom_actions=intercom_actions,
        )

        # Step 6: Handle handoff if requested
        if result.handoff_requested:
            await intercom_actions.execute_handoff(
                conversation_id=conversation_id,
                assistant=assistant,
                reason=result.handoff_reason,
                conversation_tags=webhook_data.tags,
            )
            logger.info("Webhook processed: outcome=handoff")
        else:
            logger.info("Webhook processed: outcome=success")
    finally:
        # Always clear context when done
        clear_context()


@app.post("/webhooks/intercom")
async def intercom_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """
    Handle incoming Intercom webhooks.

    This endpoint receives conversation events from Intercom, routes them
    to the appropriate AI assistant, and sends responses back.

    Returns 200 immediately to avoid Intercom retries (5 second timeout),
    then processes the webhook asynchronously.
    """
    config = get_config()
    http_client = get_http_client()

    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("JSON parse error: {}", e)
        raise HTTPException(status_code=400, detail="Invalid JSON") from e

    # Parse webhook
    try:
        webhook_data = parse_webhook(payload)
    except WebhookParseError as e:
        logger.error("Webhook parse error: {}", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    if webhook_data is None:
        # Webhook should be ignored (unsupported topic, empty message, etc.)
        return Response(status_code=200)

    # Bind context early so all logs have conversation_id
    bind_context(conversation_id=webhook_data.conversation_id)

    logger.info(
        "Webhook received: topic={}, has_message={}",
        webhook_data.topic,
        webhook_data.message is not None,
    )

    # Find matching assistant
    assistant = find_matching_assistant(config.assistants, webhook_data)

    if assistant is None:
        logger.info("No assistant matched - discarding webhook")
        return Response(status_code=200)

    logger.info("Assistant matched: playbook={}", assistant.playbook_id)

    # Schedule background processing and return immediately
    # This ensures we respond within Intercom's 5-second timeout
    background_tasks.add_task(
        process_webhook,
        webhook_data=webhook_data,
        assistant=assistant,
        http_client=http_client,
        config=config,
    )

    return Response(status_code=200)


def _detect_media_type(body: str, attachments: list[Any] | None) -> str | None:
    """Detect the type of media in a message."""
    if is_image_message(body):
        return "image"
    if is_audio_message(body):
        return "audio"
    if is_video_message(body):
        return "video"
    if attachments and len(attachments) > 0:
        # Check if all attachments are images (e.g. WhatsApp sends images as attachments)
        if all(_is_image_attachment(att) for att in attachments):
            return "image"
        return "attachment"
    return None


def _is_image_attachment(att: Any) -> bool:
    """Check if an attachment is an image based on content_type or URL."""
    if not isinstance(att, dict):
        return False
    content_type = att.get("content_type", "")
    if content_type and content_type.startswith("image/"):
        return True
    # Fallback: check URL extension
    url = (att.get("url") or "").lower().split("?")[0]
    return url.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))


def _extract_attachment_image_urls(attachments: list[Any]) -> list[str]:
    """Extract image URLs from attachment objects."""
    urls = []
    for att in attachments:
        if isinstance(att, dict) and _is_image_attachment(att):
            url = att.get("url", "")
            if url:
                urls.append(url)
    return urls


async def _build_image_attachments(image_urls: list[str], http_client: Any) -> list[dict[str, Any]]:
    """
    Build Studio Chat attachment objects from image URLs.

    Downloads images from URLs and converts them to base64.

    Args:
        image_urls: List of image URLs from Intercom
        http_client: HTTP client to download images

    Returns:
        List of attachment dicts for Studio Chat API with base64-encoded data
    """
    import base64
    import html

    attachments = []
    for url in image_urls:
        try:
            # Unescape HTML entities in URL (Intercom uses &amp; for &)
            clean_url = html.unescape(url)

            # Download the image
            logger.debug("Downloading image: {}", clean_url[:100])
            response = await http_client.get(clean_url)

            if not response.is_success:
                logger.warning("Failed to download image: status={}", response.status_code)
                continue

            # Get content type from response headers or infer from URL
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if not content_type or not content_type.startswith("image/"):
                # Infer from URL
                url_lower = url.lower()
                if ".png" in url_lower:
                    content_type = "image/png"
                elif ".gif" in url_lower:
                    content_type = "image/gif"
                elif ".webp" in url_lower:
                    content_type = "image/webp"
                else:
                    content_type = "image/jpeg"

            # Encode to base64
            image_data = base64.b64encode(response.content).decode("utf-8")

            attachments.append(
                {
                    "type": "image",
                    "media_type": content_type,
                    "data": image_data,
                }
            )
            logger.debug(
                "Image encoded: type={}, size={} bytes", content_type, len(response.content)
            )

        except Exception as e:
            logger.error("Error downloading image: {}", str(e))
            continue

    return attachments


def _find_last_user_message_in_parts(
    parts: list[dict[str, Any]],
) -> tuple[str | None, int, bool, str | None, list[str] | None]:
    """
    Find the last user message in conversation parts.

    Scans through all parts and returns the last message from a user
    (not admin/bot) along with its index position. Filters out WhatsApp
    reactions and error messages. Also detects media messages (images,
    audio, video, attachments) that cannot be processed by AI.

    Args:
        parts: List of conversation parts from Intercom API

    Returns:
        Tuple of (message_text, index, has_media, media_type, image_urls)
        - message_text: The extracted text message, or None if no text
        - index: The index of the last user part, or -1 if none found
        - has_media: True if the message contains media
        - media_type: Type of media ("image", "audio", "video", "attachment") or None
        - image_urls: List of image URLs if media_type is "image", else None
    """
    last_message = None
    last_index = -1
    last_has_media = False
    last_media_type: str | None = None
    last_image_urls: list[str] | None = None

    # Collect author types for debugging
    author_types = []

    for i, part in enumerate(parts):
        author_type = part.get("author", {}).get("type", "")
        part_type = part.get("part_type", "")
        author_types.append(f"{i}:{author_type}:{part_type}")

        if author_type in USER_AUTHOR_TYPES:
            body = part.get("body", "")
            attachments = part.get("attachments", [])

            # Log metadata for debugging (no PII)
            if body or attachments:
                logger.debug(
                    "Part {}: body_len={}, attachments={}",
                    i,
                    len(body) if body else 0,
                    len(attachments),
                )

            # Log attachment details to understand structure
            if attachments:
                for j, att in enumerate(attachments):
                    att_keys = sorted(att.keys()) if isinstance(att, dict) else str(type(att))
                    ct = att.get("content_type", "N/A") if isinstance(att, dict) else "N/A"
                    att_type = att.get("type", "N/A") if isinstance(att, dict) else "N/A"
                    att_url = att.get("url", "")[:80] if isinstance(att, dict) else "N/A"
                    logger.info(
                        "Part {} attachment {}: keys={}, content_type={}, type={}, url={}",
                        i,
                        j,
                        att_keys,
                        ct,
                        att_type,
                        att_url,
                    )

            # Check for media content
            media_type = _detect_media_type(body, attachments)
            if media_type:
                logger.info("Part {} contains media: type={}", i, media_type)
                last_index = i
                last_has_media = True
                last_media_type = media_type
                # Extract image URLs if it's an image message
                if media_type == "image":
                    # Try inline <img> tags first, then attachment URLs
                    last_image_urls = extract_image_urls(body) if body else []
                    if not last_image_urls and attachments:
                        last_image_urls = _extract_attachment_image_urls(attachments)
                    # Also extract any accompanying text
                    text = strip_html_tags(body)
                    last_message = text if text else None
                else:
                    last_message = None  # Non-image media don't have text we can process
                    last_image_urls = None
                continue

            if body:
                # Filter out WhatsApp reactions and errors
                if is_whatsapp_reaction(body):
                    logger.debug("Part {} is WhatsApp reaction, skipping", i)
                    continue
                if is_whatsapp_error(body):
                    logger.debug("Part {} is WhatsApp error, skipping", i)
                    continue
                last_message = strip_html_tags(body)
                last_index = i
                last_has_media = False
                last_media_type = None
                last_image_urls = None
            else:
                logger.debug("Part {} from user has empty body", i)

    logger.debug("Parts scan: authors={}, last_user_idx={}", author_types, last_index)

    return last_message, last_index, last_has_media, last_media_type, last_image_urls


def _has_admin_reply_after_index(parts: list[dict[str, Any]], index: int) -> bool:
    """
    Check if any admin/bot has replied with a comment after the given index.

    Only counts actual comment replies, not other events like assignments,
    notes, or attribute updates which are "noise" and don't constitute a reply.

    Args:
        parts: List of conversation parts
        index: The index of the user message to check after

    Returns:
        True if an admin comment reply exists after the index
    """
    for part in parts[index + 1 :]:
        author_type = part.get("author", {}).get("type", "")
        part_type = part.get("part_type", "")
        if author_type not in USER_AUTHOR_TYPES and part_type == PART_TYPE_COMMENT:
            return True
    return False


def _has_admin_comment_reply(parts: list[dict[str, Any]]) -> bool:
    """
    Check if any admin has posted a comment reply in the parts.

    Used for source message handling - if any admin comment exists,
    the source message has already been replied to.

    Args:
        parts: List of conversation parts

    Returns:
        True if an admin comment exists in the parts
    """
    for part in parts:
        author_type = part.get("author", {}).get("type", "")
        part_type = part.get("part_type", "")
        if author_type not in USER_AUTHOR_TYPES and part_type == PART_TYPE_COMMENT:
            return True
    return False


def _extract_source_message(
    conversation: dict[str, Any],
) -> tuple[str | None, bool, str | None, list[str] | None]:
    """
    Extract the initial message from conversation source.

    The source is the first message that started the conversation.
    Only returns the message if it's from a user (not admin-initiated).
    Filters out WhatsApp reactions and error messages.

    Args:
        conversation: The conversation data from Intercom API

    Returns:
        Tuple of (message_text, has_media, media_type, image_urls)
    """
    source = conversation.get("source", {})
    if source.get("author", {}).get("type") in USER_AUTHOR_TYPES:
        body = source.get("body", "")
        attachments = source.get("attachments", [])

        # Log metadata for debugging (no PII)
        if body or attachments:
            logger.debug(
                "Source: body_len={}, attachments={}",
                len(body) if body else 0,
                len(attachments),
            )

        # Log attachment details to understand structure
        if attachments:
            for j, att in enumerate(attachments):
                att_keys = sorted(att.keys()) if isinstance(att, dict) else str(type(att))
                ct = att.get("content_type", "N/A") if isinstance(att, dict) else "N/A"
                att_type = att.get("type", "N/A") if isinstance(att, dict) else "N/A"
                att_url = att.get("url", "")[:80] if isinstance(att, dict) else "N/A"
                logger.info(
                    "Source attachment {}: keys={}, content_type={}, type={}, url={}",
                    j,
                    att_keys,
                    ct,
                    att_type,
                    att_url,
                )

        # Check for media content
        media_type = _detect_media_type(body, attachments)
        if media_type:
            logger.info("Source contains media: type={}", media_type)
            # Extract image URLs if it's an image message
            if media_type == "image":
                # Try inline <img> tags first, then attachment URLs
                image_urls = extract_image_urls(body) if body else []
                if not image_urls and attachments:
                    image_urls = _extract_attachment_image_urls(attachments)
                # Also extract any accompanying text
                text = strip_html_tags(body)
                return text if text else None, True, media_type, image_urls
            return None, True, media_type, None

        if body:
            # Filter out WhatsApp reactions and errors
            if is_whatsapp_reaction(body) or is_whatsapp_error(body):
                return None, False, None, None
            return strip_html_tags(body), False, None, None

    return None, False, None, None


def _extract_last_user_message(conversation: dict[str, Any]) -> MessageExtractionResult:
    """
    Extract the last user message from a conversation that needs a response.

    Intercom Conversation Structure:
    - source: The initial message that started the conversation
    - conversation_parts: All subsequent messages (user replies, admin replies, notes, etc.)

    Logic:
    1. Search conversation_parts for the last user message
    2. If found, check if any admin replied AFTER it - if so, return empty (already handled)
    3. If no user message in parts, check source (initial message)
    4. For source, check if any admin comment exists in parts - if so, return empty

    This prevents:
    - Responding to messages that already have a reply
    - Processing the same message twice in race conditions

    Args:
        conversation: The conversation data from Intercom API

    Returns:
        MessageExtractionResult with message text and/or media info
    """
    parts = conversation.get("conversation_parts", {}).get("conversation_parts", [])

    # Try to find message in conversation parts first
    last_message, last_index, has_media, media_type, image_urls = _find_last_user_message_in_parts(
        parts
    )

    if last_index >= 0:  # Found a user part
        if _has_admin_reply_after_index(parts, last_index):
            logger.debug(
                "Skipping: user message at idx {} already has admin reply after", last_index
            )
            return MessageExtractionResult()

        if has_media:
            logger.debug("Found media message in parts at idx {}", last_index)
            return MessageExtractionResult(
                message=last_message,
                has_media=True,
                media_type=media_type,
                image_urls=image_urls,
            )

        if last_message:
            logger.debug("Found user message in parts at idx {}", last_index)
            return MessageExtractionResult(message=last_message)

    logger.debug("No user message found in parts, checking source")

    # Fall back to source (initial message)
    source_message, source_has_media, source_media_type, source_image_urls = (
        _extract_source_message(conversation)
    )

    if source_has_media:
        if _has_admin_comment_reply(parts):
            logger.debug("Skipping: source media already has admin comment reply")
            return MessageExtractionResult()
        logger.debug("Using source media")
        return MessageExtractionResult(
            message=source_message,
            has_media=True,
            media_type=source_media_type,
            image_urls=source_image_urls,
        )

    if source_message is not None:
        if _has_admin_comment_reply(parts):
            logger.debug("Skipping: source message already has admin comment reply")
            return MessageExtractionResult()
        logger.debug("Using source message")
        return MessageExtractionResult(message=source_message)

    logger.debug("No source message available")
    return MessageExtractionResult()


def main() -> None:
    """Entry point for the application."""
    load_dotenv()
    import uvicorn

    # Get configuration from environment
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))

    logger.info("Starting server on {}:{}", host, port)

    uvicorn.run(
        "bridge.app:app",
        host=host,
        port=port,
        reload=os.environ.get("RELOAD", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
