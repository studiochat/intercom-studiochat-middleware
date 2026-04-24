"""Async client for Studio Chat (AI Studio) API."""

from typing import Any

import httpx
from loguru import logger

from ..models import StudioChatConfig, StudioChatResponse


class StudioChatError(Exception):
    """Base exception for Studio Chat errors."""

    pass


class StudioChatConflictError(StudioChatError):
    """Raised when a new message arrives while processing (409 Conflict)."""

    pass


class StudioChatUnavailableError(StudioChatError):
    """Raised when Studio Chat is unavailable (503 Service Unavailable)."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class StudioChatClient:
    """Async client for communicating with Studio Chat API."""

    def __init__(self, config: StudioChatConfig, http_client: httpx.AsyncClient):
        """
        Initialize the Studio Chat client.

        Args:
            config: Studio Chat configuration
            http_client: Shared async HTTP client
        """
        self.config = config
        self.client = http_client
        self.base_url = config.base_url.rstrip("/")

    async def send_message(
        self,
        playbook_id: str,
        conversation_id: str,
        user_message: str,
        context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> StudioChatResponse:
        """
        Send a message to Studio Chat and get the AI response.

        Args:
            playbook_id: The playbook/assistant ID to use
            conversation_id: Intercom conversation ID for session continuity
            user_message: The user's message (plain text)
            context: Optional context data (user name, platform, etc.)
            attachments: Optional list of attachments (e.g., images) to send.
                Each attachment should have: type, media_type, and either url or data.
            tags: Optional list of conversation tags from Intercom.

        Returns:
            StudioChatResponse with events to process

        Raises:
            StudioChatConflictError: If a new message arrived while processing (409)
            StudioChatUnavailableError: If the service is unavailable (503)
            StudioChatError: For other errors
        """
        url = f"{self.base_url}/playbooks/{playbook_id}/active/chat"

        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "user_message": user_message,
            "context": context or {},
            "is_eval": False,
        }

        if attachments:
            payload["attachments"] = attachments

        if tags:
            payload["tags"] = tags

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
        }

        logger.info(
            "Studio Chat request: playbook={}, conversation={}, msg_len={}",
            playbook_id,
            conversation_id,
            len(user_message),
        )

        try:
            response = await self.client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
        except httpx.TimeoutException as e:
            logger.error(
                "Studio Chat timeout: playbook={}, conversation={}, timeout={}s",
                playbook_id,
                conversation_id,
                self.config.timeout_seconds,
            )
            raise StudioChatUnavailableError("Request timed out") from e
        except httpx.RequestError as e:
            logger.error(
                "Studio Chat request error: playbook={}, conversation={}, error={}",
                playbook_id,
                conversation_id,
                e,
            )
            raise StudioChatError(f"Request failed: {e}") from e

        # Handle specific status codes
        if response.status_code == 409:
            logger.warning(
                "Studio Chat conflict: playbook={}, conversation={}",
                playbook_id,
                conversation_id,
            )
            raise StudioChatConflictError("New message arrived while processing")

        if response.status_code == 503:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after else None
            logger.warning(
                "Studio Chat unavailable: playbook={}, conversation={}, retry_after={}",
                playbook_id,
                conversation_id,
                retry_seconds,
            )
            raise StudioChatUnavailableError(
                "Service unavailable",
                retry_after=retry_seconds,
            )

        if response.status_code == 504:
            logger.warning(
                "Studio Chat timeout: playbook={}, conversation={}",
                playbook_id,
                conversation_id,
            )
            raise StudioChatUnavailableError("Agent timed out")

        if not response.is_success:
            logger.error(
                "Studio Chat error: playbook={}, conversation={}, status={}",
                playbook_id,
                conversation_id,
                response.status_code,
            )
            raise StudioChatError(f"API error: {response.status_code}")

        # Parse response
        try:
            data = response.json()
            result = StudioChatResponse.model_validate(data)
            logger.info(
                "Studio Chat response: playbook={}, conversation={}, events={}",
                playbook_id,
                conversation_id,
                len(result.events),
            )
            return result
        except Exception as e:
            logger.error(
                "Studio Chat parse error: playbook={}, conversation={}, error={}",
                playbook_id,
                conversation_id,
                e,
            )
            raise StudioChatError(f"Failed to parse response: {e}") from e

    async def mark_handoff(
        self,
        playbook_id: str,
        conversation_id: str,
        error_type: str = "external_handoff",
    ) -> None:
        """
        Notify Studio Chat that a conversation was handed off externally.

        Called when the bridge triggers a handoff outside the normal AI response
        flow (e.g., unsupported media types). This saves an error message to
        the conversation (visible in chat logs) and sets has_handoff=True.

        Args:
            playbook_id: The playbook/assistant ID
            conversation_id: Intercom conversation ID
            error_type: Error type for the chat log entry
        """
        url = f"{self.base_url}/playbooks/{playbook_id}/conversations/{conversation_id}/handoff"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
        }

        try:
            response = await self.client.post(
                url,
                json={"error_type": error_type},
                headers=headers,
                timeout=10,
            )
            if response.is_success:
                logger.info(
                    "Marked handoff in Studio Chat: playbook={}, conversation={}",
                    playbook_id,
                    conversation_id,
                )
            else:
                logger.warning(
                    "Failed to mark handoff: playbook={}, conversation={}, status={}",
                    playbook_id,
                    conversation_id,
                    response.status_code,
                )
        except Exception as e:
            logger.warning(
                "Failed to notify Studio Chat of handoff: playbook={}, conversation={}, error={}",
                playbook_id,
                conversation_id,
                e,
            )
