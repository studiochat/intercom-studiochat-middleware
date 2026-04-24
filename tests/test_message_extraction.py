"""Unit tests for message extraction functions in app.py.

These tests verify the logic for extracting user messages from conversations
and determining whether admin replies exist. The key behavior tested is that
only actual comment replies count as "replies" - not admin noise like notes,
assignments, or attribute updates.
"""

from bridge.app import (
    _detect_media_type,
    _extract_attachment_document_info,
    _extract_attachment_image_urls,
    _extract_last_user_message,
    _find_last_user_message_in_parts,
    _has_admin_comment_reply,
    _has_admin_reply_after_index,
    _is_document_attachment,
    _is_image_attachment,
)


class TestHasAdminReplyAfterIndex:
    """Tests for _has_admin_reply_after_index function."""

    def test_admin_comment_after_user_message(self):
        """Admin comment after user message should count as reply."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "admin"}, "body": "Hi there!", "part_type": "comment"},
        ]
        # Check if there's a reply after index 0 (user message)
        assert _has_admin_reply_after_index(parts, 0) is True

    def test_bot_comment_after_user_message(self):
        """Bot comment after user message should count as reply."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "bot"}, "body": "Automated response", "part_type": "comment"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is True

    def test_admin_note_after_user_message(self):
        """Admin note after user message should NOT count as reply (it's internal noise)."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "admin"}, "body": "Internal note", "part_type": "note"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is False

    def test_admin_assignment_after_user_message(self):
        """Admin assignment after user message should NOT count as reply."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "admin"}, "body": "", "part_type": "assignment"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is False

    def test_multiple_noise_events_no_comment(self):
        """Multiple admin noise events without a comment should NOT count as reply."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "admin"}, "body": "Note 1", "part_type": "note"},
            {"author": {"type": "admin"}, "body": "", "part_type": "assignment"},
            {"author": {"type": "admin"}, "body": "Note 2", "part_type": "note"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is False

    def test_noise_then_comment(self):
        """Admin comment should be detected even after noise events."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "admin"}, "body": "Note", "part_type": "note"},
            {"author": {"type": "admin"}, "body": "", "part_type": "assignment"},
            {"author": {"type": "admin"}, "body": "Actual reply", "part_type": "comment"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is True

    def test_no_parts_after_index(self):
        """No reply when there are no parts after the index."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is False

    def test_user_message_after_user_message(self):
        """User message after user message should NOT count as reply."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
            {"author": {"type": "user"}, "body": "Follow up", "part_type": "comment"},
        ]
        assert _has_admin_reply_after_index(parts, 0) is False


class TestHasAdminCommentReply:
    """Tests for _has_admin_comment_reply function."""

    def test_admin_comment_exists(self):
        """Should return True when admin comment exists."""
        parts = [
            {"author": {"type": "admin"}, "body": "Reply", "part_type": "comment"},
        ]
        assert _has_admin_comment_reply(parts) is True

    def test_only_admin_notes(self):
        """Should return False when only admin notes exist."""
        parts = [
            {"author": {"type": "admin"}, "body": "Note", "part_type": "note"},
        ]
        assert _has_admin_comment_reply(parts) is False

    def test_empty_parts(self):
        """Should return False for empty parts list."""
        assert _has_admin_comment_reply([]) is False

    def test_only_user_messages(self):
        """Should return False when only user messages exist."""
        parts = [
            {"author": {"type": "user"}, "body": "Hello", "part_type": "comment"},
        ]
        assert _has_admin_comment_reply(parts) is False


