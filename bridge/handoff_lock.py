"""Filesystem-based lock for conversations in handoff state.

When a conversation enters handoff, no other actions should be performed
on it by the AI admin. This prevents race conditions where parallel requests
send messages that trigger self-assign, undoing the handoff transfer.

Uses file existence as lock mechanism - works across multiple processes
on the same instance without external dependencies.
"""

import time
from pathlib import Path

from loguru import logger

# Directory for lock files
LOCK_DIR = Path("/tmp/handoff_locks")

# Lock TTL in seconds (auto-expire old locks)
LOCK_TTL_SECONDS = 1800  # 30 minutes


def _ensure_lock_dir() -> None:
    """Ensure the lock directory exists."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _lock_path(conversation_id: str) -> Path:
    """Get the lock file path for a conversation."""
    # Sanitize conversation_id to be safe for filenames
    safe_id = conversation_id.replace("/", "_").replace("\\", "_")
    return LOCK_DIR / safe_id


def mark_handoff(conversation_id: str) -> None:
    """Mark a conversation as being in handoff state.

    Once marked, no further actions should be performed on this conversation.
    If lock creation fails, logs error but doesn't raise - handoff continues.

    Args:
        conversation_id: The conversation ID to mark
    """
    try:
        _ensure_lock_dir()
        lock_file = _lock_path(conversation_id)
        lock_file.write_text(str(time.time()))
        logger.info("Conversation marked for handoff lock: {}", conversation_id)
    except OSError as e:
        # Fail open: if we can't create lock, handoff still proceeds
        # Worst case: parallel request sends a message, but handoff completes
        logger.error("Failed to create handoff lock (continuing anyway): {}", e)


def is_locked(conversation_id: str) -> bool:
    """Check if a conversation is locked due to handoff.

    Fails open: if any filesystem error occurs, returns False (not locked)
    to ensure messages are still sent. Better to risk a re-assignment than
    to silently drop messages.

    Args:
        conversation_id: The conversation ID to check

    Returns:
        True if the conversation is in handoff state and should be skipped
    """
    try:
        lock_file = _lock_path(conversation_id)

        if not lock_file.exists():
            return False

        # Check TTL - auto-expire old locks
        locked_at = float(lock_file.read_text())
        if time.time() - locked_at > LOCK_TTL_SECONDS:
            # Lock expired, clean it up
            lock_file.unlink(missing_ok=True)
            logger.debug("Expired lock cleaned up: {}", conversation_id)
            return False

        return True
    except (ValueError, OSError) as e:
        # Fail open: any error means "not locked" - send the message
        logger.warning("Lock check failed (assuming unlocked): {}", e)
        return False


def clear_lock(conversation_id: str) -> None:
    """Clear the handoff lock for a conversation.

    Called after handoff is complete or if cleanup is needed.

    Args:
        conversation_id: The conversation ID to clear
    """
    lock_file = _lock_path(conversation_id)
    lock_file.unlink(missing_ok=True)
    logger.debug("Conversation handoff lock cleared: {}", conversation_id)


def get_locked_count() -> int:
    """Get the number of conversations currently locked.

    Useful for monitoring/debugging.

    Returns:
        Number of locked conversations
    """
    if not LOCK_DIR.exists():
        return 0
    return len(list(LOCK_DIR.iterdir()))


def clear_all_locks() -> None:
    """Clear all locks. Used for testing."""
    if LOCK_DIR.exists():
        for lock_file in LOCK_DIR.iterdir():
            lock_file.unlink(missing_ok=True)
