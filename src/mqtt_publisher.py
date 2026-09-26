"""Publish live agent activity to Home Assistant over MQTT.

Home Assistant cannot be handed new entities through its REST API; the standard
way for an add-on to create them is MQTT discovery. This module publishes:

* ``sensor.odysseus_activity`` — a global, anonymised view. State is the number
  of in-flight jobs ("idle" when none); attributes list only model + stage, so
  no thread titles or user text leak to whoever can see the dashboard.
* ``sensor.odysseus_activity_<owner>`` — one per active owner, whose state is the
  thread title. Restrict these per user with Home Assistant's entity visibility
  if you do not want every dashboard viewer to read them.

Everything is opt-in: without ``ODYSSEUS_MQTT_ENABLED=true`` and a broker the
publisher never starts. ``paho-mqtt`` is imported lazily so the core app runs
unchanged when it is not installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

from src.activity import anonymized_items, describe_item

logger = logging.getLogger(__name__)

DEVICE_IDENTIFIERS = ["odysseus_addon"]
DEFAULT_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_BASE_TOPIC = "odysseus"
DEFAULT_DEVICE_NAME = "Odysseus"
DEFAULT_INTERVAL = 5.0


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_flag(name: str) -> bool:
    return _env(name).lower() == "true"


def mqtt_enabled() -> bool:
    return _env_flag("ODYSSEUS_MQTT_ENABLED") and bool(_env("ODYSSEUS_MQTT_HOST"))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug or "unknown"


def _device(device_name: str) -> Dict[str, Any]:
    return {
        "identifiers": DEVICE_IDENTIFIERS,
        "name": device_name,
        "manufacturer": "Odysseus",
        "model": "Odysseus AI workspace",
    }


def global_discovery(discovery_prefix: str, base_topic: str, device_name: str) -> Dict[str, Any]:
    return {
        "topic": f"{discovery_prefix}/sensor/odysseus_activity/config",
        "payload": {
            # MQTT entities set has_entity_name=True, so Home Assistant prefixes
            # the DEVICE name ("Odysseus") to this entity name to build the
            # entity_id and friendly name. Keep it to the entity-specific part
            # ("Activity"), otherwise the id becomes a doubled
            # sensor.odysseus_odysseus_activity.
            "name": "Activity",
            "unique_id": "odysseus_activity_status",
            "object_id": "activity",
            "state_topic": f"{base_topic}/activity/state",
            "json_attributes_topic": f"{base_topic}/activity/attributes",
            "icon": "mdi:robot-happy",
            "device": _device(device_name),
        },
    }


def owner_discovery(
    discovery_prefix: str,
    base_topic: str,
    device_name: str,
    owner: str,
) -> Dict[str, Any]:
    slug = slugify(owner)
    return {
        "topic": f"{discovery_prefix}/sensor/odysseus_activity_{slug}/config",
        "payload": {
            # See global_discovery: "Activity <owner>" becomes
            # sensor.odysseus_activity_<slug> after the device prefix.
            "name": f"Activity {owner}",
            "unique_id": f"odysseus_activity_status_{slug}",
            "object_id": f"activity_{slug}",
            "state_topic": f"{base_topic}/activity/{slug}/state",
            "json_attributes_topic": f"{base_topic}/activity/{slug}/attributes",
            "icon": "mdi:robot-happy",
            "device": _device(device_name),
        },
    }


def global_state(base_topic: str, items: List[Dict[str, Any]]) -> List[tuple]:
    count = len(items)
    state = "idle" if count == 0 else f"{count} working"
    attributes = {
        "count": count,
        "items": anonymized_items(items),
        "summary": "idle" if count == 0 else "; ".join(
            sorted({f"{i.get('model') or 'unknown'} ({i.get('stage') or 'working'})" for i in items})
        ),
    }
    return [
        (f"{base_topic}/activity/state", state, True),
        (f"{base_topic}/activity/attributes", json.dumps(attributes), True),
    ]


def owner_state(base_topic: str, owner: str, items: List[Dict[str, Any]]) -> List[tuple]:
    slug = slugify(owner)
    active = [i for i in items if i.get("status") == "working"]
    if not active:
        state = "idle"
        attributes = {"count": 0, "items": []}
    else:
        state = describe_item(active[0])
        attributes = {
            "count": len(active),
            "items": [
                {
                    "title": i.get("title"),
                    "model": i.get("model"),
                    "stage": i.get("stage"),
                    "status": i.get("status"),
                }
                for i in active
            ],
        }
    return [
        (f"{base_topic}/activity/{slug}/state", state, True),
        (f"{base_topic}/activity/{slug}/attributes", json.dumps(attributes), True),
    ]


class MqttActivityPublisher:
    """Publishes discovery + state for the activity entities on an interval."""

    def __init__(
        self,
        snapshot_provider: Callable[[], List[Dict[str, Any]]],
        interval: Optional[float] = None,
    ) -> None:
        self._snapshot = snapshot_provider
        self.interval = float(interval or _env("ODYSSEUS_MQTT_INTERVAL", str(DEFAULT_INTERVAL)) or DEFAULT_INTERVAL)
        self.host = _env("ODYSSEUS_MQTT_HOST")
        self.port = int(_env("ODYSSEUS_MQTT_PORT", "1883") or "1883")
        self.username = _env("ODYSSEUS_MQTT_USERNAME")
        self.password = _env("ODYSSEUS_MQTT_PASSWORD")
        self.discovery_prefix = _env("ODYSSEUS_MQTT_DISCOVERY_PREFIX", DEFAULT_DISCOVERY_PREFIX)
        self.base_topic = _env("ODYSSEUS_MQTT_BASE_TOPIC", DEFAULT_BASE_TOPIC)
        self.device_name = _env("ODYSSEUS_MQTT_DEVICE_NAME", DEFAULT_DEVICE_NAME)
        self._client = None
        self._connected = False
        self._stopping = False
        self._known_owners: set[str] = set()

    # -- connection --------------------------------------------------------
    def _try_connect(self, mqtt_module) -> None:
        if self._client is None:
            try:
                self._client = mqtt_module.Client(
                    mqtt_module.CallbackAPIVersion.VERSION2,
                    client_id=f"odysseus_{slugify(self.device_name)}",
                )
            except (AttributeError, TypeError):
                # paho-mqtt 1.x has no CallbackAPIVersion.
                self._client = mqtt_module.Client(
                    client_id=f"odysseus_{slugify(self.device_name)}"
                )
            if self.username:
                self._client.username_pw_set(self.username, self.password or None)
            try:
                self._client.reconnect_delay_set(min_delay=1, max_delay=30)
            except Exception:
                pass
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.loop_start()
            self._connected = True
            logger.info("Activity publisher connected to MQTT %s:%s", self.host, self.port)
        except Exception as exc:
            logger.warning("MQTT connect failed (%s); retrying", exc)
            self._connected = False

    def _publish(self, topic: str, payload: str, retain: bool = True) -> None:
        if self._client is not None:
            self._client.publish(topic, payload, qos=0, retain=retain)

    def _publish_discovery(self) -> None:
        for message in (
            global_discovery(self.discovery_prefix, self.base_topic, self.device_name),
        ):
            self._publish(message["topic"], json.dumps(message["payload"]))

    # -- main loop ---------------------------------------------------------
    async def run(self) -> None:
        if not mqtt_enabled():
            return
        try:
            import paho.mqtt.client as mqtt_module
        except Exception:
            logger.warning("paho-mqtt is not installed; activity entity disabled")
            return

        while not self._stopping:
            if not self._connected:
                self._try_connect(mqtt_module)
            if self._connected:
                try:
                    self._publish_discovery()
                    items = list(self._snapshot() or [])
                    self._publish_items(items)
                except Exception:
                    logger.debug("Activity publish failed", exc_info=True)
            await asyncio.sleep(self.interval)

    def _publish_items(self, items: List[Dict[str, Any]]) -> None:
        for topic, payload, retain in global_state(self.base_topic, items):
            self._publish(topic, payload, retain)

        by_owner: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            owner = item.get("owner")
            if owner:
                by_owner.setdefault(owner, []).append(item)

        for owner, owner_items in by_owner.items():
            message = owner_discovery(
                self.discovery_prefix, self.base_topic, self.device_name, owner
            )
            self._publish(message["topic"], json.dumps(message["payload"]))
            for topic, payload, retain in owner_state(self.base_topic, owner, owner_items):
                self._publish(topic, payload, retain)

        # Reset owners that finished since the last tick so their entity goes
        # back to idle instead of showing stale "working".
        for owner in self._known_owners - set(by_owner):
            for topic, payload, retain in owner_state(self.base_topic, owner, []):
                self._publish(topic, payload, retain)
        self._known_owners = set(by_owner)

    def stop(self) -> None:
        self._stopping = True
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._connected = False