# Odysseus

Self-hosted AI workspace for chat, agents, deep research, documents, email,
notes, tasks and calendar, packaged for Home Assistant OS.

## Installation

1. In Home Assistant open **Settings → Add-ons → Add-on Store**.
2. Open the three-dot menu (top right) and choose **Repositories**.
3. Paste this repository URL and click **Add**:

   ```
   https://github.com/gkmzfk6um/odysseus
   ```

   (This is the testing fork. Use your own fork's URL if you build a customized
   add-on.)
4. Close the dialog. **Odysseus** now appears in the store — select it and click
   **Install**.
5. Open the **Configuration** tab, set at least your LLM host or provider key,
   then click **Start**.
6. Open the sidebar entry **Odysseus**, or use the direct port (see below).

The first build clones and installs the Odysseus application, so installation
takes a few minutes. Later updates reuse the cached dependency layer.

## How it is exposed

| Way in | Address | Authentication |
| --- | --- | --- |
| Sidebar panel (Recommended) | Inside the Home Assistant UI | Handled by Home Assistant (ingress) |
| Direct port | `http://<home-assistant-host>:7000` | Odysseus login, optionally using Home Assistant users |

### Sidebar panel (ingress)

Ingress embeds the web UI in Home Assistant and lets the Supervisor authenticate
the Home Assistant user before the request ever reaches Odysseus. The add-on is
only reachable from the Supervisor's network address, so no separate login is
needed inside the panel.

When `ha_ingress_auth` is enabled (default):

- The Home Assistant user is mapped to an Odysseus account on first visit.
- Usernames in `ha_admin_users` become Odysseus administrators.
- With `ha_bootstrap_admin` (default), the first Home Assistant user to open the
  panel becomes administrator when no Odysseus account exists yet.
- Set `panel_admin` behavior by editing the add-on: the panel is shown to all
  Home Assistant users by default. Restrict it to administrators by setting
  `panel_admin: true` in the add-on's `config.yaml` before installing.

### Direct port

The web UI and API are also served on port `7000`. This is useful for API
clients, the mobile app, or when you want to bypass the Home Assistant UI. Set
the host port to `null` in the add-on **Network** settings to disable direct
access.

Direct access is protected by Odysseus authentication. With `ha_password_auth`
enabled (default) an existing Home Assistant username and password also works,
in addition to local Odysseus accounts. Home Assistant users are provisioned on
first successful login using the same admin rules as ingress.

## Configuration

```yaml
ha_ingress_auth: true       # Auto sign-in from Home Assistant ingress
ha_password_auth: true      # Allow HA username/password on the direct port
ha_admin_users: []          # HA usernames that become Odysseus admins
ha_bootstrap_admin: true    # First HA user becomes admin when none exists
auth_enabled: true          # Require login for direct access
admin_user: ""              # Optional initial local admin username
admin_password: ""          # Optional initial local admin password
llm_provider: none          # openai | anthropic | openrouter | groq | deepseek | google | mistral | none
llm_api_key: ""             # API key for the selected provider (stored encrypted)
llm_model: ""               # Optional model ID to pin (else pick from the list in the app)
db_type: sqlite             # sqlite | postgres
db_url: ""                  # Optional full connection string (overrides the fields below)
db_host: ""                 # PostgreSQL host
db_port: ""                 # PostgreSQL port (default 5432)
db_name: ""                 # PostgreSQL database (default odysseus)
db_user: ""                 # PostgreSQL user
db_password: ""             # PostgreSQL password
search_provider: none       # searxng | brave | tavily | serper | google_pse | duckduckgo | disabled | none
search_url: ""              # SearXNG base URL, e.g. http://searxng:8080
search_api_key: ""          # API key for brave/tavily/serper/google_pse
llm_host: localhost         # Default LLM server host
ollama_base_url: ""         # e.g. http://host.docker.internal:11434
allowed_origins: []         # Extra CORS origins
extra_env: []               # Free-form KEY=VALUE entries
```

### Model provider

Pick your provider in the **Model provider** dropdown and paste the key into
**Provider API key**. On start the add-on creates a shared model endpoint for
that provider (`OpenAI (add-on)`, `OpenRouter (add-on)`, …) with the correct
base URL and the key stored encrypted in `/data`. The model list is discovered
automatically; optionally pin one with **Default model**. The dropdown only
lists providers that need nothing but a key:

| Provider | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| Anthropic | `https://api.anthropic.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Mistral | `https://api.mistral.ai/v1` |

Local servers (Ollama, LM Studio) are configured with `ollama_base_url` or in
the app itself. The add-on option is authoritative: it rewrites the endpoint's
key on every start.

### Database

By default everything lives in SQLite on the `/data` volume — no configuration
needed. To use an external **PostgreSQL** server, set:

