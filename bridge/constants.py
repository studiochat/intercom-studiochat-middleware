"""Constants used throughout the application.

Centralizing magic strings and values improves maintainability and reduces
the risk of typos or inconsistencies across the codebase.
"""

# =============================================================================
# Intercom Author Types
# =============================================================================
# These are the author types that represent end-users (not admins/bots)
USER_AUTHOR_TYPES = frozenset({"user", "lead", "contact"})

# =============================================================================
# Intercom Message/Part Types
# =============================================================================
PART_TYPE_COMMENT = "comment"
PART_TYPE_NOTE = "note"
PART_TYPE_ASSIGNMENT = "assignment"

# =============================================================================
# Intercom Webhook Topics
# =============================================================================
TOPIC_USER_REPLIED = "conversation.user.replied"
TOPIC_ADMIN_ASSIGNED = "conversation.admin.assigned"

SUPPORTED_WEBHOOK_TOPICS = frozenset(
    {
        TOPIC_USER_REPLIED,
        TOPIC_ADMIN_ASSIGNED,
    }
)

# =============================================================================
# Intercom API Message Types
# =============================================================================
INTERCOM_MESSAGE_TYPE_COMMENT = "comment"
INTERCOM_MESSAGE_TYPE_NOTE = "note"
INTERCOM_MESSAGE_TYPE_ASSIGNMENT = "assignment"
INTERCOM_AUTHOR_TYPE_ADMIN = "admin"

# =============================================================================
# Studio Chat URLs
# =============================================================================
STUDIO_CHAT_CHATLOG_URL_TEMPLATE = "https://app.studiochat.io/activity/chatlogs/{conversation_id}"

# =============================================================================
# Default Values
# =============================================================================
DEFAULT_STUDIO_CHAT_BASE_URL = "https://api.studiochat.io"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_CONFIG_PATH = "./config.yaml"

# =============================================================================
# Handoff Note Templates (Language-Agnostic)
# =============================================================================
HANDOFF_NOTE_TEMPLATE = "🤖→👤 {reason}"
# Intercom renders HTML in notes, so the anchor becomes a compact clickable
# label instead of the full URL (which Intercom would otherwise auto-linkify
# and render verbatim, taking up more room than needed).
FIRST_SEEN_NOTE_TEMPLATE = '🤖 <a href="{url}">Studio Chat</a>'
DEFAULT_HANDOFF_REASON = "-"

# =============================================================================
# Feedback Note (Deep Link)
# =============================================================================
# Private note inserted after an AI response when an assistant has
# include_feedback_note=True, so reviewers can jump straight to the exact
# response in the Studio Chat UI to leave feedback / corrections.
FEEDBACK_NOTE_TEMPLATE = 'Feedback ✏️? <a href="{url}">link</a>'

# =============================================================================
# Media Handoff Reasons (Language-Agnostic)
# =============================================================================
MEDIA_HANDOFF_REASONS = {
    "image": "📷",
    "audio": "🎤",
    "video": "🎥",
    "attachment": "📎",
}

# =============================================================================
# Supported Document Types (for Studio Chat API)
# =============================================================================
SUPPORTED_DOCUMENT_CONTENT_TYPES = frozenset({"application/pdf", "text/plain"})
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".txt"})

# =============================================================================
# Media Handoff User Message Templates
# =============================================================================
# Default messages sent to user when media triggers handoff.
# Can be overridden per-assistant in config under handoff.media_handoff_messages
DEFAULT_MEDIA_HANDOFF_MESSAGES = {
    "image": (
        "No puedo procesar imágenes. "
        "Te estoy derivando a un agente humano que te atenderá pronto."
    ),
    "audio": (
        "No puedo procesar mensajes de audio. "
        "Te estoy derivando a un agente humano que te atenderá pronto."
    ),
    "video": (
        "No puedo procesar videos. " "Te estoy derivando a un agente humano que te atenderá pronto."
    ),
    "attachment": (
        "No puedo procesar archivos adjuntos. "
        "Te estoy derivando a un agente humano que te atenderá pronto."
    ),
}
# Generic fallback if media_type is not in the dict
DEFAULT_MEDIA_HANDOFF_MESSAGE = (
    "No puedo procesar este tipo de contenido. "
    "Te estoy derivando a un agente humano que te atenderá pronto."
)

# =============================================================================
# HTTP Settings
# =============================================================================
DEFAULT_HTTP_TIMEOUT_CONNECT = 10.0
DEFAULT_HTTP_MAX_CONNECTIONS = 100
DEFAULT_HTTP_MAX_KEEPALIVE = 20

# =============================================================================
# Event Processing
# =============================================================================
MESSAGE_DELAY_SECONDS = 1.0  # Delay between messages for natural pacing
