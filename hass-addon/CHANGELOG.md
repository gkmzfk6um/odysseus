# Changelog

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