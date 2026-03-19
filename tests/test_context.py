"""Tests for context enrichment."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.context import (
    build_context,
    extract_attributes,
    get_nested_value,
)
from bridge.models import (
    AssistantConfig,
    ContextConfig,
    IntercomContact,
    IntercomWebhookData,
)


class TestGetNestedValue:
    """Tests for get_nested_value function."""

    def test_simple_key(self):
        """Test extracting a simple top-level key."""
        data = {"email": "test@example.com", "name": "John"}
        assert get_nested_value(data, "email") == "test@example.com"

    def test_nested_key(self):
        """Test extracting a nested key with dot notation."""
        data = {
            "custom_attributes": {
                "plan": "premium",
                "status": "active",
            }
        }
        assert get_nested_value(data, "custom_attributes.plan") == "premium"

    def test_nested_key_with_spaces(self):
        """Test extracting a nested key with spaces in the name."""
        data = {
            "custom_attributes": {
                "Plan Type": "enterprise",
                "Subscription Status": "active",
            }
        }
        assert get_nested_value(data, "custom_attributes.Plan Type") == "enterprise"

    def test_deeply_nested(self):
        """Test extracting deeply nested values."""
        data = {"level1": {"level2": {"level3": "deep value"}}}
        assert get_nested_value(data, "level1.level2.level3") == "deep value"

    def test_missing_key(self):
        """Test that missing keys return None."""
        data = {"email": "test@example.com"}
        assert get_nested_value(data, "name") is None
        assert get_nested_value(data, "custom_attributes.plan") is None

    def test_empty_data(self):
        """Test with empty data."""
        assert get_nested_value({}, "email") is None
        assert get_nested_value(None, "email") is None

    def test_empty_path(self):
        """Test with empty path."""
        data = {"email": "test@example.com"}
        assert get_nested_value(data, "") is None


class TestExtractAttributes:
    """Tests for extract_attributes function."""

    def test_extract_multiple_attributes(self):
        """Test extracting multiple attributes."""
        data = {
            "email": "test@example.com",
            "name": "John Doe",
            "phone": "+1234567890",
            "custom_attributes": {
                "Plan Type": "premium",
            },
        }
        paths = ["email", "name", "custom_attributes.Plan Type"]
        result = extract_attributes(data, paths)

        assert result == {
            "email": "test@example.com",
            "name": "John Doe",
            "plan_type": "premium",
        }

    def test_skip_none_values(self):
        """Test that None values are not included."""
        data = {"email": "test@example.com"}
        paths = ["email", "name", "phone"]
        result = extract_attributes(data, paths)

        assert result == {"email": "test@example.com"}
        assert "name" not in result
        assert "phone" not in result

    def test_empty_paths(self):
        """Test with empty paths list."""
        data = {"email": "test@example.com"}
        result = extract_attributes(data, [])
        assert result == {}


class TestBuildContext:
    """Tests for build_context function."""

    @pytest.fixture
    def webhook_data(self):
        """Sample webhook data."""
        return IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            message="Hello",
            contact=IntercomContact(
                id="contact-456",
                name="Test User",
                email="test@example.com",
            ),
            tags=[],
        )

    @pytest.fixture
    def assistant_no_context(self):
        """Assistant with no context config."""
        return AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
        )

    @pytest.fixture
    def assistant_with_context(self):
        """Assistant with context config."""
        return AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(
                contact_attributes=["email", "name", "phone", "custom_attributes.Plan"],
                conversation_attributes=["custom_attributes.Priority"],
                static={"source": "webhook"},
            ),
        )

    @pytest.mark.asyncio
    async def test_build_context_no_config(self, webhook_data, assistant_no_context):
        """Test building context with no enrichment configured."""
        mock_client = MagicMock()

        context = await build_context(webhook_data, assistant_no_context, mock_client)

        assert "platform" not in context
        assert context["contact"]["name"] == "Test User"
        assert context["contact"]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_build_context_source_channel_whatsapp(self, webhook_data, assistant_no_context):
        """Test that whatsapp source_channel is passed through."""
        mock_client = MagicMock()

        context = await build_context(
            webhook_data, assistant_no_context, mock_client, source_channel_type="whatsapp"
        )

        assert context["source_channel"] == "whatsapp"

    @pytest.mark.asyncio
    async def test_build_context_source_channel_conversation_remapped(
        self, webhook_data, assistant_no_context
    ):
        """Test that 'conversation' is remapped to 'intercom_in_app'."""
        mock_client = MagicMock()

        context = await build_context(
            webhook_data, assistant_no_context, mock_client, source_channel_type="conversation"
        )

        assert context["source_channel"] == "intercom_in_app"

    @pytest.mark.asyncio
    async def test_build_context_source_channel_type_none(self, webhook_data, assistant_no_context):
        """Test that source_channel is omitted when source_channel_type is None."""
        mock_client = MagicMock()

        context = await build_context(webhook_data, assistant_no_context, mock_client)

        assert "source_channel" not in context

    @pytest.mark.asyncio
    async def test_build_context_with_contact_enrichment(
        self, webhook_data, assistant_with_context
    ):
        """Test building context with contact enrichment."""
        mock_client = MagicMock()
        mock_client.get_contact = AsyncMock(
            return_value={
                "email": "test@example.com",
                "name": "Test User",
                "phone": "+1234567890",
                "custom_attributes": {
                    "Plan": "premium",
                },
            }
        )
        mock_client.get_conversation = AsyncMock(
            return_value={
                "custom_attributes": {
                    "Priority": "high",
                },
            }
        )

        context = await build_context(webhook_data, assistant_with_context, mock_client)

        assert context["source"] == "webhook"
        assert "platform" not in context
        assert context["contact"]["email"] == "test@example.com"
        assert context["contact"]["phone"] == "+1234567890"
        assert context["contact"]["plan"] == "premium"
        assert context["conversation"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_build_context_enrichment_failure(self, webhook_data, assistant_with_context):
        """Test that enrichment failures don't break context building."""
        mock_client = MagicMock()
        mock_client.get_contact = AsyncMock(side_effect=Exception("API Error"))
        mock_client.get_conversation = AsyncMock(side_effect=Exception("API Error"))

        # Should not raise, just log warning and continue
        context = await build_context(webhook_data, assistant_with_context, mock_client)

        assert "platform" not in context
        assert context["source"] == "webhook"

    @pytest.mark.asyncio
    async def test_build_context_static_values(self, webhook_data):
        """Test that static values are included."""
        assistant = AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(
                static={
                    "platform": "custom-platform",
                    "environment": "production",
                },
            ),
        )
        mock_client = MagicMock()

        context = await build_context(webhook_data, assistant, mock_client)

        assert context["platform"] == "custom-platform"  # Overrides default
        assert context["environment"] == "production"

    @pytest.mark.asyncio
    async def test_build_context_anonymous_contact_no_config(self):
        """Test fallback with anonymous contact (no name, no email)."""
        webhook_data = IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            message="Hello",
            contact=IntercomContact(id="contact-anon", name=None, email=None),
            tags=[],
        )
        assistant = AssistantConfig(playbook_id="playbook-1", admin_id="admin-1")
        mock_client = MagicMock()

        context = await build_context(webhook_data, assistant, mock_client)

        assert "platform" not in context
        # No contact key since both name and email are None
        assert "contact" not in context

    @pytest.mark.asyncio
    async def test_build_context_anonymous_contact_with_enrichment(self):
        """Test enrichment for anonymous contact (API returns empty email)."""
        webhook_data = IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            message="Hello",
            contact=IntercomContact(id="contact-anon", name=None, email=None),
            tags=[],
        )
        assistant = AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(contact_attributes=["email", "name"]),
        )
        mock_client = MagicMock()
        mock_client.get_contact = AsyncMock(return_value={"email": "", "name": None})

        context = await build_context(webhook_data, assistant, mock_client)

        assert "platform" not in context
        # Empty string is not None, so it gets included
        assert context["contact"]["email"] == ""
        assert "name" not in context["contact"]

    @pytest.mark.asyncio
    async def test_build_context_enrichment_failure_falls_back_to_webhook(self):
        """Test that contact enrichment failure falls back to webhook contact data."""
        webhook_data = IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            message="Hello",
            contact=IntercomContact(
                id="contact-456", name="Webhook Name", email="webhook@example.com"
            ),
            tags=[],
        )
        assistant = AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(contact_attributes=["email", "name"]),
        )
        mock_client = MagicMock()
        mock_client.get_contact = AsyncMock(side_effect=Exception("API Error"))

        context = await build_context(webhook_data, assistant, mock_client)

        assert "platform" not in context
        # Enrichment failed, no "contact" from API, so fallback kicks in
        assert context["contact"]["name"] == "Webhook Name"
        assert context["contact"]["email"] == "webhook@example.com"

    @pytest.mark.asyncio
    async def test_build_context_enrichment_returns_empty_no_fallback(self):
        """Test that when enrichment returns no attributes, fallback fills in from webhook."""
        webhook_data = IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            message="Hello",
            contact=IntercomContact(
                id="contact-456", name="Webhook Name", email="webhook@example.com"
            ),
            tags=[],
        )
        assistant = AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(contact_attributes=["phone"]),  # Only phone, not in API
        )
        mock_client = MagicMock()
        mock_client.get_contact = AsyncMock(
            return_value={"email": "api@example.com", "name": "API Name"}
        )

        context = await build_context(webhook_data, assistant, mock_client)

        # Phone not in API response -> no contact attrs extracted
        # -> no "contact" key from enrichment, fallback kicks in
        assert context["contact"]["name"] == "Webhook Name"
        assert context["contact"]["email"] == "webhook@example.com"

    @pytest.mark.asyncio
    async def test_build_context_enrichment_succeeds_no_fallback(self, webhook_data):
        """Test that when enrichment succeeds, webhook fallback is NOT used."""
        assistant = AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(contact_attributes=["email"]),
        )
        mock_client = MagicMock()
        mock_client.get_contact = AsyncMock(
            return_value={"email": "api@example.com", "name": "API Name"}
        )

        context = await build_context(webhook_data, assistant, mock_client)

        # API enrichment succeeds, so webhook fallback is skipped
        assert context["contact"]["email"] == "api@example.com"
        # name was not in contact_attributes, so it's not in enriched result
        assert "name" not in context["contact"]

    @pytest.mark.asyncio
    async def test_build_context_no_contact_in_webhook(self):
        """Test building context when webhook has no contact at all."""
        webhook_data = IntercomWebhookData(
            topic="conversation.admin.assigned",
            conversation_id="conv-123",
            message=None,
            contact=None,
            tags=[],
        )
        assistant = AssistantConfig(playbook_id="playbook-1", admin_id="admin-1")
        mock_client = MagicMock()

        context = await build_context(webhook_data, assistant, mock_client)

        assert "platform" not in context
        assert "contact" not in context

    @pytest.mark.asyncio
    async def test_build_context_partial_webhook_contact(self):
        """Test fallback with contact that has email but no name."""
        webhook_data = IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            message="Hello",
            contact=IntercomContact(id="contact-456", name=None, email="only@email.com"),
            tags=[],
        )
        assistant = AssistantConfig(playbook_id="playbook-1", admin_id="admin-1")
        mock_client = MagicMock()

        context = await build_context(webhook_data, assistant, mock_client)

        assert context["contact"]["email"] == "only@email.com"
        assert "name" not in context["contact"]

    @pytest.mark.asyncio
    async def test_build_context_conversation_enrichment_only(self, webhook_data):
        """Test enrichment with conversation_attributes but no contact_attributes."""
        assistant = AssistantConfig(
            playbook_id="playbook-1",
            admin_id="admin-1",
            context=ContextConfig(
                conversation_attributes=["custom_attributes.Department"],
            ),
        )
        mock_client = MagicMock()
        mock_client.get_conversation = AsyncMock(
            return_value={"custom_attributes": {"Department": "Sales"}}
        )

        context = await build_context(webhook_data, assistant, mock_client)

        assert context["conversation"]["department"] == "Sales"
        # No contact_attributes configured -> fallback with webhook contact
        assert context["contact"]["name"] == "Test User"
        assert context["contact"]["email"] == "test@example.com"