class TestFindLastUserMessageInParts:
    """Tests for _find_last_user_message_in_parts function."""

    def test_single_user_message(self):
        """Should find single user message."""
        parts = [
            {"author": {"type": "user"}, "body": "<p>Hello</p>", "part_type": "comment"},
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message == "Hello"
        assert index == 0
        assert has_media is False
        assert media_type is None
        assert image_urls is None

    def test_multiple_user_messages(self):
        """Should find the last user message."""
        parts = [
            {"author": {"type": "user"}, "body": "<p>First</p>", "part_type": "comment"},
            {"author": {"type": "admin"}, "body": "Reply", "part_type": "comment"},
            {"author": {"type": "user"}, "body": "<p>Second</p>", "part_type": "comment"},
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message == "Second"
        assert index == 2
        assert has_media is False
        assert media_type is None
        assert image_urls is None

    def test_lead_author_type(self):
        """Should recognize 'lead' as a user author type."""
        parts = [
            {"author": {"type": "lead"}, "body": "<p>Lead message</p>", "part_type": "comment"},
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message == "Lead message"
        assert index == 0
        assert has_media is False
        assert image_urls is None

    def test_contact_author_type(self):
        """Should recognize 'contact' as a user author type."""
        parts = [
            {
                "author": {"type": "contact"},
                "body": "<p>Contact message</p>",
                "part_type": "comment",
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message == "Contact message"
        assert index == 0
        assert has_media is False
        assert image_urls is None

    def test_no_user_messages(self):
        """Should return None when no user messages exist."""
        parts = [
            {"author": {"type": "admin"}, "body": "Admin message", "part_type": "comment"},
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None
        assert index == -1
        assert has_media is False
        assert image_urls is None

    def test_empty_parts(self):
        """Should return None for empty parts list."""
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts([])
        )
        assert message is None
        assert index == -1
        assert has_media is False
        assert image_urls is None

    def test_empty_body(self):
        """Should skip user messages with empty body."""
        parts = [
            {"author": {"type": "user"}, "body": "", "part_type": "comment"},
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None
        assert index == -1
        assert has_media is False
        assert image_urls is None

    def test_whatsapp_reaction_skipped(self):
        """Should skip WhatsApp reactions."""
        parts = [
            {
                "author": {"type": "user"},
                "body": '<p>Reacted to "Hello" with 👍</p>',
                "part_type": "comment",
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None
        assert index == -1
        assert has_media is False
        assert image_urls is None

    def test_whatsapp_error_skipped(self):
        """Should skip WhatsApp error messages."""
        parts = [
            {
                "author": {"type": "user"},
                "body": "<p>WhatsApp Business Platform was unable to deliver the message</p>",
                "part_type": "comment",
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None
        assert index == -1
        assert has_media is False
        assert image_urls is None

    def test_image_message_detected(self):
        """Should detect image messages and extract URLs."""
        parts = [
            {
                "author": {"type": "user"},
                "body": '<div class="intercom-container"><img src="https://example.com/image.png"></div>',
                "part_type": "comment",
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None  # No text besides the image
        assert index == 0
        assert has_media is True
        assert media_type == "image"
        assert image_urls == ["https://example.com/image.png"]

    def test_audio_message_detected(self):
        """Should detect audio messages."""
        parts = [
            {
                "author": {"type": "user"},
                "body": "<p>Sent an audio clip</p>",
                "part_type": "comment",
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None
        assert index == 0
        assert has_media is True
        assert media_type == "audio"
        assert image_urls is None

    def test_document_attachment_detected(self):
        """Should detect document attachments (PDF)."""
        parts = [
            {
                "author": {"type": "user"},
                "body": "<p>Here is a file</p>",
                "part_type": "comment",
                "attachments": [{"url": "https://example.com/file.pdf"}],
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message == "Here is a file"
        assert index == 0
        assert has_media is True
        assert media_type == "document"
        assert image_urls is None
        assert doc_atts == [
            {"url": "https://example.com/file.pdf", "content_type": "", "filename": ""}
        ]

    def test_unsupported_attachment_detected(self):
        """Should detect unsupported attachments (ZIP)."""
        parts = [
            {
                "author": {"type": "user"},
                "body": "<p>Here is a file</p>",
                "part_type": "comment",
                "attachments": [
                    {"url": "https://example.com/file.zip", "content_type": "application/zip"}
                ],
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message is None
        assert index == 0
        assert has_media is True
        assert media_type == "attachment"
        assert image_urls is None
        assert doc_atts is None

    def test_text_after_media_returns_text(self):
        """Text message after media should return the text, not media."""
        parts = [
            {
                "author": {"type": "user"},
                "body": '<img src="https://example.com/image.png">',
                "part_type": "comment",
            },
            {
                "author": {"type": "user"},
                "body": "<p>Here is more context</p>",
                "part_type": "comment",
            },
        ]
        message, index, has_media, media_type, image_urls, doc_atts = (
            _find_last_user_message_in_parts(parts)
        )
        assert message == "Here is more context"
        assert index == 1
        assert has_media is False
        assert media_type is None
        assert image_urls is None


class TestExtractLastUserMessage:
    """Tests for _extract_last_user_message function."""

    def test_user_message_in_parts_no_reply(self):
        """Should return user message when no admin reply exists."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "Initial"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Follow up</p>",
                        "part_type": "comment",
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "Follow up"
        assert result.has_media is False

    def test_user_message_in_parts_has_admin_comment_reply(self):
        """Should return empty result when admin has already replied with a comment."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "Initial"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Follow up</p>",
                        "part_type": "comment",
                    },
                    {"author": {"type": "admin"}, "body": "Reply", "part_type": "comment"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is False

    def test_user_message_in_parts_has_admin_note_only(self):
        """Should return user message when admin only added a note (not a reply)."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "Initial"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Follow up</p>",
                        "part_type": "comment",
                    },
                    {"author": {"type": "admin"}, "body": "Internal note", "part_type": "note"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "Follow up"
        assert result.has_media is False

    def test_user_message_in_parts_has_assignment_only(self):
        """Should return user message when admin only assigned (not replied)."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "Initial"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Follow up</p>",
                        "part_type": "comment",
                    },
                    {"author": {"type": "admin"}, "body": "", "part_type": "assignment"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "Follow up"
        assert result.has_media is False

    def test_user_message_with_multiple_noise_events(self):
        """Should return user message even with multiple admin noise events."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "Initial"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Need help</p>",
                        "part_type": "comment",
                    },
                    {"author": {"type": "admin"}, "body": "Note 1", "part_type": "note"},
                    {"author": {"type": "admin"}, "body": "", "part_type": "assignment"},
                    {"author": {"type": "admin"}, "body": "Note 2", "part_type": "note"},
                    {"author": {"type": "bot"}, "body": "", "part_type": "attribute_collected"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "Need help"
        assert result.has_media is False

    def test_source_message_no_parts(self):
        """Should return source message when no conversation parts exist."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial message</p>"},
            "conversation_parts": {"conversation_parts": []},
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "Initial message"
        assert result.has_media is False

    def test_source_message_with_admin_comment_reply(self):
        """Should return empty result when source already has admin comment reply."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial message</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {"author": {"type": "admin"}, "body": "Reply", "part_type": "comment"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is False

    def test_source_message_with_admin_note_only(self):
        """Should return source message when admin only added a note."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial message</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {"author": {"type": "admin"}, "body": "Note", "part_type": "note"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "Initial message"
        assert result.has_media is False

    def test_no_user_messages_anywhere(self):
        """Should return empty result when no user messages exist."""
        conversation = {
            "source": {"author": {"type": "admin"}, "body": "Admin initiated"},
            "conversation_parts": {
                "conversation_parts": [
                    {"author": {"type": "admin"}, "body": "Reply", "part_type": "comment"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is False

    def test_empty_conversation(self):
        """Should return empty result for empty conversation."""
        conversation = {
            "source": {},
            "conversation_parts": {"conversation_parts": []},
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is False

    def test_real_world_scenario_assignment_then_user_message(self):
        """Real-world scenario: Admin assigns, user sends message, should process it."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "admin"},
                        "body": "Assigned to bot",
                        "part_type": "assignment",
                    },
                    {
                        "author": {"type": "user"},
                        "body": "<p>New message after assignment</p>",
                        "part_type": "comment",
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message == "New message after assignment"
        assert result.has_media is False

    def test_image_in_parts_detected(self):
        """Should detect image in conversation parts."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": '<img src="https://example.com/image.png">',
                        "part_type": "comment",
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is True
        assert result.media_type == "image"

    def test_audio_in_parts_detected(self):
        """Should detect audio in conversation parts."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Sent an audio clip</p>",
                        "part_type": "comment",
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is True
        assert result.media_type == "audio"

    def test_image_in_source_detected(self):
        """Should detect image in source message."""
        conversation = {
            "source": {
                "author": {"type": "user"},
                "body": '<img src="https://example.com/image.png">',
            },
            "conversation_parts": {"conversation_parts": []},
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is True
        assert result.media_type == "image"

    def test_media_with_existing_admin_reply_skipped(self):
        """Media message should be skipped if admin already replied."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": '<img src="https://example.com/image.png">',
                        "part_type": "comment",
                    },
                    {"author": {"type": "admin"}, "body": "Got it!", "part_type": "comment"},
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.message is None
        assert result.has_media is False  # Skipped because already replied

    def test_whatsapp_image_attachment_in_parts(self):
        """WhatsApp image sent as attachment should be detected as image, not generic attachment."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Hola</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "name": "foto.jpg",
                                "url": "https://downloads.intercomcdn.com/i/o/abc/image.jpg",
                                "content_type": "image/jpeg",
                                "filesize": 90255,
                                "width": 1024,
                                "height": 768,
                            }
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "image"
        assert result.image_urls == ["https://downloads.intercomcdn.com/i/o/abc/image.jpg"]

    def test_whatsapp_image_attachment_in_source(self):
        """WhatsApp image in source should be detected as image."""
        conversation = {
            "source": {
                "author": {"type": "user"},
                "body": "",
                "attachments": [
                    {
                        "type": "upload",
                        "url": "https://downloads.intercomcdn.com/i/o/abc/photo.png",
                        "content_type": "image/png",
                    }
                ],
            },
            "conversation_parts": {"conversation_parts": []},
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "image"
        assert result.image_urls == ["https://downloads.intercomcdn.com/i/o/abc/photo.png"]

    def test_pdf_attachment_detected_as_document(self):
        """PDF attachments should be classified as 'document'."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Hola</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "name": "doc.pdf",
                                "url": "https://example.com/doc.pdf",
                                "content_type": "application/pdf",
                            }
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "document"
        assert result.image_urls is None
        assert result.document_attachments == [
            {
                "url": "https://example.com/doc.pdf",
                "content_type": "application/pdf",
                "filename": "doc.pdf",
            },
        ]

    def test_txt_attachment_detected_as_document(self):
        """TXT attachments should be classified as 'document'."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Hola</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "name": "notes.txt",
                                "url": "https://example.com/notes.txt",
                                "content_type": "text/plain",
                            }
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "document"
        assert result.document_attachments == [
            {
                "url": "https://example.com/notes.txt",
                "content_type": "text/plain",
                "filename": "notes.txt",
            },
        ]

    def test_mixed_image_and_pdf_detected_as_mixed(self):
        """Mixed attachments (image + PDF) should be classified as 'mixed'."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Hola</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "url": "https://example.com/photo.jpg",
                                "content_type": "image/jpeg",
                            },
                            {
                                "type": "upload",
                                "name": "doc.pdf",
                                "url": "https://example.com/doc.pdf",
                                "content_type": "application/pdf",
                            },
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "mixed"
        assert result.image_urls == ["https://example.com/photo.jpg"]
        assert result.document_attachments == [
            {
                "url": "https://example.com/doc.pdf",
                "content_type": "application/pdf",
                "filename": "doc.pdf",
            },
        ]

    def test_unsupported_attachment_still_triggers_attachment(self):
        """Unsupported attachment types (e.g., ZIP) should still classify as 'attachment'."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Hola</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "url": "https://example.com/archive.zip",
                                "content_type": "application/zip",
                            }
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "attachment"

    def test_mixed_document_and_unsupported_is_attachment(self):
        """Mix of document + unsupported should classify as 'attachment' (handoff)."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Hola</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "url": "https://example.com/doc.pdf",
                                "content_type": "application/pdf",
                            },
                            {
                                "type": "upload",
                                "url": "https://example.com/archive.zip",
                                "content_type": "application/zip",
                            },
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "attachment"

    def test_document_with_text(self):
        """Document attachment with caption text should return both."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Mira este documento</p>",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "name": "informe.pdf",
                                "url": "https://example.com/informe.pdf",
                                "content_type": "application/pdf",
                            }
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "document"
        assert result.message == "Mira este documento"
        assert result.document_attachments == [
            {
                "url": "https://example.com/informe.pdf",
                "content_type": "application/pdf",
                "filename": "informe.pdf",
            },
        ]

    def test_whatsapp_image_attachment_with_text(self):
        """WhatsApp image with caption text should return both."""
        conversation = {
            "source": {"author": {"type": "user"}, "body": "<p>Initial</p>"},
            "conversation_parts": {
                "conversation_parts": [
                    {
                        "author": {"type": "user"},
                        "body": "<p>Mira esta foto</p>",
                        "part_type": "comment",
                        "attachments": [
                            {
                                "type": "upload",
                                "url": "https://downloads.intercomcdn.com/i/o/abc/img.jpg",
                                "content_type": "image/jpeg",
                            }
                        ],
                    },
                ]
            },
        }
        result = _extract_last_user_message(conversation)
        assert result.has_media is True
        assert result.media_type == "image"
        assert result.message == "Mira esta foto"
        assert result.image_urls == ["https://downloads.intercomcdn.com/i/o/abc/img.jpg"]


class TestIsImageAttachment:
    """Tests for _is_image_attachment helper."""

    def test_jpeg_content_type(self):
        assert _is_image_attachment({"content_type": "image/jpeg", "url": "x"}) is True

    def test_png_content_type(self):
        assert _is_image_attachment({"content_type": "image/png", "url": "x"}) is True

    def test_pdf_content_type(self):
        assert _is_image_attachment({"content_type": "application/pdf", "url": "x"}) is False

    def test_no_content_type_image_url(self):
        """Should fallback to URL extension when content_type is missing."""
        assert _is_image_attachment({"url": "https://example.com/photo.jpg"}) is True

    def test_no_content_type_pdf_url(self):
        assert _is_image_attachment({"url": "https://example.com/doc.pdf"}) is False

    def test_not_a_dict(self):
        assert _is_image_attachment("not a dict") is False

    def test_empty_dict(self):
        assert _is_image_attachment({}) is False


class TestExtractAttachmentImageUrls:
    """Tests for _extract_attachment_image_urls helper."""

    def test_extracts_image_urls(self):
        attachments = [
            {"content_type": "image/jpeg", "url": "https://example.com/a.jpg"},
            {"content_type": "image/png", "url": "https://example.com/b.png"},
        ]
        assert _extract_attachment_image_urls(attachments) == [
            "https://example.com/a.jpg",
            "https://example.com/b.png",
        ]

    def test_skips_non_image_attachments(self):
        attachments = [
            {"content_type": "image/jpeg", "url": "https://example.com/a.jpg"},
            {"content_type": "application/pdf", "url": "https://example.com/b.pdf"},
        ]
        assert _extract_attachment_image_urls(attachments) == [
            "https://example.com/a.jpg",
        ]

    def test_empty_list(self):
        assert _extract_attachment_image_urls([]) == []


class TestIsDocumentAttachment:
    """Tests for _is_document_attachment helper."""

    def test_pdf_content_type(self):
        assert _is_document_attachment({"content_type": "application/pdf", "url": "x"}) is True

    def test_txt_content_type(self):
        assert _is_document_attachment({"content_type": "text/plain", "url": "x"}) is True

    def test_image_content_type(self):
        assert _is_document_attachment({"content_type": "image/jpeg", "url": "x"}) is False

    def test_zip_content_type(self):
        assert _is_document_attachment({"content_type": "application/zip", "url": "x"}) is False

    def test_no_content_type_pdf_url(self):
        assert _is_document_attachment({"url": "https://example.com/doc.pdf"}) is True

    def test_no_content_type_txt_url(self):
        assert _is_document_attachment({"url": "https://example.com/notes.txt"}) is True

    def test_no_content_type_jpg_url(self):
        assert _is_document_attachment({"url": "https://example.com/photo.jpg"}) is False

    def test_not_a_dict(self):
        assert _is_document_attachment("not a dict") is False

    def test_empty_dict(self):
        assert _is_document_attachment({}) is False


class TestExtractAttachmentDocumentInfo:
    """Tests for _extract_attachment_document_info helper."""

    def test_extracts_document_info(self):
        attachments = [
            {
                "content_type": "application/pdf",
                "url": "https://example.com/a.pdf",
                "name": "a.pdf",
            },
            {"content_type": "text/plain", "url": "https://example.com/b.txt", "name": "b.txt"},
        ]
        assert _extract_attachment_document_info(attachments) == [
            {
                "url": "https://example.com/a.pdf",
                "content_type": "application/pdf",
                "filename": "a.pdf",
            },
            {"url": "https://example.com/b.txt", "content_type": "text/plain", "filename": "b.txt"},
        ]

    def test_skips_non_document_attachments(self):
        attachments = [
            {
                "content_type": "application/pdf",
                "url": "https://example.com/a.pdf",
                "name": "a.pdf",
            },
            {"content_type": "image/jpeg", "url": "https://example.com/b.jpg"},
        ]
        assert _extract_attachment_document_info(attachments) == [
            {
                "url": "https://example.com/a.pdf",
                "content_type": "application/pdf",
                "filename": "a.pdf",
            },
        ]

    def test_empty_list(self):
        assert _extract_attachment_document_info([]) == []

    def test_missing_name(self):
        attachments = [
            {"content_type": "application/pdf", "url": "https://example.com/a.pdf"},
        ]
        assert _extract_attachment_document_info(attachments) == [
            {"url": "https://example.com/a.pdf", "content_type": "application/pdf", "filename": ""},
        ]


class TestDetectMediaType:
    """Tests for _detect_media_type with attachment image detection."""

    def test_inline_image_in_body(self):
        assert _detect_media_type('<img src="x">', None) == "image"

    def test_image_attachment(self):
        atts = [{"content_type": "image/jpeg", "url": "https://example.com/a.jpg"}]
        assert _detect_media_type("", atts) == "image"

    def test_pdf_attachment(self):
        atts = [{"content_type": "application/pdf", "url": "https://example.com/a.pdf"}]
        assert _detect_media_type("", atts) == "document"

    def test_txt_attachment(self):
        atts = [{"content_type": "text/plain", "url": "https://example.com/a.txt"}]
        assert _detect_media_type("", atts) == "document"

    def test_mixed_image_and_document(self):
        atts = [
            {"content_type": "image/jpeg", "url": "https://example.com/a.jpg"},
            {"content_type": "application/pdf", "url": "https://example.com/b.pdf"},
        ]
        assert _detect_media_type("", atts) == "mixed"

    def test_unsupported_attachment(self):
        atts = [{"content_type": "application/zip", "url": "https://example.com/a.zip"}]
        assert _detect_media_type("", atts) == "attachment"

    def test_mixed_document_and_unsupported(self):
        """Unsupported attachment in the mix should trigger 'attachment' (handoff)."""
        atts = [
            {"content_type": "application/pdf", "url": "https://example.com/a.pdf"},
            {"content_type": "application/zip", "url": "https://example.com/b.zip"},
        ]
        assert _detect_media_type("", atts) == "attachment"

    def test_audio_body(self):
        assert _detect_media_type("<p>Sent an audio clip</p>", None) == "audio"

    def test_no_media(self):
        assert _detect_media_type("<p>Hello</p>", None) is None
