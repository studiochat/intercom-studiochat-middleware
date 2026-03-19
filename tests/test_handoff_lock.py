"""Tests for handoff lock module."""

from unittest.mock import patch

from bridge.handoff_lock import (
    LOCK_DIR,
    clear_lock,
    get_locked_count,
    is_locked,
    mark_handoff,
)


class TestHandoffLock:
    """Tests for the handoff lock functions."""

    def test_mark_handoff_locks_conversation(self):
        """Marking a conversation for handoff should lock it."""
        mark_handoff("conv-123")
        assert is_locked("conv-123") is True

    def test_is_locked_returns_false_for_unlocked(self):
        """Unlocked conversations should return False."""
        assert is_locked("conv-not-locked") is False

    def test_clear_lock_unlocks_conversation(self):
        """Clearing the lock should unlock the conversation."""
        mark_handoff("conv-456")
        assert is_locked("conv-456") is True

        clear_lock("conv-456")
        assert is_locked("conv-456") is False

    def test_clear_lock_on_unlocked_does_not_error(self):
        """Clearing a non-existent lock should not raise an error."""
        clear_lock("conv-never-locked")  # Should not raise

    def test_get_locked_count(self):
        """Should return the number of locked conversations."""
        assert get_locked_count() == 0

        mark_handoff("conv-a")
        assert get_locked_count() == 1

        mark_handoff("conv-b")
        assert get_locked_count() == 2

        clear_lock("conv-a")
        assert get_locked_count() == 1

    def test_multiple_marks_same_conversation(self):
        """Marking the same conversation multiple times should be idempotent."""
        mark_handoff("conv-789")
        mark_handoff("conv-789")
        mark_handoff("conv-789")

        assert is_locked("conv-789") is True
        assert get_locked_count() == 1


class TestHandoffLockFixture:
    """Tests to verify the autouse fixture clears locks between tests."""

    def test_first_test_locks_conversation(self):
        """First test locks a conversation."""
        mark_handoff("fixture-test-conv")
        assert is_locked("fixture-test-conv") is True

    def test_second_test_should_not_see_lock(self):
        """Second test should not see the lock from the first test."""
        # The autouse fixture should have cleared the lock
        assert is_locked("fixture-test-conv") is False


class TestFailOpenBehavior:
    """Tests to verify fail-open behavior on filesystem errors."""

    def test_is_locked_returns_false_on_read_error(self):
        """is_locked should return False (fail open) if file read fails."""
        # Create a valid lock first
        mark_handoff("conv-error-test")
        assert is_locked("conv-error-test") is True

        # Simulate read error
        with patch.object(LOCK_DIR.__class__, "exists", return_value=True):
            with patch("pathlib.Path.read_text", side_effect=OSError("Disk error")):
                # Should return False (fail open), not raise
                result = is_locked("conv-error-test")
                assert result is False

    def test_is_locked_returns_false_on_invalid_content(self):
        """is_locked should return False if lock file has invalid content."""
        lock_file = LOCK_DIR / "conv-invalid"
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock_file.write_text("not-a-timestamp")

        # Should return False (invalid content), not raise
        assert is_locked("conv-invalid") is False

    def test_mark_handoff_continues_on_write_error(self):
        """mark_handoff should not raise on filesystem errors."""
        with patch("pathlib.Path.write_text", side_effect=OSError("Disk full")):
            # Should not raise, just log error
            mark_handoff("conv-write-error")  # No exception

    def test_mark_handoff_continues_on_mkdir_error(self):
        """mark_handoff should not raise if directory creation fails."""
        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            # Should not raise, just log error
            mark_handoff("conv-mkdir-error")  # No exception
