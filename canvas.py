"""Холсты приложения: 2D-план квартиры и «развёртка» комнаты с объектами.

Реализовано на собственном QWidget + QPainter (PyQt6); сторонние библиотеки
отрисовки не используются.
"""
from __future__ import annotations

import copy
import json
import math
from typing import Any

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget

from model import (
    COMMUNICATION_LAYERS,
    ELECTRICITY,
    INTERNET,
    LAYER_COLORS,
    LAYER_LABELS,
    ROOM_LAYER,
    WALL_LABELS,
    WATER,
    clamp,
    new_id,
    normalize_element,
    point3,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции проекций
# ---------------------------------------------------------------------------
def _project_unfolded(w: float, d: float, h: float, wall: str, x: float, y: float, z: float) -> tuple[float, float]:
    """Точка комнаты (x — ширина, y — глубина, z — высота) в координатах развертки (у.е. метры)."""
    if wall == "north":
        return x, h - z
    if wall == "south":
        return w - x, h - z
    if wall == "west":
        return d - y, h - z
    if wall == "east":
        return y, h - z
    if wall == "floor":
        return x, d - y
    return x, d - y  # ceiling


def _unfolded_wall_rect(w: float, d: float, h: float, wall: str) -> tuple[float, float, float, float]:
    """Прямоугольник (bx, by, bw, bh) поверхности стены на развертке."""
    if wall in ("north", "south"):
        return 0.0, 0.0, w, h
    if wall in ("east", "west"):
        return w, 0.0, d, h
    return w + d, 0.0, w, max(d, h)


def _wall_local_from_unfolded(w: float, d: float, h: float, wall: str, px: float, py: float) -> dict[str, float]:
    """Обратная проекция: точка развертки -> локальные метрические координаты на стене."""
    if wall == "north":
        return point3(clamp(px, 0.0, w), 0.0, clamp(h - py, 0.0, h))
    if wall == "south":
        return point3(clamp(w - px, 0.0, w), d, clamp(h - py, 0.0, h))
    if wall == "west":
        return point3(0.0, clamp(d - py, 0.0, d), clamp(h - px, 0.0, h))
    if wall == "east":
        return point3(w, clamp(py, 0.0, d), clamp(h - px, 0.0, h))
    if wall == "floor":
        return point3(clamp(px, 0.0, w), clamp(d - py, 0.0, d), 0.0)
    return point3(clamp(px, 0.0, w), clamp(d - py, 0.0, d), h)


def snap_value(value: float, step_m: float) -> float:
    return round(value / step_m) * step_m


class _BaseCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)

    def _scaled_plan(self, world_w: float, world_h: float, margin: int = 28) -> tuple[float, float, float, float, QPixmap | None]:
        """Возвращает (scale, ox, oy, rotation_deg, pixmap) для отображения мира в виджете."""
        pw, ph = max(1, self.width() - 2 * margin), max(1, self.height() - 2 * margin)
        ww, wh = max(0.001, world_w), max(0.001, world_h)
        rot = getattr(self, "_rotation", 0) % 180
        if rot:
            ww, wh = wh, ww
        scale = min(pw / ww, ph / wh)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        return scale, cx - (ww * scale) / 2.0, cy - (wh * scale) / 2.0, rot, None


