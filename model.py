"""Модель данных «Инженерной схемы квартиры».

Слои, обозначения, палитра и хранилище (JSON). Никакого GUI — только данные.
"""
from __future__ import annotations

import copy
import json
import math
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Слои
# ---------------------------------------------------------------------------
ROOM_LAYER = "room"
ELECTRICITY = "electricity"
WATER = "water"
INTERNET = "internet"

ALL_LAYERS: list[str] = [ROOM_LAYER, ELECTRICITY, WATER, INTERNET]
COMMUNICATION_LAYERS: list[str] = [ELECTRICITY, WATER, INTERNET]

LAYER_LABELS: dict[str, str] = {
    ROOM_LAYER: "Помещение",
    ELECTRICITY: "Электричество",
    WATER: "Вода",
    INTERNET: "Интернет",
}
LABEL_TO_LAYER: dict[str, str] = {label: layer for layer, label in LAYER_LABELS.items()}

LAYER_COLORS: dict[str, str] = {
    ROOM_LAYER: "#94a3b8",
    ELECTRICITY: "#1685d1",
    WATER: "#0891b2",
    INTERNET: "#c026d3",
}

# ---------------------------------------------------------------------------
# Поверхности комнаты
# ---------------------------------------------------------------------------
WALLS: list[str] = ["north", "south", "east", "west", "floor", "ceiling"]

WALL_LABELS: dict[str, str] = {
    "north": "Северная стена",
    "south": "Южная стена",
    "east": "Восточная стена",
    "west": "Западная стена",
    "floor": "Пол",
    "ceiling": "Потолок",
}
LABEL_TO_WALL: dict[str, str] = {label: wall for wall, label in WALL_LABELS.items()}

# ---------------------------------------------------------------------------
# Типы объектов коммуникаций
# ---------------------------------------------------------------------------
KIND_LABELS: dict[str, str] = {
    "wire": "Провод (отрезок)",
    "branch": "Разветвление",
    "socket": "Розетка",
    "switch": "Выключатель",
    "lamp": "Светильник",
}

ELEMENT_DEFAULTS: dict[str, Any] = {
    "name": "Объект",
    "kind": "wire",
    "layer": ELECTRICITY,
    "wall": "north",
    "start": {"x": 0.0, "y": 0.0, "z": 0.0},
    "end": {"x": 0.0, "y": 0.0, "z": 0.0},
    "description": "",
    "install_date": "",
    "removal_date": "",
    "status": "Видимый",
    "routing": "Открытая",
    "voltage": 0.0,
    "diameter": 0.0,
    "material": "",
    "connections": [],
}


def new_id() -> str:
    return uuid.uuid4().hex


def clamp(value: float, lo: float, hi: float) -> float:
    """Ограничивает значение отрезком [lo, hi]."""
    return max(lo, min(hi, value))


