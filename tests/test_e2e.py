"""End-to-end tests for the webhook endpoint."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from bridge.models import (
    Action,
    ActionType,
    AppConfig,
    AssistantConfig,
    ContextConfig,
    FallbackConfig,
    HandoffConfig,
    IntercomConfig,
    LoggingConfig,
    RolloutConfig,
    RoutingRule,
    RoutingRuleType,
    StudioChatConfig,
)


@pytest.fixture
def test_config():
    """Test configuration with one assistant."""
    return AppConfig(
        studio_chat=StudioChatConfig(
            api_key="test-api-key",
            base_url="https://api.studiochat.io",
            timeout_seconds=30,
        ),
        intercom=IntercomConfig(access_token="test-intercom-token"),
        logging=LoggingConfig(level="DEBUG", format="text"),
        assistants=[
            AssistantConfig(
                playbook_id="playbook-123",
                admin_id="admin-456",
                rollout=RolloutConfig(percentage=100),
                routing_rules=[
                    RoutingRule(type=RoutingRuleType.INBOX, inbox_id="inbox-789"),
                ],
                handoff=HandoffConfig(
                    actions=[
                        Action(type=ActionType.ADD_TAG, tag_name="ai-handoff"),
                        Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="human-inbox"),
                        Action(type=ActionType.ADD_NOTE, template="Handoff reason: {reason}"),
                    ]
                ),
                fallback=FallbackConfig(
                    actions=[
                        Action(type=ActionType.ADD_TAG, tag_name="ai-fallback"),
                        Action(type=ActionType.TRANSFER_TO_INBOX, inbox_id="fallback-inbox"),
                    ]
                ),
                context=ContextConfig(
                    contact_attributes=["email", "name", "custom_attributes.Plan"],
                    static={"source": "webhook"},
                ),
            )
        ],
    )


@pytest.fixture
def test_config_partial_rollout():
    """Test configuration with 0% rollout."""
    return AppConfig(
        studio_chat=StudioChatConfig(
            api_key="test-api-key",
            base_url="https://api.studiochat.io",
        ),
        intercom=IntercomConfig(access_token="test-intercom-token"),
        logging=LoggingConfig(level="DEBUG", format="text"),
        assistants=[
            AssistantConfig(
                playbook_id="playbook-123",
                admin_id="admin-456",
                rollout=RolloutConfig(percentage=0),  # 0% rollout
                routing_rules=[
                    RoutingRule(type=RoutingRuleType.INBOX, inbox_id="inbox-789"),
                ],
                fallback=FallbackConfig(
                    actions=[
                        Action(type=ActionType.ADD_TAG, tag_name="rollout-excluded"),
                    ]
                ),
            )
        ],
    )


@pytest.fixture
def user_replied_payload():
    """Standard user replied webhook payload."""
    return {
        "topic": "conversation.user.replied",
        "data": {
            "item": {
                "id": "conv-12345",
                "admin_assignee_id": None,
                "team_assignee_id": "inbox-789",
                "tags": {"tags": []},
                "contacts": {
                    "contacts": [
                        {
                            "id": "contact-abc",
                            "name": "John Doe",
                            "email": "john@example.com",
                        }
                    ]
                },
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            }
        },
    }


def create_mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.is_success = 200 <= status_code < 300
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = json.dumps(json_data)
    response.headers = {}
    return response


def create_mock_binary_response(content: bytes, content_type: str, status_code=200):
    """Create a mock httpx.Response for binary content (e.g., images)."""
    response = MagicMock(spec=httpx.Response)
    response.is_success = 200 <= status_code < 300
    response.status_code = status_code
    response.content = content
    response.headers = {"content-type": content_type}
    return response


class MockHttpClient:
    """Mock HTTP client that routes requests based on URL patterns."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def add_response(self, url_pattern: str, response_data: dict, status_code: int = 200):
        """Add a response for a URL pattern."""
        self.responses[url_pattern] = create_mock_response(response_data, status_code)

    def add_responses(self, url_pattern: str, responses: list):
        """Add multiple responses for a URL pattern (consumed in order).

        Each response should be a dict - it will be used as the JSON response directly.
        """
        self.responses[url_pattern] = [create_mock_response(r, 200) for r in responses]

    def add_binary_response(
        self, url_pattern: str, content: bytes, content_type: str, status_code: int = 200
    ):
        """Add a binary response for a URL pattern (e.g., images)."""
        self.responses[url_pattern] = create_mock_binary_response(
            content, content_type, status_code
        )

    def _find_response(self, url: str):
        """Find matching response for URL.

        Uses endswith matching first, then contains matching.
        This ensures /tags only matches api.intercom.io/tags, not /conversations/x/tags.
        """
        # First try exact endswith matches
        for pattern, response in self.responses.items():
            if url.endswith(pattern):
                if isinstance(response, list):
                    if response:
                        return response.pop(0)
                    raise ValueError(f"No more responses for {pattern}")
                return response

        # Then try contains matches (sorted by length, longest first)
        sorted_patterns = sorted(self.responses.keys(), key=len, reverse=True)
        for pattern in sorted_patterns:
            if pattern in url:
                response = self.responses[pattern]
                if isinstance(response, list):
                    if response:
                        return response.pop(0)
                    raise ValueError(f"No more responses for {pattern}")
                return response

        raise ValueError(f"No mock response for {url}")

    async def request(self, method: str, url: str, **kwargs):
        """Mock request method (used by Intercom client)."""
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self._find_response(url)

    async def post(self, url: str, **kwargs):
        """Mock post method (used by Studio Chat client)."""
        self.calls.append({"method": "POST", "url": url, "kwargs": kwargs})
        return self._find_response(url)

    async def get(self, url: str, **kwargs):
        """Mock get method (used by readiness check)."""
        self.calls.append({"method": "GET", "url": url, "kwargs": kwargs})
        return self._find_response(url)


