# Changelog

## 1.0.9

- Fix the activity entity id. MQTT entities set `has_entity_name`, so Home
  Assistant prefixes the device name ("Odysseus") to the entity name; our name
  "Odysseus activity" produced `sensor.odysseus_odysseus_activity`. The payload
  now carries only the entity-specific part ("Activity"), yielding
  `sensor.odysseus_activity` and `sensor.odysseus_activity_<owner>`. The
  unique_id changed once, so delete any leftover
  `sensor.odysseus_odysseus_activity` entity.

## 1.0.8

- Add **database connection** options: `db_type` (`sqlite`/`postgres`), a full
  `db_url` override, and `db_host`/`db_port`/`db_name`/`db_user`/`db_password`
  (credentials percent-encoded). `DATABASE_URL` is exported before schema init.
- Add **web search provider** options: `search_provider` dropdown plus
  `search_url` (SearXNG) and `search_api_key` (brave/tavily/serper/google_pse).
  The provider is written into the app settings on start; the key is passed via
  the provider's environment variable.

## 1.0.7

- Fix an invalid add-on manifest that made Home Assistant hide the add-on: the
  MQTT service must be declared as `mqtt:want`. Supervisor's service schema
  requires a rights suffix (`provide`/`want`/`need`); the bare `mqtt` entry
  failed validation for the whole config.
- Add a config-validation test mirroring the Supervisor rules (services,
  watchdog/webui URLs, map entries, options/schema).

## 1.0.6

- Add a **Model provider** dropdown + **Provider API key** field to the add-on
  options. On start the add-on seeds a ready-to-use model endpoint (correct base
  URL + encrypted key) for OpenAI, Anthropic, OpenRouter, Groq, DeepSeek,
  Google Gemini or Mistral.
- Publish live agent activity to Home Assistant via MQTT discovery:
  - `sensor.odysseus_activity` — global, anonymised (`idle` / `N working`,
    attributes carry model + stage only).
  - `sensor.odysseus_activity_<owner>` — per owner, state is the thread title.
  Optional: only active when an MQTT broker is available.

## 1.0.5

- Stop serving stale ingress assets. Static files advertise an ETag that does
  not change with the rewritten body, so a browser could keep an old JS bundle
  via a 304 even after a rebuild. Ingress responses now drop the conditional
  request headers and return `Cache-Control: no-store` without ETag/Last-Modified.

## 1.0.4

- Fix ingress API calls returning HTTP 404. The SPA builds absolute URLs from
  `window.location.origin` (e.g. `` `${API_BASE}/api/sessions` ``); those are now
  prefixed with the ingress path both in served JS and at runtime in the shim.

## 1.0.3

- Initial Home Assistant OS add-on.
- Sidebar panel via Supervisor ingress.
- Optional direct port access on `7000`.
- Home Assistant user authentication: ingress auto-login and optional
  HA username/password login on the direct port.