def point3(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> dict[str, float]:
    """Точка в метрах относительно угла комнаты: x — ширина, y — глубина, z — высота."""
    return {"x": float(x), "y": float(y), "z": float(z)}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_element(raw: dict[str, Any]) -> dict[str, Any]:
    element = copy.deepcopy(ELEMENT_DEFAULTS)
    element.update(raw or {})
    element["id"] = str(element.get("id") or new_id())
    element["start"] = point3(*[element.get("start", {}).get(a, 0) if isinstance(element.get("start"), dict) else 0 for a in ("x", "y", "z")])
    element["end"] = point3(*[element.get("end", {}).get(a, 0) if isinstance(element.get("end"), dict) else 0 for a in ("x", "y", "z")])
    element["connections"] = [str(c) for c in element.get("connections", []) if c]
    return element


def normalize_room(raw: dict[str, Any], number: int = 1) -> dict[str, Any]:
    room = {
        "id": str(raw.get("id") or new_id()),
        "name": str(raw.get("name") or f"Комната {number}"),
        "width": _as_float(raw.get("width"), 4.0),
        "depth": _as_float(raw.get("depth"), 3.0),
        "height": _as_float(raw.get("height"), 2.7),
        "description": str(raw.get("description", "")),
        "elements": [normalize_element(e) for e in raw.get("elements", []) if isinstance(e, dict)],
        "wall_properties": dict(raw.get("wall_properties") or {}),
    }
    # Обратная совместимость со старым форматом: communications по относительным
    # координатам плана конвертируются в отрезки проводов слоя электричества.
    legacy = raw.get("communications") or {}
    if isinstance(legacy, dict) and legacy:
        migrated = set(raw.get("migrated_layers", []) or [])
        for layer_key, label in (("electricity", LAYER_LABELS[ELECTRICITY]), ("water", LAYER_LABELS[WATER])):
            if layer_key in migrated:
                continue
            for segment in legacy.get(label, []):
                pts = [_norm_point(p) for p in segment]
                pts = [p for p in pts if p is not None]
                if len(pts) >= 2:
                    room["elements"].append(normalize_element({
                        "name": "Провод",
                        "kind": "wire",
                        "layer": ELECTRICITY,
                        "wall": "north",
                        "start": pts[-2],
                        "end": pts[-1],
                    }))
            migrated.add(layer_key)
        room["communications"] = legacy
        room["migrated_layers"] = sorted(migrated)
    return room


def _norm_point(p: Any) -> dict[str, float] | None:
    if isinstance(p, dict):
        return point3(_as_float(p.get("x")), _as_float(p.get("y")), _as_float(p.get("z")))
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        # Относительная точка плана [u, v] -> точка на «полу» комнаты (масштаб 4×3 м).
        return point3(_as_float(p[0]) * 4.0, _as_float(p[1]) * 3.0, 0.0)
    return None


def normalize_apartment(raw: dict[str, Any], number: int = 1) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or new_id()),
        "name": str(raw.get("name") or f"Квартира {number}"),
        "description": str(raw.get("description", "")),
        "plan_path": raw.get("plan_path"),
        "rooms": [normalize_room(r, i + 1) for i, r in enumerate([r for r in raw.get("rooms", []) if isinstance(r, dict)])],
    }


class DataStore:
    """Хранилище квартир/комнат с автосохранением в JSON."""

    def __init__(self, path: str | Path = "apartment_data.json") -> None:
        self.path = Path(path)
        self.apartments: list[dict[str, Any]] = []
        self.load()

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        raw_list = data.get("apartments", data if isinstance(data, list) else [])
        self.apartments = [normalize_apartment(a, i + 1) for i, a in enumerate(raw_list if isinstance(raw_list, list) else [])]

    def save(self) -> None:
        payload = {"apartments": self.apartments}
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # не блокируем работу приложения при проблемах с диском

    # ------------------------------------------------------------------ поиск
    def get_apartment(self, apartment_id: str | None) -> dict[str, Any] | None:
        if not apartment_id:
            return None
        return next((a for a in self.apartments if a.get("id") == apartment_id), None)

    @staticmethod
    def get_room(apartment: dict[str, Any] | None, room_id: str | None) -> dict[str, Any] | None:
        if not apartment or not room_id:
            return None
        return next((r for r in apartment.get("rooms", []) if r.get("id") == room_id), None)

    # -------------------------------------------------------------- создание
    def create_apartment(self, name: str, description: str = "") -> dict[str, Any]:
        apartment = normalize_apartment({
            "name": name or f"Квартира {len(self.apartments) + 1}",
            "description": description,
            "rooms": [],
        })
        self.apartments.append(apartment)
        self.save()
        return apartment

    def delete_apartment(self, apartment_id: str) -> bool:
        before = len(self.apartments)
        self.apartments = [a for a in self.apartments if a.get("id") != apartment_id]
        changed = len(self.apartments) != before
        if changed:
            self.save()
        return changed

    def rename_apartment(self, apartment_id: str, name: str) -> None:
        apartment = self.get_apartment(apartment_id)
        if apartment:
            apartment["name"] = name
            self.save()

    def set_plan(self, apartment_id: str, plan_path: str | None) -> None:
        apartment = self.get_apartment(apartment_id)
        if apartment:
            apartment["plan_path"] = plan_path
            self.save()


def room_diagonal_scale(room: dict[str, Any]) -> float:
    w, d, h = (_as_float(room.get(k), 1.0) for k in ("width", "depth", "height"))
    return math.sqrt(w * w + d * d + h * h)
