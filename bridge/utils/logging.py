"""Logging utilities using loguru."""

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from loguru import Message, Record

# Context variable for request-scoped logging context
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


def _format_extra_dev(record: "Record") -> str:
    """Format extra context fields as key=value pairs for development."""
    extra = record.get("extra", {})
    # Filter out loguru's internal keys
    context_keys = {k: v for k, v in extra.items() if not k.startswith("_") and v is not None}
    if not context_keys:
        return ""
    return " | " + ", ".join(f"{k}={v}" for k, v in sorted(context_keys.items()))


def _json_sink(message: "Message") -> None:
    """Sink that outputs JSON to stderr for production.

    Includes 'level' field for log aggregators like Render that use it
    to map to syslog priority.
    """
    record = message.record
    extra = record.get("extra", {})
    # Filter out loguru's internal keys
    context_keys = {k: v for k, v in extra.items() if not k.startswith("_") and v is not None}

    # Build the message with location prefix
    msg = f"{record['name']}:{record['function']}:{record['line']} - {record['message']}"

    log_dict: dict[str, Any] = {
        "level": record["level"].name,
        "message": msg,
    }
    log_dict.update(context_keys)

    sys.stderr.write(json.dumps(log_dict, default=str) + "\n")


def _patcher(record: "Record") -> None:
    """Patch log records with context from ContextVar."""
    ctx = _log_context.get()
    record["extra"].update(ctx)


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru based on environment.

    In production (ENV=production), use JSON format for log aggregators.
    In development, use human-readable format with timestamp and level.

    Also intercepts standard library logs (uvicorn, httpx, etc.) and routes
    them through loguru for consistent formatting.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
    """
    logger.remove()  # Remove default handler
    logger.configure(patcher=_patcher)

    env = os.environ.get("ENV", "development")

    if env == "production":
        # JSON sink for log aggregators
        logger.add(_json_sink, level=level)
    else:
        # Development: human-readable format with timestamp and level
        fmt = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} - {message}{extra[_formatted]}"
        )

        def format_with_context(record: "Record") -> str:
            """Format function that adds context to each record."""
            record["extra"]["_formatted"] = _format_extra_dev(record)
            return fmt + "\n"

        logger.add(sys.stderr, format=format_with_context, level=level)

    # Disable uvicorn access logs (we have our own logging)
    logging.getLogger("uvicorn.access").disabled = True


def get_log_context() -> dict[str, Any]:
    """Get the current logging context."""
    return _log_context.get()


def bind_context(**kwargs: str | int | None) -> None:
    """
    Bind key-value pairs to the logging context.

    All subsequent log calls in this context will include these values.
    Use clear_context() to remove them when done.
    """
    ctx = _log_context.get().copy()
    ctx.update({k: v for k, v in kwargs.items() if v is not None})
    _log_context.set(ctx)


def clear_context() -> None:
    """Clear all bound context variables."""
    _log_context.set({})


def generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return str(uuid.uuid4())[:8]


# Re-export logger for convenience
__all__ = ["logger", "bind_context", "clear_context", "generate_request_id", "get_log_context"]