# ---------------------------------------------------------------------------
# 2D-план квартиры
# ---------------------------------------------------------------------------
class ApartmentPlanCanvas(_BaseCanvas):
    roomActivated = pyqtSignal(str)

    GRID_COLORS = ["#dfe7f0", "#cfd9e6"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.apartment: dict[str, Any] | None = None
        self.current_room_id: str | None = None
        self._plan_pixmap: QPixmap | None = None
        self._plan_path_used: str | None = None
        self._room_rects: dict[str, tuple[float, float, float, float]] = {}
        self.setMinimumSize(420, 300)

    def set_apartment(self, apartment: dict[str, Any] | None, current_room_id: str | None = None) -> None:
        self.apartment = apartment
        self.current_room_id = current_room_id
        plan_path = (apartment or {}).get("plan_path")
        if plan_path != self._plan_path_used:
            self._plan_path_used = plan_path
            pixmap = QPixmap(plan_path) if plan_path else QPixmap()
            self._plan_pixmap = pixmap if not pixmap.isNull() else None
        self.update()

    # ------------------------------------------------------------- геометрия
    def _layout_rooms(self) -> list[dict[str, Any]]:
        rooms = (self.apartment or {}).get("rooms", [])
        rects: dict[str, tuple[float, float, float, float]] = {}
        gap = 0.5
        # Простая упаковка по строкам: максимальная высота строки, перенос при 12 м.
        row_y, row_h, cursor_x = 0.0, 0.0, 0.0
        for room in rooms:
            rw = clamp(float(room.get("width", 4)), 0.5, 12.0)
            rd = clamp(float(room.get("depth", 3)), 0.5, 12.0)
            if cursor_x + rw > 12.5 and cursor_x > 0:
                cursor_x = 0.0
                row_y += row_h + gap
                row_h = 0.0
            rects[str(room.get("id"))] = (cursor_x, row_y, rw, rd)
            cursor_x += rw + gap
            row_h = max(row_h, rd)
        self._room_rects = rects
        return rooms

    def _world_bounds(self) -> tuple[float, float]:
        if not self._room_rects:
            return 10.0, 7.0
        max_x = max(rx + rw for rx, ry, rw, rh in self._room_rects.values())
        max_y = max(ry + rh for rx, ry, rw, rh in self._room_rects.values())
        return max(6.0, max_x + 1.0), max(4.0, max_y + 1.0)

    # ------------------------------------------------------------ отрисовка
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#eef2f6"))
        rooms = self._layout_rooms()
        world_w, world_h = self._world_bounds()
        margin = 30
        scale = min((self.width() - 2 * margin) / world_w, (self.height() - 2 * margin) / world_h)
        off_x = (self.width() - world_w * scale) / 2.0
        off_y = (self.height() - world_h * scale) / 2.0

        def to_view(x: float, y: float) -> tuple[float, float]:
            return off_x + x * scale, off_y + y * scale

        # фоновая сетка 0.5 м
        pen = QPen(QColor("#dbe4ee"))
        pen.setWidth(1)
        painter.setPen(pen)
        gx = 0.0
        while gx <= world_w:
            x0, y0 = to_view(gx, 0.0)
            x1, y1 = to_view(gx, world_h)
            painter.drawLine(QPoint(int(x0), int(y0)), QPoint(int(x1), int(y1)))
            gx += 0.5
        gy = 0.0
        while gy <= world_h:
            x0, y0 = to_view(0.0, gy)
            x1, y1 = to_view(world_w, gy)
            painter.drawLine(QPoint(int(x0), int(y0)), QPoint(int(x1), int(y1)))
            gy += 0.5

        # план из изображения — полупрозрачный подложкой
        if self._plan_pixmap is not None:
            painter.setOpacity(0.35)
            painter.drawPixmap(int(off_x), int(off_y), int(world_w * scale), int(world_h * scale), self._plan_pixmap)
            painter.setOpacity(1.0)

        if not rooms:
            painter.setPen(QColor("#64748b"))
            font = QFont("Segoe UI", 11)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "В квартире пока нет комнат.\nДобавьте комнату или откройте менеджер квартир.")
            return

        for room in rooms:
            rid = str(room.get("id"))
            rx, ry, rw, rh = self._room_rects.get(rid, (0, 0, 4, 3))
            x, y = to_view(rx, ry)
            rect_w, rect_h = rw * scale, rh * scale
            active = rid == str(self.current_room_id or "")
            fill = QColor("#dbeafe" if active else "#ffffff")
            border = QColor("#2563eb" if active else "#7c8da3")
            painter.setBrush(QBrush(fill))
            painter.setPen(QPen(border, 3 if active else 2))
            painter.drawRoundedRect(int(x), int(y), int(rect_w), int(rect_h), 6, 6)

            label_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
            painter.setFont(label_font)
            painter.setPen(QColor("#172334"))
            text_rect = QRect(int(x + 6), int(y + 4), int(max(1, rect_w - 12)), 24)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             str(room.get("name", "Комната")))
            dims_font = QFont("Segoe UI", 8)
            painter.setFont(dims_font)
            painter.setPen(QColor("#64748b"))
            dims = f"{float(room.get('width', 0)):g} × {float(room.get('depth', 0)):g} м"
            painter.drawText(QRect(int(x + 6), int(y + 24), int(max(1, rect_w - 12)), 18),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, dims)

            # объекты видимых слоёв комнаты (проекция на пол)
            visible = getattr(self, "_visible_layers_override", None)
            for element in room.get("elements", []):
                layer = element.get("layer")
                if layer not in COMMUNICATION_LAYERS:
                    continue
                if visible is not None and layer not in visible:
                    continue
                color = QColor(LAYER_COLORS.get(layer, "#334155"))
                color.setAlpha(230)
                e_pen = QPen(color, 2.4)
                painter.setPen(e_pen)
                s, e = element.get("start", {}), element.get("end", {})
                sx, sy = to_view(rx + float(s.get("x", 0)), ry + float(s.get("y", 0)))
                ex, ey = to_view(rx + float(e.get("x", 0)), ry + float(e.get("y", 0)))
                if element.get("kind") == "wire":
                    painter.drawLine(int(sx), int(sy), int(ex), int(ey))
                else:
                    painter.setBrush(QBrush(color))
                    painter.drawEllipse(QPoint(int(sx), int(sy)), 4, 4)

        hint_font = QFont("Segoe UI", 9)
        painter.setFont(hint_font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                         "Двойной щелчок по комнате — открыть её в окне 3D")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        rooms = (self.apartment or {}).get("rooms", [])
        world_w, world_h = self._world_bounds()
        margin = 30
        scale = min((self.width() - 2 * margin) / world_w, (self.height() - 2 * margin) / world_h)
        off_x = (self.width() - world_w * scale) / 2.0
        off_y = (self.height() - world_h * scale) / 2.0
        wx = (pos.x() - off_x) / scale
        wy = (pos.y() - off_y) / scale
        for room in rooms:
            rx, ry, rw, rh = self._room_rects.get(str(room.get("id")), (0, 0, 0, 0))
            if rx <= wx <= rx + rw and ry <= wy <= ry + rh:
                self.roomActivated.emit(str(room.get("id")))
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # одинарный клик тоже открывает комнату — удобнее на тачпаде
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            rooms = (self.apartment or {}).get("rooms", [])
            world_w, world_h = self._world_bounds()
            margin = 30
            scale = min((self.width() - 2 * margin) / world_w, (self.height() - 2 * margin) / world_h)
            off_x = (self.width() - world_w * scale) / 2.0
            off_y = (self.height() - world_h * scale) / 2.0
            wx = (pos.x() - off_x) / scale
            wy = (pos.y() - off_y) / scale
            for room in rooms:
                rx, ry, rw, rh = self._room_rects.get(str(room.get("id")), (0, 0, 0, 0))
                if rx <= wx <= rx + rw and ry <= wy <= ry + rh:
                    self.roomActivated.emit(str(room.get("id")))
                    return
        super().mousePressEvent(event)




