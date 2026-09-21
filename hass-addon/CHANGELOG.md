# Changelog

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