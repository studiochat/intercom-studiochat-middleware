# Claude Code Guide

This document provides context for Claude Code agents working on the Intercom Studio Chat Bridge project.

## Project Overview

A FastAPI-based middleware that connects Intercom conversations with Studio Chat AI assistants. When a user sends a message in Intercom, the bridge routes it to the appropriate AI assistant and sends the response back.

## Studio Chat API

API specification: https://api.studiochat.io/openapi.json

## Architecture

```
Intercom Webhook → Bridge → Studio Chat API → Bridge → Intercom Reply
```

**Key Flow:**
1. Intercom sends webhook (`conversation.user.replied` or `conversation.admin.assigned`)
2. Bridge returns 200 immediately (Intercom has 5-second timeout)
3. Background task processes the message:
   - Fetches conversation from Intercom API (security: never trust webhook data)
   - Matches routing rules to find the right assistant
   - Sends message to Studio Chat API
   - Processes response events (message, note, handoff, etc.)
   - Sends reply back to Intercom

## Project Structure

```
bridge/                 # Main application package
├── app.py             # FastAPI app, endpoints, main orchestration
├── config.py          # YAML config loading with env var interpolation
├── models.py          # Pydantic models for config and data
├── constants.py       # Shared constants
├── context.py         # Context enrichment for Studio Chat
├── intercom/          # Intercom integration
│   ├── client.py      # HTTP client for Intercom API
│   ├── webhook.py     # Webhook parsing
│   └── actions.py     # High-level actions (send message, handoff, etc.)
├── studio_chat/       # Studio Chat integration
│   ├── client.py      # HTTP client for Studio Chat API
│   └── events.py      # Process AI response events
├── routing/           # Routing logic
│   ├── rules.py       # Match assistants by rules
│   └── rollout.py     # Percentage-based rollout
└── utils/             # Utilities
    ├── logging.py     # structlog setup
    └── html.py        # HTML to text conversion

tests/                 # Test suite
├── conftest.py        # Shared fixtures
├── test_e2e.py        # End-to-end tests (most comprehensive)
├── test_*.py          # Unit tests for each module
```

## Key Concepts

### Security Model
Intercom webhooks are NOT signed. The webhook is only a notification - we always fetch the actual message from the API and verify against the webhook hint. If they don't match, we reject the request.

### Configuration
- YAML-based config with `${ENV_VAR}` interpolation
- Loaded from `CONFIG_YAML` env var, `CONFIG_PATH`, or `./config.yaml`
- Validated with Pydantic models

### Routing Rules
Assistants are matched by:
- `inbox`: Match conversations in a specific inbox (team)
- `admin_assignment`: Match when assigned to a specific admin
- `tag`: Match conversations with a specific tag

**Rule Matching Logic:** When an assistant has multiple routing rules, ALL rules must match (AND logic). This allows combining conditions like "inbox X AND tag Y".

### Actions
When handoff or fallback is triggered:
- `add_tag`: Add a tag to the conversation
- `transfer_to_inbox`: Move to another inbox
- `assign_to_admin`: Assign to a specific admin
- `add_note`: Add a private note

## Development Commands

```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest

# Run tests with coverage
poetry run pytest --cov=bridge

# Type checking
poetry run mypy bridge/

# Linting
poetry run ruff check .

# Format code
poetry run ruff format .

# Run server locally
poetry run python -m bridge.app

# Run pre-commit hooks
poetry run pre-commit run --all-files
```

## Testing Approach

- Unit tests for individual modules
- E2E tests use `MockHttpClient` to simulate external APIs
- Tests use `patch` to inject mock config and HTTP client
- All external API calls are mocked - no real network calls in tests

### Running specific tests

```bash
# Run single test file
poetry run pytest tests/test_e2e.py

# Run specific test class
poetry run pytest tests/test_e2e.py::TestWebhookEndpointE2E

# Run with verbose output
poetry run pytest -v
```

## Common Tasks

### Adding a new routing rule type
1. Add to `RoutingRuleType` enum in `models.py`
2. Add field to `RoutingRule` model
3. Add matching logic in `routing/rules.py`
4. Add tests

### Adding a new action type
1. Add to `ActionType` enum in `models.py`
2. Add field to `Action` model
3. Implement in `intercom/actions.py` `execute_actions()`
4. Add tests

### Adding a new Studio Chat event type
1. Add to `StudioChatEventType` enum in `models.py`
2. Handle in `studio_chat/events.py` `process_events()`
3. Add tests

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe (always returns 200) |
| `/ready` | GET | Readiness probe (checks config + Studio Chat API) |
| `/webhooks/intercom` | POST | Webhook receiver |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STUDIO_CHAT_API_KEY` | Yes | Studio Chat API key |
| `INTERCOM_ACCESS_TOKEN` | Yes | Intercom access token |
| `CONFIG_YAML` | No | Raw YAML config (for serverless) |
| `CONFIG_PATH` | No | Path to config file |
| `PORT` | No | Server port (default: 8080) |
| `HOST` | No | Server host (default: 0.0.0.0) |

## Code Style

- Python 3.12
- Type hints everywhere (strict mypy)
- Ruff for linting and formatting
- structlog for structured logging
- Async/await throughout (FastAPI + httpx)