# ---------------------------------------------------------------------------
# Развертка комнаты
# ---------------------------------------------------------------------------
class RoomCanvas(_BaseCanvas):
    selectionChanged = pyqtSignal(str)
    wallSelected = pyqtSignal(str)
    elementCreated = pyqtSignal(str)
    dataChanged = pyqtSignal()
    roomActivated = pyqtSignal()          # переход к следующей комнате («дверь»)
    cameraChanged = pyqtSignal(str)
    message = pyqtSignal(str)
    rightClickExit = pyqtSignal()

    CAMERA_UNFOLDED = "Развёртка"
    CAMERAS = [CAMERA_UNFOLDED, "Север", "Юг", "Запад", "Восток", "Пол", "Потолок"]
    CAMERA_LABELS = list(CAMERAS)
    _CAMERA_WALL = {"Север": "north", "Юг": "south", "Запад": "west", "Восток": "east",
                    "Пол": "floor", "Потолок": "ceiling"}

    KIND_DEFAULT_NAMES = {"wire": "Провод", "branch": "Разветвление", "socket": "Розетка",
                          "switch": "Выключатель", "lamp": "Светильник"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.room: dict[str, Any] | None = None
        self.edit_mode = False
        self.active_layer: str | None = None
        self.tool: str | None = None
        self.visible_layers: set[str] = set(COMMUNICATION_LAYERS)
        self.room_layer_visible = True
        self.show_grid = False
        self.snap = False
        self.grid_step_cm = 10
        self.camera = self.CAMERA_UNFOLDED
        self.selected_id: str | None = None
        self._pending_wire_point: dict[str, float] | None = None
        self._pending_wire_wall: str | None = None
        self._drag_id: str | None = None
        self._drag_last: tuple[float, float] | None = None
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._surface_rects: dict[str, tuple[float, float, float, float]] = {}
        self.setMinimumSize(420, 300)

    # ------------------------------------------------------------------ API
    def set_room(self, room: dict[str, Any] | None) -> None:
        self.room = room
        self.selected_id = None
        self._pending_wire_point = None
        self._undo.clear()
        self._redo.clear()
        self.update()

    def set_mode(self, edit_mode: bool, active_layer: str | None) -> None:
        self.edit_mode = edit_mode
        self.active_layer = active_layer if edit_mode else None
        if not edit_mode:
            self.tool = None
            self._pending_wire_point = None
        self.update()

    def set_active_layer(self, active_layer: str | None) -> None:
        self.active_layer = active_layer
        if not active_layer:
            self.tool = None
            self._pending_wire_point = None
        self.update()

    def set_tool(self, tool: str | None) -> None:
        self.tool = tool
        self._pending_wire_point = None
        if tool and tool != "select":
            self.message.emit(f"Инструмент «{self.KIND_DEFAULT_NAMES.get(tool, tool)}»: кликните на поверхности, чтобы разместить объект.")
        self.update()

    def set_visible_layers(self, layers: set[str], room_layer_visible: bool) -> None:
        self.visible_layers = set(layers)
        self.room_layer_visible = room_layer_visible
        self.update()

    def set_grid_options(self, show_grid: bool, snap: bool, step_cm: int) -> None:
        self.show_grid = show_grid
        self.snap = snap
        self.grid_step_cm = max(1, step_cm)
        self.update()

    def set_camera(self, label: str) -> None:
        if label in self.CAMERAS and label != self.camera:
            self.camera = label
            self.update()

    def select_element(self, element_id: str | None) -> None:
        self.selected_id = element_id
        self.update()

    def delete_element(self, element_id: str) -> None:
        if not self.room:
            return
        self.record_undo()
        elements = self.room.get("elements", [])
        self.room["elements"] = [e for e in elements if e.get("id") != element_id]
        for e in self.room["elements"]:
            if element_id in e.get("connections", []):
                e["connections"] = [c for c in e["connections"] if c != element_id]
        if self.selected_id == element_id:
            self.selected_id = None
        self.dataChanged.emit()
        self.update()

    # ------------------------------------------------------------- undo/redo
    def record_undo(self) -> None:
        if self.room:
            self._undo.append(json_dumps(copy.deepcopy(self.room.get("elements", []))))
            self._redo.clear()
            if len(self._undo) > 50:
                self._undo.pop(0)

    def _restore(self, blob: str) -> None:
        if self.room:
            self.room["elements"] = [normalize_element(e) for e in json_loads(blob)]
            ids = {e.get("id") for e in self.room["elements"]}
            if self.selected_id not in ids:
                self.selected_id = None
            self.dataChanged.emit()
            self.update()

    def undo(self) -> bool:
        if not self._undo or not self.room:
            return False
        self._redo.append(json_dumps(copy.deepcopy(self.room.get("elements", []))))
        self._restore(self._undo.pop())
        self.message.emit("Отменено действие (Ctrl+Z).")
        return True

    def redo(self) -> bool:
        if not self._redo or not self.room:
            return False
        self._undo.append(json_dumps(copy.deepcopy(self.room.get("elements", []))))
        self._restore(self._redo.pop())
        self.message.emit("Действие повторено (Ctrl+Y).")
        return True

    # -------------------------------------------------------------- геометрия
    def _dims(self) -> tuple[float, float, float]:
        room = self.room or {}
        w = clamp(float(room.get("width", 4)), 0.5, 100.0)
        d = clamp(float(room.get("depth", 3)), 0.5, 100.0)
        h = clamp(float(room.get("height", 2.7)), 0.5, 100.0)
        return w, d, h

    def _view_transform(self) -> tuple[float, float, float]:
        """Возвращает (scale, off_x, off_y) для текущего режима камеры."""
        w, d, h = self._dims()
        margin = 34
        if self.camera == self.CAMERA_UNFOLDED:
            north_w, north_h = w, h
            side_w = d
            bottom_h = max(d, h)
            total_w = north_w + 2 * side_w + 0.6  # север|запад|(пол/потолок)|восток|юг — упрощённо
            total_h = max(north_h, bottom_h)
            # раскладка: верхний ряд — запад, север, восток; нижний — пол и потолок
            total_w = d + w + d
            total_h = h + max(d, h) + 0.4
            pw, ph = max(1, self.width() - 2 * margin), max(1, self.height() - 2 * margin)
            scale = min(pw / total_w, ph / total_h)
            return scale, (self.width() - total_w * scale) / 2.0, (self.height() - total_h * scale) / 2.0
        wall = self._CAMERA_WALL.get(self.camera, "north")
        ww, wh = _surface_world_size(w, d, h, wall)
        pw, ph = max(1, self.width() - 2 * margin), max(1, self.height() - 2 * margin)
        scale = min(pw / ww, ph / wh)
        return scale, (self.width() - ww * scale) / 2.0, (self.height() - wh * scale) / 2.0

    def _wall_screen_rect(self, wall: str) -> tuple[float, float, float, float]:
        """Прямоугольник поверхности на экране (x, y, w, h) в пикселях."""
        w, d, h = self._dims()
        scale, off_x, off_y = self._view_transform()
        if self.camera == self.CAMERA_UNFOLDED:
            bx, by, bw, bh = _unfolded_wall_rect(w, d, h, wall)
            base_y = 0.0 if wall in ("north", "south", "east", "west") else h + 0.4
            if wall == "west":
                return off_x, off_y + base_y * scale, bw * scale, bh * scale
            if wall == "north":
                return off_x + d * scale, off_y + base_y * scale, bw * scale, bh * scale
            if wall == "east":
                return off_x + (d + w) * scale, off_y + base_y * scale, bw * scale, bh * scale
            # floor / ceiling — нижний ряд
            fx, fy, fw, fh = _unfolded_wall_rect(w, d, h, wall)
            if wall == "ceiling":
                return off_x + (d + w) * scale, off_y + base_y * scale, fw * scale, fh * scale
            return off_x, off_y + base_y * scale, fw * scale, fh * scale
        ww, wh = _surface_world_size(w, d, h, wall)
        return off_x, off_y, ww * scale, wh * scale

    def _to_surface_point(self, wall: str, screen_pos) -> dict[str, float]:
        """Экранная точка -> локальные метрические координаты на выбранной поверхности."""
        w, d, h = self._dims()
        rx, ry, rw, rh = self._wall_screen_rect(wall)
        ww, wh = _surface_world_size(w, d, h, wall)
        if rw <= 0 or rh <= 0:
            return point3()
        px = clamp((screen_pos.x() - rx) / rw, 0.0, 1.0) * ww
        py = clamp((screen_pos.y() - ry) / rh, 0.0, 1.0) * wh
        if self.snap:
            step = self.grid_step_cm / 100.0
            px, py = snap_value(px, step), snap_value(py, step)
        return _local_from_surface(w, d, h, wall, px, py)

    # ------------------------------------------------------------- события
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f9fc"))
        if not self.room:
            painter.setPen(QColor("#64748b"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Комната не выбрана.")
            return
        w, d, h = self._dims()
        self._surface_rects = {}
        if self.camera == self.CAMERA_UNFOLDED:
            walls = ["west", "north", "east", "floor", "ceiling", "south"]
        else:
            walls = [self._CAMERA_WALL.get(self.camera, "north")]
        for wall in walls:
            self._draw_surface(painter, wall, w, d, h)
        self._draw_elements(painter, walls, w, d, h)
        if self.edit_mode and self.tool == "wire" and self._pending_wire_point and self._pending_wire_wall:
            self._draw_pending_wire(painter, walls, w, d, h)
        if self.room_layer_visible:
            self._draw_door_hint(painter)

    def _draw_surface(self, painter: QPainter, wall: str, w: float, d: float, h: float) -> None:
        rx, ry, rw, rh = self._wall_screen_rect(wall)
        self._surface_rects[wall] = (rx, ry, rw, rh)
        highlight = self.edit_mode and self.active_layer and wall == _wall_of_selection(self.room, self.selected_id)
        fill = QColor("#ffffff" if not highlight else "#eef6ff")
        if wall in ("floor", "ceiling"):
            fill = QColor("#f1f5f9" if not highlight else "#eaf4ff")
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(QColor("#94a3b8"), 1.5))
        painter.drawRect(int(rx), int(ry), int(rw), int(rh))
        # сетка
        if self.show_grid:
            step = self.grid_step_cm / 100.0
            ww, wh = _surface_world_size(w, d, h, wall)
            painter.setPen(QPen(QColor("#e2e8f0"), 1))
            gx = step
            while gx < ww:
                x = rx + gx / ww * rw
                painter.drawLine(int(x), int(ry), int(x), int(ry + rh))
                gx += step
            gy = step
            while gy < wh:
                y = ry + gy / wh * rh
                painter.drawLine(int(rx), int(y), int(rx + rw), int(y))
                gy += step
        label_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        painter.setFont(label_font)
        painter.setPen(QColor("#475569"))
        painter.drawText(QRect(int(rx) + 6, int(ry) + 4, int(max(0, rw - 12)), 18),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         WALL_LABELS.get(wall, wall))

    def _element_visible(self, element: dict[str, Any]) -> bool:
        layer = element.get("layer")
        if layer == ROOM_LAYER:
            return self.room_layer_visible
        if layer not in self.visible_layers:
            return False
        if element.get("status") == "Скрытый" and element.get("routing") == "Скрытая":
            return False
        return True

    def _draw_elements(self, painter: QPainter, walls: list[str], w: float, d: float, h: float) -> None:
        if not self.room:
            return
        for element in self.room.get("elements", []):
            if not self._element_visible(element):
                continue
            wall = element.get("wall", "north")
            if wall not in walls:
                continue
            layer = element.get("layer", ELECTRICITY)
            base_color = QColor(LAYER_COLORS.get(layer, "#334155"))
            selected = element.get("id") == self.selected_id
            hidden_routing = element.get("routing") == "Скрытая"
            pen = QPen(base_color, 3.2 if selected else 2.4)
            if hidden_routing:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            start = self._project_to_surface(w, d, h, wall, element.get("start", {}))
            end = self._project_to_surface(w, d, h, wall, element.get("end", {}))
            kind = element.get("kind", "wire")
            if kind == "wire":
                painter.drawLine(start, end)
                painter.setBrush(QBrush(base_color))
                painter.drawEllipse(start, 3, 3)
                painter.drawEllipse(end, 3, 3)
            else:
                painter.setBrush(QBrush(QColor("#ffffff")))
                painter.drawEllipse(start, 9, 9)
                painter.setPen(QPen(base_color, 2))
                symbol = {"branch": "●", "socket": "⊙", "switch": "S", "lamp": "✳"}.get(kind, "?")
                if kind == "branch":
                    painter.setBrush(QBrush(base_color))
                    painter.drawEllipse(start, 6, 6)
                    symbol = ""
                if symbol:
                    painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                    painter.drawText(QRect(start.x() - 9, start.y() - 9, 18, 18),
                                     Qt.AlignmentFlag.AlignCenter, symbol)
            if selected:
                glow = QColor(base_color)
                glow.setAlpha(70)
                painter.setPen(QPen(glow, 9))
                if kind == "wire":
                    painter.drawLine(start, end)
                else:
                    painter.drawEllipse(start, 12, 12)
            name_color = QColor("#172334")
            painter.setPen(name_color)
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(start.x() + 12, start.y() - 8, str(element.get("name", "")))

    def _project_to_surface(self, w: float, d: float, h: float, wall: str, p: dict[str, float]) -> QPoint:
        rx, ry, rw, rh = self._wall_screen_rect(wall)
        ww, wh = _surface_world_size(w, d, h, wall)
        lx, ly = _surface_local_coords(w, d, h, wall, p)
        if ww <= 0 or wh <= 0:
            return QPoint(int(rx), int(ry))
        return QPoint(int(rx + lx / ww * rw), int(ry + ly / wh * rh))

    def _draw_pending_wire(self, painter: QPainter, walls: list[str], w: float, d: float, h: float) -> None:
        if not self._pending_wire_point or not self._pending_wire_wall:
            return
        wall = self._pending_wire_wall
        if wall not in walls:
            return
        rx, ry, rw, rh = self._wall_screen_rect(wall)
        ww, wh = _surface_world_size(w, d, h, wall)
        lx = float(self._pending_wire_point.get("u", 0))
        ly = float(self._pending_wire_point.get("v", 0))
        pt = QPoint(int(rx + lx / max(ww, 0.001) * rw), int(ry + ly / max(wh, 0.001) * rh))
        color = QColor(LAYER_COLORS.get(self.active_layer or ELECTRICITY, "#2563eb"))
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(pt, 5, 5)

    def _draw_door_hint(self, painter: QPainter) -> None:
        if not self.room:
            return
        rooms = self._sibling_count()
        if rooms < 2:
            return
        wall = "south"
        rx, ry, rw, rh = self._wall_screen_rect(wall)
        door_w = max(18.0, rw * 0.18)

        painter.setPen(QPen(QColor("#b45309"), 2))
        painter.setBrush(QBrush(QColor("#fef3c7")))
        painter.drawRoundedRect(int(rx + rw / 2 - door_w / 2), int(ry + rh - min(rh * 0.45, 64)),
                                int(door_w), int(min(rh * 0.45, 64)), 4, 4)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#92400e"))
        painter.drawText(int(rx + rw / 2 - door_w / 2), int(ry + rh - min(rh * 0.45, 64) / 2),
                         "→ дверь")
        self._door_rect = (rx + rw / 2 - door_w / 2, ry + rh - min(rh * 0.45, 64), door_w, min(rh * 0.45, 64))

    def _sibling_count(self) -> int:
        # количество комнат в квартире определяется внешним миром; храним как атрибут
        return int(getattr(self, "_rooms_total", 0))

    def set_rooms_total(self, count: int) -> None:
        if count != getattr(self, "_rooms_total", 0):
            self._rooms_total = count
            self.update()

    # --------------------------------------------------------------- клики
    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            if self.edit_mode:
                self.rightClickExit.emit()
                self.message.emit("Выход из редактирования (правый клик).")
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # дверь?
        door = getattr(self, "_door_rect", None)
        if door and self.room_layer_visible and door[0] <= pos.x() <= door[0] + door[2] and \
                door[1] <= pos.y() <= door[1] + door[3]:
            self.roomActivated.emit()
            return
        wall = self._wall_at(pos)
        if not wall:
            return
        editable_layer_active = self.edit_mode and bool(self.active_layer)
        # клик по существующему объекту?
        hit = self._element_at(wall, pos)
        if hit and not (editable_layer_active and self.tool and self.tool != "select"):
            self.selected_id = hit
            self.selectionChanged.emit(hit)
            self.update()
            return
        if not editable_layer_active:
            self.wallSelected.emit(wall)
            return
        layer = self.active_layer
        if layer == WATER:
            self.message.emit("Библиотека водоснабжения будет добавлена после испытаний.")
            return
        w, d, h = self._dims()
        tool = self.tool or "select"
        if tool == "select":
            self.wallSelected.emit(wall)
            return
        local = self._to_surface_point(wall, pos)
        if tool == "wire":
            ww, wh = _surface_world_size(w, d, h, wall)
            u, v = _surface_local_coords(w, d, h, wall, local)
            if self._pending_wire_point is None or self._pending_wire_wall != wall:
                self._pending_wire_point = {"wall": wall, "u": u, "v": v, **local}
                self._pending_wire_wall = wall
                self.message.emit(f"{WALL_LABELS.get(wall, wall)}: отмечено начало провода. Кликните конец на этой же поверхности.")
            else:
                start = point3(**{k: self._pending_wire_point[k] for k in ("x", "y", "z")})
                self._create_element("wire", wall, start=start, end=local)
                self._pending_wire_point = None
                self._pending_wire_wall = None
            self.update()
            return
        self._create_element(tool, wall, start=local, end=local)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_id and self.room and self.edit_mode:
            element = next((e for e in self.room.get("elements", []) if e.get("id") == self._drag_id), None)
            if element and self._drag_last is not None:
                wall = element.get("wall", "north")
                w, d, h = self._dims()
                rx, ry, rw, rh = self._wall_screen_rect(wall)
                ww, wh = _surface_world_size(w, d, h, wall)
                du = (pos.x() - self._drag_last[0]) / max(rw, 1) * ww
                dv = (pos.y() - self._drag_last[1]) / max(rh, 1) * wh
                if abs(du) + abs(dv) > 0.001:
                    self._apply_drag_delta(element, wall, w, d, h, du, dv)
                    self._drag_last = (pos.x(), pos.y())
                    self.dataChanged.emit()
                    self.update()
            return
        self._update_cursor(pos)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_id:
            self._drag_id = None
            self._drag_last = None
            self.store_snapshot_after_drag()
        super().mouseReleaseEvent(event)

    def store_snapshot_after_drag(self) -> None:
        pass  # снимок уже записан при начале перетаскивания

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.mousePressEvent(event)

    def _update_cursor(self, pos) -> None:
        if self._element_at_any(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._wall_at(pos):
            self.setCursor(Qt.CursorShape.CrossCursor if (self.edit_mode and self.tool) else Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _wall_at(self, pos) -> str | None:
        for wall, (rx, ry, rw, rh) in self._surface_rects.items():
            if rx <= pos.x() <= rx + rw and ry <= pos.y() <= ry + rh:
                return wall
        return None

    def _element_at(self, wall: str, pos) -> str | None:
        if not self.room:
            return None
        w, d, h = self._dims()
        best_id, best_dist = None, 14.0
        for element in self.room.get("elements", []):
            if element.get("wall", "north") != wall or not self._element_visible(element):
                continue
            if self.edit_mode and self.active_layer and element.get("layer") != self.active_layer:
                continue
            start = self._project_to_surface(w, d, h, wall, element.get("start", {}))
            if element.get("kind") == "wire":
                end = self._project_to_surface(w, d, h, wall, element.get("end", {}))
                dist = _point_segment_distance(pos.x(), pos.y(), start.x(), start.y(), end.x(), end.y())
            else:
                dist = math.hypot(pos.x() - start.x(), pos.y() - start.y())
            if dist <= best_dist:
                best_dist, best_id = dist, element.get("id")
        return best_id

    def _element_at_any(self, pos) -> str | None:
        wall = self._wall_at(pos)
        return self._element_at(wall, pos) if wall else None

    def _apply_drag_delta(self, element: dict[str, Any], wall: str, w: float, d: float, h: float, du: float, dv: float) -> None:
        """Смещение объекта вдоль его поверхности с обратным пересчётом в 3D."""
        mapping = {
            "north": lambda p: point3(p["x"] + du, 0.0, clamp(p["z"] - dv, 0, h)),
            "south": lambda p: point3(clamp(p["x"] - du, 0, w), d, clamp(p["z"] - dv, 0, h)),
            "west": lambda p: point3(0.0, clamp(p["y"] - dv, 0, d), clamp(p["z"] - du, 0, h)),
            "east": lambda p: point3(w, clamp(p["y"] + dv, 0, d), clamp(p["z"] - du, 0, h)),
            "floor": lambda p: point3(clamp(p["x"] + du, 0, w), clamp(p["y"] + dv, 0, d), 0.0),
            "ceiling": lambda p: point3(clamp(p["x"] + du, 0, w), clamp(p["y"] + dv, 0, d), h),
        }.get(wall)
        if not mapping:
            return
        if not getattr(self, "_drag_snapshot_done", False):
            self.record_undo()
            self._drag_snapshot_done = True
        element["start"] = mapping(dict(element.get("start", {})))
        if element.get("kind") == "wire":
            element["end"] = mapping(dict(element.get("end", {})))

    # переопределяем начало перетаскивания: фиксируем drag при нажатии на объект
    def _begin_drag(self, element_id: str, pos) -> None:
        self._drag_id = element_id
        self._drag_last = (pos.x(), pos.y())
        self._drag_snapshot_done = False

    def _create_element(self, kind: str, wall: str, start: dict[str, float], end: dict[str, float]) -> None:
        if not self.room:
            return
        self.record_undo()
        counter = sum(1 for e in self.room.get("elements", []) if e.get("kind") == kind) + 1
        element = normalize_element({
            "id": new_id(),
            "name": f"{self.KIND_DEFAULT_NAMES.get(kind, 'Объект')} {counter}",
            "kind": kind,
            "layer": self.active_layer or ELECTRICITY,
            "wall": wall,
            "start": start,
            "end": end if kind == "wire" else point3(**end),
            "voltage": 230.0 if (self.active_layer or ELECTRICITY) == ELECTRICITY else 0.0,
        })
        self.room.setdefault("elements", []).append(element)
        self.selected_id = element["id"]
        self.elementCreated.emit(element["id"])
        self.dataChanged.emit()


def _wall_of_selection(room: dict[str, Any] | None, element_id: str | None) -> str | None:
    if not room or not element_id:
        return None
    element = next((e for e in room.get("elements", []) if e.get("id") == element_id), None)
    return element.get("wall") if element else None


def _surface_world_size(w: float, d: float, h: float, wall: str) -> tuple[float, float]:
    if wall in ("north", "south"):
        return w, h
    if wall in ("east", "west"):
        return d, h
    return w, d


def _surface_local_coords(w: float, d: float, h: float, wall: str, p: dict[str, float]) -> tuple[float, float]:
    x, y, z = float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("z", 0))
    if wall == "north":
        return x, h - z
    if wall == "south":
        return w - x, h - z
    if wall == "west":
        return d - y, h - z
    if wall == "east":
        return y, h - z
    return x, d - y  # floor / ceiling


def _local_from_surface(w: float, d: float, h: float, wall: str, u: float, v: float) -> dict[str, float]:
    if wall == "north":
        return point3(clamp(u, 0, w), 0.0, clamp(h - v, 0, h))
    if wall == "south":
        return point3(clamp(w - u, 0, w), d, clamp(h - v, 0, h))
    if wall == "west":
        return point3(0.0, clamp(d - v, 0, d), clamp(h - u, 0, h))
    if wall == "east":
        return point3(w, clamp(v, 0, d), clamp(h - u, 0, h))
    if wall == "floor":
        return point3(clamp(u, 0, w), clamp(d - v, 0, d), 0.0)
    return point3(clamp(u, 0, w), clamp(d - v, 0, d), h)


def _point_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq <= 1e-9:
        return math.hypot(px - x1, py - y1)
    t = clamp(((px - x1) * dx + (py - y1) * dy) / len_sq, 0.0, 1.0)
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))




def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def json_loads(blob: str) -> Any:
    return json.loads(blob)
