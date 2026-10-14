from __future__ import annotations

from dataclasses import dataclass

from engine.config_loader import Config

_COLLAPSED_ACTIVE_EVENT_NAME = "SCHEDULER_SELECT_ACTIVE"

_DATA_CLASS_EVENT_SUFFIX_ALIASES = {"CODEC2_M17": "VOICE"}

_IDLE_EVENT_NAME = "SCHEDULER_SELECT_IDLE"

class EventMappingError(KeyError):
    pass

@dataclass(frozen=True)
class EventMap:

    by_name: dict[str, str]

def build_event_map(cfg: Config) -> EventMap:
    return EventMap(by_name={event.name: event.id for event in cfg.events.values()})

def resolve(event_map: EventMap, name: str) -> str:
    try:
        return event_map.by_name[name]
    except KeyError:
        raise EventMappingError(
            f"event name not defined by this config: {name!r}"
        ) from None

def scheduler_select_event_names(
    event_map: EventMap, data_class: str | None
) -> list[str]:
    if data_class is None:
        candidates = [_IDLE_EVENT_NAME]
    else:
        candidates = [f"SCHEDULER_SELECT_{data_class}"]
        alias_suffix = _DATA_CLASS_EVENT_SUFFIX_ALIASES.get(data_class)
        if alias_suffix is not None:
            candidates.append(f"SCHEDULER_SELECT_{alias_suffix}")
        candidates.append(_COLLAPSED_ACTIVE_EVENT_NAME)

    return [name for name in candidates if name in event_map.by_name]
