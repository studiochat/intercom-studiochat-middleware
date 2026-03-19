"""HTML utility functions."""

import re

import html2text


def strip_html_tags(html_content: str) -> str:
    """
    Convert HTML content to plain text.

    Handles common HTML elements from Intercom messages:
    - Paragraphs
    - Line breaks
    - Links (preserves URL)
    - Bold/italic text
    - Lists

    Args:
        html_content: HTML string to convert

    Returns:
        Plain text version of the content
    """
    if not html_content:
        return ""

    # Configure html2text
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0  # Don't wrap lines

    # Convert to markdown-like text
    text: str = h.handle(html_content)

    # Clean up excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def is_whatsapp_reaction(html_content: str) -> bool:
    """
    Check if the message is a WhatsApp reaction (not a real message).

    WhatsApp reactions appear as messages like:
    - "Reacted with 👍" (simple reaction)
    - "Reacted to \"Hello\" with 👍" (reaction to a specific message)

    These should be ignored as they're not real user messages.

    Args:
        html_content: HTML content of the message

    Returns:
        True if this is a reaction, not a real message
    """
    if not html_content:
        return False

    # Match both "Reacted with" and "Reacted to ... with" patterns
    return "<p>Reacted with" in html_content or "<p>Reacted to" in html_content


def is_whatsapp_error(html_content: str) -> bool:
    """
    Check if the message is a WhatsApp error notification.

    These are system messages from WhatsApp Business Platform about
    delivery failures, etc.

    Args:
        html_content: HTML content of the message

    Returns:
        True if this is an error notification
    """
    if not html_content:
        return False

    return "WhatsApp Business Platform was unable to" in html_content


def is_image_message(html_content: str) -> bool:
    """
    Check if the message contains an image.

    Intercom image messages have HTML like:
    - <div class="intercom-container"><img src="..."></div>
    - <img src="https://downloads.intercomcdn.com/...">

    Args:
        html_content: HTML content of the message

    Returns:
        True if this is an image message
    """
    if not html_content:
        return False

    return "<img " in html_content or "<img>" in html_content


def is_audio_message(html_content: str) -> bool:
    """
    Check if the message is a WhatsApp audio clip.

    WhatsApp audio messages appear as:
    - <p>Sent an audio clip</p>

    Args:
        html_content: HTML content of the message

    Returns:
        True if this is an audio message
    """
    if not html_content:
        return False

    return "Sent an audio clip" in html_content


def is_video_message(html_content: str) -> bool:
    """
    Check if the message contains a video.

    Args:
        html_content: HTML content of the message

    Returns:
        True if this is a video message
    """
    if not html_content:
        return False

    return "<video " in html_content or "<video>" in html_content


def is_media_message(html_content: str, attachments: list[dict[str, str]] | None = None) -> bool:
    """
    Check if the message contains media (image, audio, video, or attachments).

    These messages cannot be processed by the AI and should trigger a handoff.

    Args:
        html_content: HTML content of the message
        attachments: List of attachments from the conversation part

    Returns:
        True if this is a media message that should trigger handoff
    """
    if is_image_message(html_content):
        return True
    if is_audio_message(html_content):
        return True
    if is_video_message(html_content):
        return True
    if attachments and len(attachments) > 0:
        return True
    return False


def extract_image_urls(html_content: str) -> list[str]:
    """
    Extract image URLs from HTML content.

    Intercom image messages have HTML like:
    - <div class="intercom-container"><img src="..."></div>
    - <img src="https://downloads.intercomcdn.com/...">

    Args:
        html_content: HTML content of the message

    Returns:
        List of image URLs found in the content
    """
    if not html_content:
        return []

    # Match src attribute in img tags (handles both single and double quotes)
    pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    matches = re.findall(pattern, html_content, re.IGNORECASE)
    return matches