class TestWebhookEndpointE2E:
    """End-to-end tests for /webhooks/intercom endpoint."""

    @pytest.mark.asyncio
    async def test_full_flow_message_response(self, test_config, user_replied_payload):
        """Test complete flow: webhook -> Studio Chat -> Intercom reply."""
        mock_client = MockHttpClient()

        # Setup responses
        # Conversation fetch (required by security model - always fetch from API)
        # Note: Pattern must end with unique suffix to not conflict with /reply or /tags
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": [{"id": "tag-1", "name": "__ai_test"}]})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response(
            "/contacts/contact-abc",
            {
                "id": "contact-abc",
                "email": "john@example.com",
                "name": "John Doe",
                "custom_attributes": {"Plan": "premium"},
            },
        )
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {
                "events": [
                    {"event_type": "message", "data": {"content": "How can I help with billing?"}}
                ]
            },
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Verify Studio Chat was called
            studio_calls = [c for c in mock_client.calls if "playbooks" in c["url"]]
            assert len(studio_calls) == 1
            expected_msg = "Hello, I need help with billing"
            assert studio_calls[0]["kwargs"]["json"]["user_message"] == expected_msg

            # Verify Intercom reply was sent
            reply_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert len(reply_calls) == 1
            assert reply_calls[0]["kwargs"]["json"]["body"] == "How can I help with billing?"

            # Verify tags are NOT sent when send_tags is false (default)
            assert "tags" not in studio_calls[0]["kwargs"]["json"]

    @pytest.mark.asyncio
    async def test_send_tags_to_studio_chat(self, user_replied_payload):
        """Test that conversation tags are sent to Studio Chat when send_tags is enabled."""
        config_with_tags = AppConfig(
            studio_chat=StudioChatConfig(
                api_key="test-api-key",
                base_url="https://api.studiochat.io",
            ),
            intercom=IntercomConfig(access_token="test-intercom-token"),
            assistants=[
                AssistantConfig(
                    playbook_id="playbook-123",
                    admin_id="admin-456",
                    send_tags=True,
                    rollout=RolloutConfig(percentage=100),
                    routing_rules=[
                        RoutingRule(type=RoutingRuleType.INBOX, inbox_id="inbox-789"),
                    ],
                    handoff=HandoffConfig(
                        actions=[
                            Action(type=ActionType.ADD_TAG, tag_name="ai-handoff"),
                        ]
                    ),
                    fallback=FallbackConfig(actions=[]),
                )
            ],
        )

        # Add tags to the webhook payload
        user_replied_payload["data"]["item"]["tags"] = {
            "tags": [{"name": "vip"}, {"name": "billing"}]
        }

        mock_client = MockHttpClient()
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "tags": {"tags": [{"name": "vip"}, {"name": "billing"}]},
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {"events": [{"event_type": "message", "data": {"content": "Hi!"}}]},
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})
        mock_client.add_response("/conversations/conv-12345/parts", {"id": "part-456"})

        with (
            patch("bridge.app._config", config_with_tags),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Verify tags were sent to Studio Chat
            studio_calls = [c for c in mock_client.calls if "playbooks" in c["url"]]
            assert len(studio_calls) == 1
            assert studio_calls[0]["kwargs"]["json"]["tags"] == ["vip", "billing"]

    @pytest.mark.asyncio
    async def test_handoff_flow(self, test_config, user_replied_payload):
        """Test handoff flow when AI requests human takeover."""
        mock_client = MockHttpClient()

        # Conversation fetch (required by security model)
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        # Tags endpoint returns all tags that exist
        all_tags = {
            "data": [
                {"id": "tag-1", "name": "__ai_test"},
                {"id": "tag-2", "name": "ai-handoff"},
            ]
        }
        mock_client.add_response("/tags", all_tags)
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response(
            "/contacts/contact-abc", {"id": "contact-abc", "email": "john@example.com"}
        )
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {
                "events": [
                    {"event_type": "handoff_agent", "data": {"reason": "Complex billing issue"}}
                ]
            },
        )
        # Three calls to /parts: 1) assign_self, 2-3) transfer_to_inbox (unassign + assign team)
        mock_client.add_responses(
            "/conversations/conv-12345/parts",
            [
                {"id": "conv-12345"},  # assign_self
                {"id": "conv-12345"},  # transfer step 1: unassign
                {"id": "conv-12345"},  # transfer step 2: assign team
            ],
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-456"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Verify handoff note contains reason
            note_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert any(
                "Complex billing issue" in c["kwargs"]["json"].get("body", "") for c in note_calls
            )

            # Verify: 1) assign_self, 2-3) transfer_to_inbox
            parts_calls = [c for c in mock_client.calls if "/parts" in c["url"]]
            assert len(parts_calls) >= 3
            # First call should be assign_self (assignee_id=admin_id)
            assert parts_calls[0]["kwargs"]["json"]["assignee_id"] == "admin-456"
            # Second call should be unassign (assignee_id=0) from transfer_to_inbox
            assert parts_calls[1]["kwargs"]["json"]["assignee_id"] == "0"
            # Third call should be assign to team
            assert parts_calls[2]["kwargs"]["json"]["type"] == "team"

    @pytest.mark.asyncio
    async def test_studio_chat_unavailable_triggers_fallback(
        self, test_config, user_replied_payload
    ):
        """Test fallback when Studio Chat returns 503."""
        mock_client = MockHttpClient()

        # Conversation fetch (required by security model)
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        # All tags exist
        all_tags = {
            "data": [
                {"id": "tag-1", "name": "__ai_test"},
                {"id": "fb-tag", "name": "ai-fallback"},
            ]
        }
        mock_client.add_response("/tags", all_tags)
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response("/contacts/contact-abc", {"id": "contact-abc"})
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat", {"error": "Service unavailable"}, status_code=503
        )
        # Three calls to /parts: 1) assign_self, 2-3) transfer_to_inbox (unassign + assign team)
        mock_client.add_responses(
            "/conversations/conv-12345/parts",
            [
                {"id": "conv-12345"},  # assign_self
                {"id": "conv-12345"},  # transfer step 1: unassign
                {"id": "conv-12345"},  # transfer step 2: assign team
            ],
        )

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Verify: 1) assign_self, 2-3) transfer_to_inbox
            parts_calls = [c for c in mock_client.calls if "/parts" in c["url"]]
            assert len(parts_calls) >= 3
            # First call should be assign_self (assignee_id=admin_id)
            assert parts_calls[0]["kwargs"]["json"]["assignee_id"] == "admin-456"
            # Second call should be unassign (assignee_id=0) from transfer_to_inbox
            assert parts_calls[1]["kwargs"]["json"]["assignee_id"] == "0"
            # Third call should be transfer to fallback inbox
            assert parts_calls[2]["kwargs"]["json"]["assignee_id"] == "fallback-inbox"
            assert parts_calls[2]["kwargs"]["json"]["type"] == "team"

    @pytest.mark.asyncio
    async def test_rollout_excluded_triggers_fallback(
        self, test_config_partial_rollout, user_replied_payload
    ):
        """Test fallback when conversation excluded from rollout."""
        mock_client = MockHttpClient()

        # Conversation fetch (required by security model)
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        # Tag exists
        all_tags = {"data": [{"id": "tag-id", "name": "rollout-excluded"}]}
        mock_client.add_response("/tags", all_tags)
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})

        with (
            patch("bridge.app._config", test_config_partial_rollout),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Studio Chat should NOT be called
            studio_calls = [c for c in mock_client.calls if "studiochat" in c["url"]]
            assert len(studio_calls) == 0

    @pytest.mark.asyncio
    async def test_conflict_response_ignored(self, test_config, user_replied_payload):
        """Test that 409 conflict from Studio Chat is handled gracefully."""
        mock_client = MockHttpClient()

        # Conversation fetch (required by security model)
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": [{"id": "tag-1", "name": "__ai_test"}]})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response("/contacts/contact-abc", {"id": "contact-abc"})
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat", {"error": "Conflict"}, status_code=409
        )

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            # Should return 200 (conflict is expected)
            assert response.status_code == 200

            # No reply should be sent to Intercom
            reply_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert len(reply_calls) == 0

    @pytest.mark.asyncio
    async def test_no_matching_assistant(self, test_config):
        """Test webhook from unmatched inbox is ignored."""
        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-99999",
                    "team_assignee_id": "different-inbox",
                    "tags": {"tags": []},
                    "contacts": {"contacts": []},
                    "conversation_parts": {
                        "conversation_parts": [{"author": {"type": "user"}, "body": "<p>Hello</p>"}]
                    },
                }
            },
        }

        mock_client = MockHttpClient()

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200
            assert len(mock_client.calls) == 0

    @pytest.mark.asyncio
    async def test_unsupported_topic_ignored(self, test_config):
        """Test that unsupported webhook topics are ignored."""
        payload = {
            "topic": "conversation.created",
            "data": {"item": {"id": "conv-123"}},
        }

        mock_client = MockHttpClient()

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_message_ignored(self, test_config):
        """Test that messages from admins are ignored."""
        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-123",
                    "team_assignee_id": "inbox-789",
                    "tags": {"tags": []},
                    "contacts": {"contacts": []},
                    "conversation_parts": {
                        "conversation_parts": [
                            {"author": {"type": "admin"}, "body": "<p>Admin message</p>"}
                        ]
                    },
                }
            },
        }

        mock_client = MockHttpClient()

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, test_config):
        """Test that invalid JSON returns 400."""
        mock_client = MockHttpClient()

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    content="not valid json",
                    headers={"Content-Type": "application/json"},
                )

            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_topic_returns_400(self, test_config):
        """Test that missing topic returns 400."""
        mock_client = MockHttpClient()

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json={"data": {"item": {"id": "123"}}},
                )

            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_multiple_events_processed(self, test_config, user_replied_payload):
        """Test that multiple events from Studio Chat are all processed."""
        mock_client = MockHttpClient()

        # Conversation fetch (required by security model)
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        # Use responses list for /tags since called multiple times
        mock_client.add_responses(
            "/tags",
            [
                {"data": [{"id": "tag-1", "name": "__ai_test"}]},  # tracking
                {"data": []},  # label lookup
                {"data": [{"id": "label-id", "name": "billing-issue"}]},  # after create
            ],
        )
        mock_client.add_response("POST /tags", {"id": "label-id", "name": "billing-issue"})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response("/contacts/contact-abc", {"id": "contact-abc"})
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {
                "events": [
                    {"event_type": "message", "data": {"content": "First message"}},
                    {"event_type": "message", "data": {"content": "Second message"}},
                    {"event_type": "note", "data": {"content": "Internal note"}},
                    {"event_type": "label", "data": {"name": "billing-issue"}},
                ]
            },
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Verify messages were sent
            reply_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert len(reply_calls) >= 2  # At least 2 messages + 1 note

    @pytest.mark.asyncio
    async def test_whatsapp_reaction_ignored(self, test_config):
        """Test that WhatsApp reactions are filtered and not sent to Studio Chat."""
        # WhatsApp reactions have specific format "Reacted to 'X' with Y"
        reaction_body = '<p>Reacted to "Hello" with 👍</p>'
        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-123",
                    "team_assignee_id": "inbox-789",
                    "tags": {"tags": []},
                    "contacts": {"contacts": []},
                    "conversation_parts": {
                        "conversation_parts": [{"author": {"type": "user"}, "body": reaction_body}]
                    },
                }
            },
        }

        mock_client = MockHttpClient()

        # Security model: we still fetch from API to verify
        # API returns the same reaction message
        mock_client.add_response(
            "/conversations/conv-123",
            {
                "id": "conv-123",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [{"author": {"type": "user"}, "body": reaction_body}]
                },
            },
        )

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

            # Conversation fetch happens, but no Studio Chat calls
            conv_calls = [
                c
                for c in mock_client.calls
                if "/conversations/conv-123" in c["url"] and "/reply" not in c["url"]
            ]
            assert len(conv_calls) == 1  # Conversation was fetched

            studio_calls = [
                c for c in mock_client.calls if "studiochat" in c["url"] or "playbooks" in c["url"]
            ]
            assert len(studio_calls) == 0  # No Studio Chat calls

    @pytest.mark.asyncio
    async def test_context_enrichment_included(self, test_config, user_replied_payload):
        """Test that context enrichment data is sent to Studio Chat."""
        mock_client = MockHttpClient()

        # Conversation fetch (required by security model)
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Hello, I need help with billing</p>",
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": [{"id": "tag-1", "name": "__ai_test"}]})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response(
            "/contacts/contact-abc",
            {
                "id": "contact-abc",
                "email": "john@example.com",
                "name": "John Doe",
                "custom_attributes": {"Plan": "enterprise"},
            },
        )
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {"events": [{"event_type": "message", "data": {"content": "Got it!"}}]},
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/webhooks/intercom",
                    json=user_replied_payload,
                )

            assert response.status_code == 200

            # Verify context was sent to Studio Chat
            studio_calls = [c for c in mock_client.calls if "playbooks" in c["url"]]
            assert len(studio_calls) == 1
            context = studio_calls[0]["kwargs"]["json"]["context"]
            assert context["source"] == "webhook"
            assert context["contact"]["email"] == "john@example.com"
            assert context["contact"]["plan"] == "enterprise"


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, test_config):
        """Test /health endpoint."""
        mock_client = MockHttpClient()

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/health")

            assert response.status_code == 200
            assert response.json() == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_ready_endpoint(self, test_config):
        """Test /ready endpoint."""
        mock_client = MockHttpClient()
        # Mock Studio Chat readiness endpoint
        mock_client.add_response("/readiness", {"status": "ready", "version": "1.0.0"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["checks"]["config"]["assistants"] == 1
            assert data["checks"]["studio_chat"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_image_message_sent_to_studio_chat(self, test_config):
        """Test that image messages are sent to Studio Chat with attachments."""
        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-12345",
                    "team_assignee_id": "inbox-789",
                    "tags": {"tags": []},
                    "contacts": {
                        "contacts": [
                            {
                                "id": "contact-abc",
                                "name": "John Doe",
                                "email": "john@example.com",
                            }
                        ]
                    },
                    "conversation_parts": {
                        "conversation_parts": [
                            {
                                "author": {"type": "user"},
                                "body": '<img src="https://example.com/image.png">',
                            }
                        ]
                    },
                }
            },
        }

        mock_client = MockHttpClient()

        # Conversation fetch
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": '<img src="https://example.com/image.png">',
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": []})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response(
            "/contacts/contact-abc",
            {"id": "contact-abc", "email": "john@example.com", "name": "John Doe"},
        )
        # Mock image download - returns fake PNG bytes
        mock_client.add_binary_response(
            "https://example.com/image.png",
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",  # PNG header
            "image/png",
        )
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {"events": [{"event_type": "message", "data": {"content": "I see the image!"}}]},
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

            # Verify Studio Chat was called with attachments
            studio_calls = [c for c in mock_client.calls if "playbooks" in c["url"]]
            assert len(studio_calls) == 1

            request_json = studio_calls[0]["kwargs"]["json"]
            # user_message should be empty for image-only messages
            assert request_json["user_message"] == ""
            assert "attachments" in request_json
            assert len(request_json["attachments"]) == 1
            assert request_json["attachments"][0]["type"] == "image"
            assert request_json["attachments"][0]["media_type"] == "image/png"
            # Should have base64 data, not URL
            assert "data" in request_json["attachments"][0]
            assert "url" not in request_json["attachments"][0]

            # Verify Intercom reply was sent
            reply_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert len(reply_calls) == 1
            assert reply_calls[0]["kwargs"]["json"]["body"] == "I see the image!"

    @pytest.mark.asyncio
    async def test_image_with_text_sent_to_studio_chat(self, test_config):
        """Test that image with accompanying text is sent correctly."""
        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-12345",
                    "team_assignee_id": "inbox-789",
                    "tags": {"tags": []},
                    "contacts": {
                        "contacts": [
                            {
                                "id": "contact-abc",
                                "name": "John Doe",
                                "email": "john@example.com",
                            }
                        ]
                    },
                    "conversation_parts": {
                        "conversation_parts": [
                            {
                                "author": {"type": "user"},
                                "body": '<p>What is this?</p><img src="https://example.com/photo.jpg">',
                            }
                        ]
                    },
                }
            },
        }

        mock_client = MockHttpClient()

        # Conversation fetch
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": '<p>What is this?</p><img src="https://example.com/photo.jpg">',
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": []})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response(
            "/contacts/contact-abc",
            {"id": "contact-abc", "email": "john@example.com", "name": "John Doe"},
        )
        # Mock image download
        mock_client.add_binary_response(
            "https://example.com/photo.jpg",
            b"\xff\xd8\xff\xe0",  # JPEG header
            "image/jpeg",
        )
        mock_client.add_response(
            "/playbooks/playbook-123/active/chat",
            {"events": [{"event_type": "message", "data": {"content": "That's a photo!"}}]},
        )
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

            # Verify Studio Chat was called with both message and attachments
            studio_calls = [c for c in mock_client.calls if "playbooks" in c["url"]]
            assert len(studio_calls) == 1

            request_json = studio_calls[0]["kwargs"]["json"]
            # Should have the text message
            assert request_json["user_message"] == "What is this?"
            # And the image attachment
            assert "attachments" in request_json
            assert len(request_json["attachments"]) == 1
            assert request_json["attachments"][0]["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_audio_message_triggers_handoff(self, test_config):
        """Test that audio messages still trigger handoff (not sent to Studio Chat)."""
        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-12345",
                    "team_assignee_id": "inbox-789",
                    "tags": {"tags": []},
                    "contacts": {"contacts": [{"id": "contact-abc"}]},
                    "conversation_parts": {
                        "conversation_parts": [
                            {
                                "author": {"type": "user"},
                                "body": "<p>Sent an audio clip</p>",
                            }
                        ]
                    },
                }
            },
        }

        mock_client = MockHttpClient()

        # Conversation fetch
        mock_client.add_response(
            "/conversations/conv-12345",
            {
                "id": "conv-12345",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Sent an audio clip</p>",
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": [{"id": "tag-1", "name": "ai-handoff"}]})
        mock_client.add_response("/conversations/conv-12345/tags", {"id": "conv-12345"})
        mock_client.add_response("/conversations/conv-12345/parts", {"id": "conv-12345"})
        mock_client.add_response("/conversations/conv-12345/reply", {"id": "part-123"})
        # BE handoff notification
        mock_client.add_response(
            "/playbooks/playbook-123/conversations/conv-12345/handoff",
            {"status": "ok"},
        )

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

            # Verify Studio Chat chat API was NOT called (audio triggers handoff)
            chat_calls = [c for c in mock_client.calls if "/active/chat" in c["url"]]
            assert len(chat_calls) == 0

            # Verify BE was notified of the handoff
            handoff_calls = [
                c
                for c in mock_client.calls
                if "/handoff" in c["url"] and "/conversations/" in c["url"]
            ]
            assert len(handoff_calls) == 1
            assert handoff_calls[0]["kwargs"]["json"] == {"error_type": "unsupported_media"}

            # Verify handoff was triggered (multiple replies: user message + notes)
            reply_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert len(reply_calls) >= 1  # At least the user-facing message

            # Check that the first reply is the audio handoff message
            first_reply = reply_calls[0]["kwargs"]["json"]["body"]
            assert "audio" in first_reply.lower() or "No puedo procesar" in first_reply


class TestUnsupportedMediaHandoff:
    """Tests that unsupported media (video, audio) triggers handoff and notifies BE."""

    @pytest.mark.asyncio
    async def test_video_message_triggers_handoff_and_notifies_be(self, test_config):
        """Test that a video message triggers handoff + calls Studio Chat mark_handoff endpoint."""
        mock_client = MockHttpClient()

        # Conversation with a video message
        mock_client.add_response(
            "/conversations/conv-video",
            {
                "id": "conv-video",
                "source": {"author": {"type": "user"}, "body": ""},
                "conversation_parts": {
                    "conversation_parts": [
                        {
                            "author": {"type": "user"},
                            "body": "<p>Check this out</p><video src='https://example.com/video.mp4'></video>",
                        }
                    ]
                },
            },
        )
        mock_client.add_response("/tags", {"data": [{"id": "tag-1", "name": "ai-handoff"}]})
        mock_client.add_response("/conversations/conv-video/tags", {"id": "conv-video"})
        mock_client.add_response("/conversations/conv-video/reply", {"id": "part-123"})
        mock_client.add_response("/conversations/conv-video/assign", {"id": "conv-video"})
        # BE handoff notification endpoint
        mock_client.add_response(
            "/playbooks/playbook-123/conversations/conv-video/handoff",
            {"status": "ok"},
        )

        payload = {
            "topic": "conversation.user.replied",
            "data": {
                "item": {
                    "id": "conv-video",
                    "admin_assignee_id": "admin-456",
                    "team_assignee_id": "inbox-789",
                    "tags": {"tags": []},
                    "contacts": {
                        "contacts": [
                            {
                                "id": "contact-abc",
                                "name": "Jane",
                                "email": "jane@example.com",
                            }
                        ]
                    },
                    "conversation_parts": {
                        "conversation_parts": [
                            {
                                "author": {"type": "user"},
                                "body": "<p>Check this out</p><video src='https://example.com/video.mp4'></video>",
                            }
                        ]
                    },
                }
            },
        }

        with (
            patch("bridge.app._config", test_config),
            patch("bridge.app._http_client", mock_client),
        ):
            from httpx import ASGITransport, AsyncClient

            from bridge.app import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/webhooks/intercom", json=payload)

            assert response.status_code == 200

            # Verify Studio Chat was NOT called for chat (no AI response for video)
            chat_calls = [c for c in mock_client.calls if "/active/chat" in c["url"]]
            assert len(chat_calls) == 0

            # Verify the BE handoff endpoint WAS called
            handoff_calls = [
                c
                for c in mock_client.calls
                if "/handoff" in c["url"] and "/conversations/" in c["url"]
            ]
            assert len(handoff_calls) == 1
            assert "conv-video" in handoff_calls[0]["url"]
            assert "playbook-123" in handoff_calls[0]["url"]
            assert handoff_calls[0]["kwargs"]["json"] == {"error_type": "unsupported_media"}

            # Verify Intercom handoff actions were executed (reply with message + tag + transfer)
            reply_calls = [c for c in mock_client.calls if "/reply" in c["url"]]
            assert len(reply_calls) >= 1
