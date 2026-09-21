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
llm_host: localhost         # Default LLM server host
ollama_base_url: ""         # e.g. http://host.docker.internal:11434
openai_api_key: ""          # OpenAI / compatible provider key
allowed_origins: []         # Extra CORS origins
extra_env: []               # Free-form KEY=VALUE entries
```

Anything Odysseus supports through environment variables can be passed with
`extra_env`, for example:

```yaml
extra_env:
  - TAVILY_API_KEY=...
  - ODYSSEUS_INPROCESS_TASKS=1
```

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