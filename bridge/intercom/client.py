"""Async HTTP client for Intercom API."""

from typing import Any

import httpx
from loguru import logger

from ..models import IntercomConfig

INTERCOM_API_BASE = "https://api.intercom.io"


class IntercomError(Exception):
    """Base exception for Intercom errors."""

    pass


class IntercomClient:
    """Async client for Intercom API using httpx."""

    def __init__(self, config: IntercomConfig, http_client: httpx.AsyncClient):
        """
        Initialize the Intercom client.

        Args:
            config: Intercom configuration with access token
            http_client: Shared async HTTP client
        """
        self.config = config
        self.client = http_client
        self.base_url = INTERCOM_API_BASE

    def _get_headers(self) -> dict[str, str]:
        """Get common headers for Intercom API requests."""
        return {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Intercom-Version": "2.11",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Make an authenticated request to the Intercom API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path (without base URL)
            json: JSON body for the request
            **kwargs: Additional arguments for httpx

        Returns:
            JSON response as a dictionary

        Raises:
            IntercomError: If the request fails
        """
        url = f"{self.base_url}{path}"
        headers = self._get_headers()

        try:
            response = await self.client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                **kwargs,
            )
        except httpx.RequestError as e:
            logger.error("Intercom request error: path={}, error={}", path, e)
            raise IntercomError(f"Request failed: {e}") from e

        if not response.is_success:
            # Log response body for debugging (Intercom includes error details)
            body = response.text[:500] if response.text else "(empty)"
            logger.error(
                "Intercom API error: path={}, status={}, body={}",
                path,
                response.status_code,
                body,
            )
            raise IntercomError(f"API error: {response.status_code}")

        return response.json() if response.text else {}

    async def reply_to_conversation(
        self,
        conversation_id: str,
        admin_id: str,
        message: str,
        message_type: str = "comment",
    ) -> dict[str, Any]:
        """
        Reply to a conversation.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin/bot ID sending the reply
            message: The message content (HTML supported)
            message_type: "comment" for user-visible, "note" for internal

        Returns:
            API response
        """
        return await self._request(
            "POST",
            f"/conversations/{conversation_id}/reply",
            json={
                "type": "admin",
                "admin_id": admin_id,
                "message_type": message_type,
                "body": message,
            },
        )

    async def attach_file_to_conversation(
        self,
        conversation_id: str,
        admin_id: str,
        file_url: str,
    ) -> dict[str, Any]:
        """
        Attach a file (image) to a conversation reply.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin/bot ID sending the reply
            file_url: URL of the file to attach

        Returns:
            API response
        """
        return await self._request(
            "POST",
            f"/conversations/{conversation_id}/reply",
            json={
                "type": "admin",
                "admin_id": admin_id,
                "message_type": "comment",
                "attachment_urls": [file_url],
            },
        )

    async def add_tag_to_conversation(
        self,
        conversation_id: str,
        admin_id: str,
        tag_id: str,
    ) -> dict[str, Any]:
        """
        Add a tag to a conversation.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the action
            tag_id: The tag ID to add

        Returns:
            API response
        """
        return await self._request(
            "POST",
            f"/conversations/{conversation_id}/tags",
            json={
                "id": tag_id,
                "admin_id": admin_id,
            },
        )

    async def get_or_create_tag(self, tag_name: str) -> str:
        """
        Get a tag by name, or create it if it doesn't exist.

        Args:
            tag_name: The name of the tag

        Returns:
            The tag ID
        """
        # First, try to find the tag
        response = await self._request("GET", "/tags")
        tags = response.get("data", [])

        for tag in tags:
            if tag.get("name") == tag_name:
                return str(tag["id"])

        # Tag doesn't exist, create it
        response = await self._request(
            "POST",
            "/tags",
            json={"name": tag_name},
        )
        return str(response["id"])

    async def assign_conversation(
        self,
        conversation_id: str,
        admin_id: str,
        assignee_id: str | None = None,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Assign a conversation to an admin or team (inbox).

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the assignment
            assignee_id: Optional admin ID to assign to
            team_id: Optional team ID (inbox) to assign to

        Returns:
            API response
        """
        body: dict[str, Any] = {
            "admin_id": admin_id,
            "message_type": "assignment",
            "body": "",
        }

        # Set type and assignee based on assignment target
        if assignee_id:
            body["type"] = "admin"
            body["assignee_id"] = assignee_id
        elif team_id:
            body["type"] = "team"
            body["assignee_id"] = team_id
        else:
            body["type"] = "admin"

        return await self._request(
            "POST",
            f"/conversations/{conversation_id}/parts",
            json=body,
        )

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """
        Get conversation details.

        Args:
            conversation_id: The conversation ID

        Returns:
            Conversation data
        """
        return await self._request("GET", f"/conversations/{conversation_id}")

    async def get_contact(self, contact_id: str) -> dict[str, Any]:
        """
        Get contact details including custom attributes.

        Args:
            contact_id: The contact ID

        Returns:
            Contact data including custom_attributes, email, name, phone, etc.
        """
        return await self._request("GET", f"/contacts/{contact_id}")

    async def unassign_admin(
        self,
        conversation_id: str,
        admin_id: str,
    ) -> dict[str, Any]:
        """
        Unassign the admin from a conversation.

        Uses assignee_id="0" to remove the admin assignment while keeping
        any team assignment intact.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the unassignment

        Returns:
            API response
        """
        return await self._request(
            "POST",
            f"/conversations/{conversation_id}/parts",
            json={
                "admin_id": admin_id,
                "message_type": "assignment",
                "type": "admin",
                "assignee_id": "0",
                "body": "",
            },
        )