```yaml
db_type: postgres
db_host: 192.168.1.20
db_port: "5432"
db_name: odysseus
db_user: odysseus
db_password: "your password"
```

The user and password are percent-encoded, so special characters are safe. For
anything more exotic set `db_url` to a full SQLAlchemy string (e.g.
`postgresql+psycopg2://user:pass@host:5432/odysseus`); it overrides the fields.

Switching the database does **not** migrate existing data — point the add-on at
an empty database or import your SQLite data yourself. The add-on creates the
schema on first start.

### Web search

Pick the backend in **Search provider**:

| Provider | `search_provider` | Needs |
| --- | --- | --- |
| SearXNG (default) | `searxng` | `search_url` (or a bundled/host instance) |
| Brave Search API | `brave` | `search_api_key` |
| Tavily | `tavily` | `search_api_key` |
| Serper.dev | `serper` | `search_api_key` |
| Google Programmable Search | `google_pse` | `search_api_key` |
| DuckDuckGo (no key) | `duckduckgo` | – |
| Disabled | `disabled` | – |

Example (key-based provider):

```yaml
search_provider: brave
search_api_key: "BSA..."
```

Example (self-hosted SearXNG, reachable from the add-on network):

```yaml
search_provider: searxng
search_url: http://searxng:8080
```

The provider is written into the app settings on start (authoritative — a
change made in the app is reset on the next restart). API keys are passed as
environment variables, so a key set inside the app takes precedence over the
add-on option.

Anything Odysseus supports through environment variables can be passed with
`extra_env`, for example:

```yaml
extra_env:
  - TAVILY_API_KEY=...
  - ODYSSEUS_INPROCESS_TASKS=1
```

## Live activity in Home Assistant

When an **MQTT broker** (e.g. the Mosquitto add-on) is available, the add-on
publishes the current agent activity as Home Assistant entities via MQTT
discovery — no manual YAML needed. The add-on declares the `mqtt` service, so
broker credentials are picked up automatically.

| Entity | State | Notes |
| --- | --- | --- |
| `sensor.odysseus_activity` | `idle` or `N working` | Global and anonymised. Attributes list only model + stage, never thread titles. |
| `sensor.odysseus_activity_<owner>` | thread title, or `idle` | One per active owner. The state is that owner's thread title; restrict it per user with Home Assistant's entity visibility if desired. |

The entities appear under the **Odysseus** device. Home Assistant builds their
ids from the device + entity name, so they are exactly
`sensor.odysseus_activity` and `sensor.odysseus_activity_<owner>`. After
upgrading from a build before 1.0.9 you may see an old
`sensor.odysseus_odysseus_activity`; open it in Settings → Devices & Services →
Entities and delete it.

To show them on a dashboard, add a Markdown card (Settings → Dashboards → Edit →
Add card → Manual):

```yaml
type: markdown
title: Odysseus activity
content: >-
  {% set n = states('sensor.odysseus_activity') %}
  {% set items = state_attr('sensor.odysseus_activity', 'items') or [] %}
  {% if n in ['unknown', 'unavailable'] %}Entity not found yet.
  {% elif n == 'idle' or items | count == 0 %}Nothing running.
  {% else %}{{ n }}:
  {% for item in items %}
  - {{ item.model or 'unknown' }} — {{ item.stage or 'working' }}
  {% endfor %}{% endif %}
```

Or a plain Entities card for the raw states:

```yaml
type: entities
title: Odysseus activity
entities:
  - entity: sensor.odysseus_activity
  - entity: sensor.odysseus_activity_alice
```

Without an MQTT broker nothing is published and the add-on runs normally.

## Data and backups

All state is stored on the add-on's `/data` volume (Odysseus `data/`, SQLite
database, uploads, sessions, encryption key). Home Assistant backups include it
automatically. `/share` is mounted read-write at `/share` for exchanging files
with other add-ons.

## Local models

To reach an Ollama instance on the Home Assistant host, set:

```yaml
ollama_base_url: http://host.docker.internal:11434
```

The add-on runs inside the Supervisor network, so host services are reachable
via `host.docker.internal` or by IP address.

## Notes and limitations

- The add-on clones the Odysseus source at build time. To build your own fork
  or a pinned release, change the `ODYSSEUS_REPO` and `ODYSSEUS_REF` build
  arguments in `hass-addon/Dockerfile`.
- The Cookbook "install Real-ESRGAN" path is not pre-staged in this image (the
  upstream image builds patched wheels for it). Everything else is unchanged.
- Some UI features that build absolute links (deep links, certain downloads)
  may behave differently inside the ingress iframe. Use the direct port if you
  hit one.
- Cookbook model downloads and some agent features are disk- and memory-heavy;
  make sure the Home Assistant host has enough resources.