"""Tests for the live agent-activity aggregation, redaction and MQTT payloads."""

from src import activity as act
from src import mqtt_publisher as mqtt


def _session_info(mapping):
    def _info(session_id):
        return mapping.get(session_id, (None, None, None))

    return _info


def _sample_items():
    return act.collect_activity(
        chat_streams={
            "s1": {"status": "streaming", "mode": "agent"},
            "s2": {"status": "streaming", "mode": "chat"},
            "s3": {"status": "idle"},  # ignored
        },
        research_tasks={
            "s4": {"status": "running", "owner": "bob", "query": "secret topic"},
            "s5": {"status": "done"},  # ignored
        },
        bg_jobs={
            "j1": {"status": "running", "session_id": "s2", "command": "rm -rf /tmp/x"},
            "j2": {"status": "done"},  # ignored
        },
        session_info=_session_info({
            "s1": ("alice", "Alice planning", "gpt-4o"),
            "s2": ("bob", "Bob chat", "llama3"),
            "s4": ("bob", "Bob research", "llama3"),
        }),
        now=1000.0,
    )


def test_collect_activity_stages_and_fields():
    items = {i["session_id"]: i for i in _sample_items() if i["session_id"]}
    assert items["s1"]["stage"] == act.STAGE_AGENT
    assert items["s1"]["owner"] == "alice"
    assert items["s1"]["title"] == "Alice planning"
    assert items["s1"]["model"] == "gpt-4o"
    # s2 has both a chat stream and a bg job -> two entries
    s2 = [i for i in _sample_items() if i["session_id"] == "s2"]
    assert {i["stage"] for i in s2} == {act.STAGE_CHAT, act.STAGE_BACKGROUND}
    research = [i for i in _sample_items() if i["stage"] == act.STAGE_RESEARCH]
    assert research and research[0]["owner"] == "bob"
    assert all(i["status"] == "working" for i in _sample_items())


def test_redaction_hides_other_users_content():
    items = _sample_items()
    alice_view = act.redact_items(items, "alice")
    mine = [i for i in alice_view if i["owner"] == "alice"]
    others = [i for i in alice_view if i["owner"] == "bob"]
    assert all(i["title"] for i in mine)
    assert all(i["title"] is None for i in others)
    assert all(i["query"] is None for i in others)
    assert all(i["session_id"] is None for i in others)
    # model + stage stay visible for others
    assert all(i["model"] for i in others)
    assert all(i["stage"] for i in others)


def test_admin_and_auth_disabled_see_everything():
    items = _sample_items()
    admin_view = act.redact_items(items, "someone", is_admin=True)
    assert all(i["title"] for i in admin_view if i["owner"])
    open_view = act.redact_items(items, None)
    assert all(i["title"] for i in open_view if i["owner"])


def test_snapshot_counts_only_working():
    snap = act.snapshot(_sample_items(), "alice")
    assert snap["count"] == len(_sample_items())
    assert snap["working"] == snap["count"]


def test_describe_and_anonymize():
    owned = {"title": "My thread", "model": "gpt-4o", "stage": "agent", "status": "working"}
    other = {"title": None, "model": "gpt-4o", "stage": "agent", "status": "working"}
    assert act.describe_item(owned) == "My thread — gpt-4o (agent)"
    assert act.describe_item(other) == "gpt-4o (agent)"
    assert act.anonymized_items([owned]) == [
        {"model": "gpt-4o", "stage": "agent", "status": "working"}
    ]


# ---------------------------------------------------------------------------
# MQTT payload builders
# ---------------------------------------------------------------------------

def test_slugify():
    assert mqtt.slugify("Alice Smith") == "alice_smith"
    assert mqtt.slugify("") == "unknown"
    assert mqtt.slugify("a--b__C") == "a_b_c"


def test_discovery_uses_entity_specific_name_to_avoid_doubled_id():
    # has_entity_name=True: HA prefixes the device name, so the payload name
    # must be only the entity part or the id becomes odysseus_odysseus_activity.
    g = mqtt.global_discovery("homeassistant", "odysseus", "Odysseus")
    assert g["topic"] == "homeassistant/sensor/odysseus_activity/config"
    assert g["payload"]["name"] == "Activity"
    assert g["payload"]["unique_id"] == "odysseus_activity_status"
    assert g["payload"]["object_id"] == "activity"
    assert g["payload"]["device"]["name"] == "Odysseus"
    o = mqtt.owner_discovery("homeassistant", "odysseus", "Odysseus", "Alice Smith")
    assert o["topic"] == "homeassistant/sensor/odysseus_activity_alice_smith/config"
    assert o["payload"]["name"] == "Activity Alice Smith"
    assert o["payload"]["unique_id"] == "odysseus_activity_status_alice_smith"
    assert o["payload"]["state_topic"] == "odysseus/activity/alice_smith/state"


def test_global_state_is_anonymized():
    items = [
        {"owner": "alice", "title": "Secret thread", "model": "gpt-4o", "stage": "agent", "status": "working"},
    ]
    messages = dict((t, p) for t, p, _ in mqtt.global_state("odysseus", items))
    assert messages["odysseus/activity/state"] == "1 working"
    import json
    attrs = json.loads(messages["odysseus/activity/attributes"])
    assert attrs["count"] == 1
    assert attrs["items"] == [{"model": "gpt-4o", "stage": "agent", "status": "working"}]
    assert "Secret thread" not in json.dumps(attrs)


def test_global_state_idle():
    messages = dict((t, p) for t, p, _ in mqtt.global_state("odysseus", []))
    assert messages["odysseus/activity/state"] == "idle"


def test_owner_state_shows_title():
    items = [
        {"owner": "alice", "title": "Alice planning", "model": "gpt-4o", "stage": "agent", "status": "working"},
    ]
    messages = dict((t, p) for t, p, _ in mqtt.owner_state("odysseus", "alice", items))
    assert messages["odysseus/activity/alice/state"] == "Alice planning — gpt-4o (agent)"
    messages = dict((t, p) for t, p, _ in mqtt.owner_state("odysseus", "alice", []))
    assert messages["odysseus/activity/alice/state"] == "idle"