# Intercom Studio Chat Middleware

[![CI](https://github.com/studiochat/intercom-studiochat-middleware/actions/workflows/ci.yml/badge.svg)](https://github.com/studiochat/intercom-studiochat-middleware/actions/workflows/ci.yml)

A lightweight, open-source middleware that connects [Intercom](https://www.intercom.com/) with AI-powered chatbots via Studio Chat API. Route conversations to AI assistants based on configurable rules, with full support for handoff to human agents.

## Features

- **Declarative YAML Configuration**: Define routing rules, assistants, and handoff behavior in a simple YAML file
- **Multiple Assistants**: Support multiple AI playbooks with independent routing rules
- **Flexible Routing**: Route conversations based on inbox, tags, or admin assignment
- **Gradual Rollout**: Control the percentage of conversations handled by AI per assistant
- **Handoff to Humans**: Configurable actions when AI requests handoff (transfer inbox, assign admin, add tags)
- **Media Message Handling**: Automatic handoff when users send images, audio, video, or attachments
- **Fallback Handling**: Automatic fallback actions when AI is unavailable or conversation excluded from rollout
- **100% Async**: Built with FastAPI and httpx for high performance
- **Easy Deployment**: Docker-ready with health checks

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/studiochat/intercom-studiochat-middleware.git
cd intercom-studiochat-middleware
```

### 2. Install dependencies

```bash
# Using Poetry (recommended)
poetry install

# Or using pip
pip install -e .
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Create your configuration

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
```

### 5. Run the server

```bash
# Using Poetry
poetry run python -m bridge.app

# Or using Docker
docker-compose up
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STUDIO_CHAT_API_KEY` | Yes | API key for Studio Chat authentication |
| `STUDIO_CHAT_BASE_URL` | No | Base URL of the Studio Chat API (default: `https://api.studiochat.io`) |
| `INTERCOM_ACCESS_TOKEN` | Yes | Intercom API access token |
| `ROLLOUT_PERCENTAGE` | No | Percentage of conversations to route to AI (0-100, default: 100) |
| `PORT` | No | Server port (default: 8080) |
| `HOST` | No | Server host (default: 0.0.0.0) |
| `CONFIG_YAML` | No | Raw YAML configuration content (for platforms without filesystem access) |
| `CONFIG_PATH` | No | Path to config file (default: ./config.yaml) |

**Configuration priority:** `CONFIG_YAML` > `CONFIG_PATH` > `./config.yaml`

### YAML Configuration

```yaml
# config.yaml

# Studio Chat settings
studio_chat:
  api_key: ${STUDIO_CHAT_API_KEY}
  # base_url: https://api.studiochat.io  # Optional, this is the default
  timeout_seconds: 120

# Global Intercom settings
intercom:
  access_token: ${INTERCOM_ACCESS_TOKEN}

# Logging configuration
logging:
  level: INFO      # DEBUG, INFO, WARNING, ERROR
  format: json     # json or text

# Define your AI assistants
assistants:
  - playbook_id: "your-playbook-id"
    admin_id: "intercom-admin-id"

    rollout:
      # Can use env var: ${ROLLOUT_PERCENTAGE}
      percentage: ${ROLLOUT_PERCENTAGE}

    routing_rules:
      - type: inbox
        inbox_id: "sales-inbox-id"

    handoff:
      # Note: A handoff note (🤖→👤 {reason}) is always added automatically
      actions:
        - type: add_tag
          tag_name: "ai-handoff"
        - type: transfer_to_inbox
          inbox_id: "human-inbox-id"

    fallback:
      actions:
        - type: transfer_to_inbox
          inbox_id: "human-inbox-id"
```

### Routing Rules

| Type | Field | Description |
|------|-------|-------------|
| `inbox` | `inbox_id` | Match conversations assigned to a specific inbox (team) |
| `admin_assignment` | `admin_id` | Match when assigned to a specific admin |

### Actions

| Type | Fields | Description |
|------|--------|-------------|
| `add_tag` | `tag_name` | Add a tag to the conversation |
| `transfer_to_inbox` | `inbox_id` | Transfer to another inbox |
| `assign_to_admin` | `admin_id` | Assign to a specific admin |
| `add_note` | `template` | Add a private note (supports `{reason}` placeholder) |

### Media Message Handling

When users send media (images, audio, video, or file attachments) that the AI cannot process, the middleware automatically:

1. Sends a user-facing message explaining the limitation
2. Executes the configured handoff actions

**Default messages (Spanish):**
- Image: "No puedo procesar imágenes. Te estoy derivando a un agente humano..."
- Audio: "No puedo procesar mensajes de audio. Te estoy derivando..."
- Video: "No puedo procesar videos. Te estoy derivando..."
- Attachment: "No puedo procesar archivos adjuntos. Te estoy derivando..."

**Customize messages per assistant:**

```yaml
handoff:
  # Custom messages for media handoff (optional)
  media_handoff_messages:
    image: "I can't process images. Transferring you to a human agent who will assist you shortly."
    audio: "I can't process audio messages. Transferring you to a human agent."
    video: "I can't process videos. Transferring you to a human agent."
    attachment: "I can't process file attachments. Transferring you to a human agent."

  # Regular handoff actions still apply
  actions:
    - type: transfer_to_inbox
      inbox_id: "human-inbox-id"
```

### Context Enrichment

Send additional contact and conversation data to Studio Chat for personalized AI responses:

```yaml
context:
  # Contact attributes (fetched from Intercom API)
  contact_attributes:
    - email
    - name
    - phone
    - external_id
    - "custom_attributes.Plan Type"        # Supports spaces in keys
    - "custom_attributes.Subscription Status"

  # Conversation attributes
  conversation_attributes:
    - "custom_attributes.Ticket Priority"
    - "custom_attributes.Department"

  # Static values always included
  static:
    platform: intercom
    source: webhook
```

This sends a context object to Studio Chat:
```json
{
  "platform": "intercom",
  "source": "webhook",
  "contact": {
    "email": "user@example.com",
    "name": "John Doe",
    "Plan Type": "premium"
  },
  "conversation": {
    "Ticket Priority": "high"
  }
}
```

**Note:** Contact enrichment requires the "Read one user and one company" permission.

## Intercom App Setup

### 1. Create an Intercom App

1. Go to the [Intercom Developer Hub](https://developers.intercom.com/)
2. Click **Your Apps** in the top right
3. Click **New app**
4. Enter a name (e.g., "Studio Chat Middleware") and select your workspace
5. Click **Create app**

### 2. Configure Permissions

Navigate to **Authentication** > **Edit scopes** and enable these permissions:

**People and conversation data:**
| Permission | Description | Required |
|------------|-------------|----------|
| Read conversations | View conversations | Yes |
| Write conversations | Reply to, mark as read and close conversations | Yes |
| Read tags | List all tags | Yes |
| Write tags | Create, update, use and delete tags | Yes |
| Read one user and one company | View a single user and company | For context enrichment |

The last permission is only required if you configure `contact_attributes` in the context section to fetch additional contact data.

### 3. Get Your Access Token

1. Go to **Authentication** in your app settings
2. Copy the **Access token**
3. Add it to your `.env` file as `INTERCOM_ACCESS_TOKEN`

### 4. Find Your Admin ID

The `admin_id` in your config is the ID of the bot/admin that will send messages. To find it:

```bash
curl https://api.intercom.io/admins \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Accept: application/json"
```

Look for the admin you want to use and copy its `id` field.

### 5. Configure Webhooks

1. Navigate to **Webhooks** in your app settings
2. Click **Add webhook**
3. Set the URL to: `https://your-domain.com/webhooks/intercom`
4. Select these topics:
   - `conversation.user.replied` - When a user sends a message
   - `conversation.admin.assigned` - When a conversation is assigned to an inbox (required for Inbox Rules routing)

### 6. Find Inbox and Team IDs

To find inbox IDs for routing rules:

```bash
curl https://api.intercom.io/teams \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Accept: application/json"
```

Each team object has an `id` field you can use as `inbox_id` in routing rules.

## Deployment

### Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Development mode with auto-reload
docker-compose --profile dev up
```

### Railway / Render / Heroku (Platforms without filesystem)

For platforms where you can't mount config files, use the `CONFIG_YAML` environment variable:

```bash
# Set your configuration as a single environment variable
CONFIG_YAML='
studio_chat:
  api_key: ${STUDIO_CHAT_API_KEY}
  timeout_seconds: 120

intercom:
  access_token: ${INTERCOM_ACCESS_TOKEN}

logging:
  level: INFO
  format: json

assistants:
  - playbook_id: "your-playbook-id"
    admin_id: "your-admin-id"
    routing_rules:
      - type: inbox
        inbox_id: "your-inbox-id"
    handoff:
      actions:
        - type: transfer_to_inbox
          inbox_id: "human-inbox-id"
'
```

Then set your secrets as separate environment variables:
- `STUDIO_CHAT_API_KEY`
- `INTERCOM_ACCESS_TOKEN`

The YAML content supports `${VAR_NAME}` syntax for environment variable interpolation.

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: intercom-middleware
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: bridge
          image: studiochat/intercom-bridge-middleware:latest
          ports:
            - containerPort: 8080
          envFrom:
            - secretRef:
                name: intercom-middleware-secrets
          volumeMounts:
            - name: config
              mountPath: /app/config.yaml
              subPath: config.yaml
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (returns 200 if running) |
| `/ready` | GET | Readiness check (validates configuration) |
| `/webhooks/intercom` | POST | Intercom webhook receiver |

## Development

```bash
# Install dev dependencies
poetry install

# Run tests
poetry run pytest

# Run tests with coverage
poetry run pytest --cov=bridge

# Linting
poetry run ruff check .

# Type checking
poetry run mypy src/

# Format code
poetry run black .
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Intercom                                  │
│  (User sends message via WhatsApp, Messenger, Web, etc.)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Webhook (conversation.user.replied)
┌─────────────────────────────────────────────────────────────────┐
│              Intercom Studio Chat Middleware                         │
│                                                                  │
│  1. Parse webhook & extract message                             │
│  2. Find matching assistant (routing rules)                     │
│  3. Check rollout percentage                                    │
│  4. Send message to Studio Chat API                             │
│  5. Process response events (message, note, label, handoff)    │
│  6. Send responses back to Intercom                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ POST /playbooks/{id}/active/chat
┌─────────────────────────────────────────────────────────────────┐
│                      Studio Chat API                             │
│         (AI processes message, returns events)                  │
└─────────────────────────────────────────────────────────────────┘
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- [GitHub Issues](https://github.com/studiochat/intercom-studiochat-middleware/issues)
- [Documentation](https://github.com/studiochat/intercom-studiochat-middleware/wiki)
