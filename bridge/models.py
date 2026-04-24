"""Pydantic models for configuration and data structures."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# === Configuration Models ===


class StudioChatConfig(BaseModel):
    """Studio Chat API configuration."""

    api_key: str = Field(..., description="API key for authentication")
    base_url: str = Field(
        default="https://api.studiochat.io",
        description="Base URL of the Studio Chat API",
    )
    timeout_seconds: int = Field(default=120, description="Request timeout in seconds")


class IntercomConfig(BaseModel):
    """Intercom API configuration."""

    access_token: str = Field(..., description="Intercom access token")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")


class RolloutConfig(BaseModel):
    """Rollout configuration for an assistant."""

    percentage: int = Field(
        default=100, ge=0, le=100, description="Percentage of conversations (0-100)"
    )


class RoutingRuleType(str, Enum):
    """Types of routing rules."""

    INBOX = "inbox"
    ADMIN_ASSIGNMENT = "admin_assignment"
    TAG = "tag"


class RoutingRule(BaseModel):
    """A routing rule that determines when to activate an assistant."""

    type: RoutingRuleType
    inbox_id: str | int | None = None
    admin_id: str | int | None = None
    tag_name: str | None = None


class ActionType(str, Enum):
    """Types of actions that can be executed."""

    ADD_TAG = "add_tag"
    TRANSFER_TO_INBOX = "transfer_to_inbox"
    ASSIGN_TO_ADMIN = "assign_to_admin"
    ADD_NOTE = "add_note"


class Action(BaseModel):
    """An action to execute (handoff, fallback, etc.)."""

    type: ActionType
    tag_name: str | None = None
    inbox_id: str | int | None = None
    admin_id: str | int | None = None
    template: str | None = None  # For add_note, supports {reason} placeholder


class HandoffBranch(BaseModel):
    """A branch of handoff actions based on conversation tag."""

    tag: str = Field(..., description="Tag name to match for this branch")
    actions: list[Action] = Field(default_factory=list)


class HandoffConfig(BaseModel):
    """Configuration for handoff actions.

    Supports two modes:
    1. Simple mode: Use `actions` for a single set of handoff actions
    2. Branching mode: Use `branches` to route to different actions based on tags

    When branches are defined, the system will:
    - Check conversation tags against each branch's tag (in order)
    - Execute the first matching branch's actions
    - Fall back to `actions` (default) if no branch matches

    Media handoff messages can be customized per media type. The default messages
    are in Spanish but can be overridden in the config.
    """

    actions: list[Action] = Field(
        default_factory=list,
        description="Default actions when no branch matches (or when not using branches)",
    )
    branches: list[HandoffBranch] = Field(
        default_factory=list,
        description="Tag-based branches for conditional handoff routing",
    )
    media_handoff_messages: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Custom messages to send when media triggers handoff. "
            "Keys are media types: 'image', 'audio', 'video', 'attachment'. "
            "If not specified, uses default messages."
        ),
    )


class FallbackConfig(BaseModel):
    """Configuration for fallback actions (when AI is unavailable)."""

    actions: list[Action] = Field(default_factory=list)


class ContextConfig(BaseModel):
    """Configuration for context enrichment sent to Studio Chat."""

    contact_attributes: list[str] = Field(
        default_factory=list,
        description="Contact attributes to fetch (supports dot notation)",
    )
    conversation_attributes: list[str] = Field(
        default_factory=list,
        description="Conversation attributes to fetch and include (supports dot notation)",
    )
    static: dict[str, str] = Field(
        default_factory=dict,
        description="Static key-value pairs to always include in context",
    )


class AssistantConfig(BaseModel):
    """Configuration for a single assistant/playbook."""

    playbook_id: str = Field(..., description="Studio Chat playbook ID")
    admin_id: str | int = Field(..., description="Intercom admin ID for responses")
    send_tags: bool = Field(
        default=False,
        description="Send Intercom conversation tags to Studio Chat",
    )
    rollout: RolloutConfig = Field(default_factory=RolloutConfig)
    routing_rules: list[RoutingRule] = Field(default_factory=list)
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    include_feedback_note: bool = Field(
        default=False,
        description=(
            "When true, add a private Intercom note after each AI response "
            "containing a link back to that response in the Studio Chat UI "
            "(for quick feedback/corrections). Requires Studio Chat to return "
            "a deep_link in the response."
        ),
    )


class AppConfig(BaseModel):
    """Root application configuration."""

    studio_chat: StudioChatConfig
    intercom: IntercomConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    assistants: list[AssistantConfig] = Field(default_factory=list)


# === Intercom Webhook Models ===


class IntercomContact(BaseModel):
    """Contact information from Intercom."""

    id: str
    name: str | None = None
    email: str | None = None


class IntercomConversation(BaseModel):
    """Conversation data from Intercom webhook."""

    id: str
    admin_assignee_id: str | None = None
    team_assignee_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class IntercomWebhookData(BaseModel):
    """Parsed data from an Intercom webhook.

    Security Note:
    Intercom webhooks are NOT signed. The webhook is only a notification/hint
    that something happened - never trust it as source of truth.
    Always fetch the actual data from the API and verify.
    """

    topic: str
    conversation_id: str
    message: str | None = None
    contact: IntercomContact | None = None
    admin_assignee_id: str | None = None
    team_assignee_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    webhook_message_hint: str | None = Field(
        default=None,
        description="Message from webhook payload (for verification only, not source of truth)",
    )


# === Studio Chat Models ===


class StudioChatEventType(str, Enum):
    """Types of events from Studio Chat."""

    MESSAGE = "message"
    NOTE = "note"
    LABEL = "label"
    HANDOFF_AGENT = "handoff_agent"
    PRIORITY = "priority"
    IMAGE = "image"


class StudioChatEvent(BaseModel):
    """An event from Studio Chat response."""

    event_type: StudioChatEventType
    data: dict[str, Any]


class StudioChatResponse(BaseModel):
    """Response from Studio Chat API."""

    events: list[StudioChatEvent] = Field(default_factory=list)
    explanation: str | None = None
    first_seen: bool = Field(
        default=False,
        description="True if this is the first message in this conversation",
    )
    deep_link: str | None = Field(
        default=None,
        description=(
            "URL to this specific assistant response in the Studio Chat "
            "activity UI (…/activity/chatlogs/<conv_id>?r=<response_index>). "
            "Used to build feedback links back to the response."
        ),
    )
