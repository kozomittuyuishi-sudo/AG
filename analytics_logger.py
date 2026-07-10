"""
DWDM (Data Warehousing and Data Mining) logging foundation.
Append-only event history for future analytics. No ML, no dashboards —
just structured event capture and a few deterministic aggregate queries.
"""

import json
import os
from datetime import datetime, timezone

from storage_manager import append_event

WAREHOUSE_FILE = os.path.join("data", "warehouse", "events.jsonl")


def log_event(event_type: str, payload: dict) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload or {}
    }

    try:
        append_event("warehouse_events", event)
    except Exception:
        pass


def _read_events() -> list:
    if not os.path.exists(WAREHOUSE_FILE):
        return []

    events = []

    try:
        with open(WAREHOUSE_FILE, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []

    return events


def get_recent_events(limit: int = 20) -> list:
    events = _read_events()
    return events[-limit:]


def get_brain_usage_stats() -> dict:
    events = _read_events()
    stats = {"local": 0, "cloud": 0, "auto": 0, "temporary_cloud": 0}

    for event in events:
        event_type = event.get("event_type")

        if event_type == "brain_mode_changed":
            mode = event.get("payload", {}).get("mode")
            if mode in stats:
                stats[mode] += 1

        elif event_type == "temporary_brain_used":
            stats["temporary_cloud"] += 1

    return stats


def get_action_pattern_stats() -> dict:
    events = _read_events()
    stats: dict = {}

    for event in events:
        if event.get("event_type") == "action_pattern_detected":
            action_type = event.get("payload", {}).get("action_type", "unknown")
            stats[action_type] = stats.get(action_type, 0) + 1

    return stats


def get_frequent_topics(limit: int = 10) -> list:
    events = _read_events()
    counts: dict = {}

    for event in events:
        topic = event.get("payload", {}).get("topic")
        if topic:
            counts[topic] = counts.get(topic, 0) + 1

    return sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:limit]


def get_error_events(limit: int = 20) -> list:
    events = _read_events()
    errors = [event for event in events if event.get("event_type") == "error"]
    return errors[-limit:]