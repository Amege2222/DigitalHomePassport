# Версия 7 — полностью переработанный рабочий экран по обновлённому ТЗ.
from __future__ import annotations

import math
import sys
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from canvas import ApartmentPlanCanvas, RoomCanvas
from dialogs import ApartmentManagerDialog, RoomDialog
from model import (
    ALL_LAYERS,
    COMMUNICATION_LAYERS,
    ELECTRICITY,
    INTERNET,
    KIND_LABELS,
    LABEL_TO_WALL,
    LAYER_COLORS,
    LAYER_LABELS,
    ROOM_LAYER,
    WALLS,
    WALL_LABELS,
    WATER,
    DataStore,
    clamp,
    point3,
)

APP_STYLE = """
QWidget {
    background: #f7f9fc;
    color: #1f2937;
    font-family: "Segoe UI", "Arial";
    font-size: 10pt;
}
QMainWindow { background: #eef2f6; }
QFrame#topBar, QFrame#card, QFrame#sidePanel, QFrame#infoPanel {
    background: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 10px;
}
QLabel#appTitle { font-size: 17pt; font-weight: 700; color: #172334; }
QLabel#sectionHeading { font-size: 11pt; font-weight: 700; color: #26374a; }
QLabel#muted { color: #64748b; }
QLabel#activeLayer { color: #1d4ed8; font-weight: 700; }
QPushButton {
    background: #ffffff;
    color: #243244;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 7px 11px;
    min-height: 24px;
}
QPushButton:hover { background: #eef4fb; border-color: #94a3b8; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:checked { background: #dbeafe; border: 2px solid #3b82f6; color: #1d4ed8; font-weight: 700; }
QPushButton#primaryButton { background: #2563eb; color: #ffffff; border: 1px solid #1d4ed8; font-weight: 700; }
QPushButton#primaryButton:hover { background: #1d4ed8; }
QPushButton#dangerButton { color: #b91c1c; border-color: #fecaca; }
QPushButton#layer_room:checked { background: #e8edf3; border: 2px solid #94a3b8; }
QPushButton#layer_electricity:checked { background: #e0f2fe; border: 2px solid #1685d1; color: #075985; }
QPushButton#layer_water:checked { background: #cffafe; border: 2px solid #0891b2; color: #155e75; }
QPushButton#layer_internet:checked { background: #fae8ff; border: 2px solid #c026d3; color: #86198f; }
QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox, QListWidget {
    background: #ffffff;
    color: #172334;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px;
    selection-background-color: #bfdbfe;
    selection-color: #172334;
}
QComboBox QAbstractItemView { background: #ffffff; color: #172334; selection-background-color: #dbeafe; }
QCheckBox { color: #26374a; spacing: 6px; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #e2e8f0; }
QToolTip { background: #fffbe6; color: #1f2937; border: 1px solid #cbd5e1; padding: 4px; }
"""


class LayerButton(QPushButton):
    doubleClicked = pyqtSignal()

    def __init__(self, layer: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.layer = layer
        self.setCheckable(True)
        self.setObjectName(f"layer_{layer}")
        self.setToolTip("Нажатие — показать/скрыть слой. В режиме редактирования двойное нажатие включает редактирование слоя.")
        self.setMinimumHeight(36)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.doubleClicked.emit()
        event.accept()


class ProjectPicker(QWidget):
    openRequested = pyqtSignal(str)
    createRequested = pyqtSignal()
    manageRequested = pyqtSignal()
    exitRequested = pyqtSignal()

    def __init__(self, store: DataStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(44, 34, 44, 34)
        root.addStretch(1)

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(780)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 30, 32, 30)
        card_layout.setSpacing(14)
        title = QLabel("Инженерная схема квартиры")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Выберите квартиру или создайте новый проект")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(8)
        self.apartment_list = QListWidget()
        self.apartment_list.setMinimumHeight(230)
        self.apartment_list.itemDoubleClicked.connect(self._open_current)
        card_layout.addWidget(self.apartment_list)
        buttons = QHBoxLayout()
        self.create_button = QPushButton("+ Создать квартиру")
        self.create_button.setObjectName("primaryButton")
        self.open_button = QPushButton("Открыть")
        self.manage_button = QPushButton("Управление")
        self.exit_button = QPushButton("Выход")
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.manage_button)
        buttons.addWidget(self.exit_button)
        card_layout.addLayout(buttons)
        root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

        self.create_button.clicked.connect(self.createRequested.emit)
        self.open_button.clicked.connect(self._open_current)
        self.manage_button.clicked.connect(self.manageRequested.emit)
        self.exit_button.clicked.connect(self.exitRequested.emit)
        self.refresh()

    def refresh(self, selected_id: str | None = None) -> None:
        self.apartment_list.clear()
        row_to_select = 0
        for i, apartment in enumerate(self.store.apartments):
            rooms_count = len(apartment.get("rooms", []))
            item = QListWidgetItem(f"{apartment.get('name', 'Квартира')}    ·    комнат: {rooms_count}")
            item.setData(Qt.ItemDataRole.UserRole, apartment.get("id"))
            self.apartment_list.addItem(item)
            if apartment.get("id") == selected_id:
                row_to_select = i
        if self.apartment_list.count():
            self.apartment_list.setCurrentRow(row_to_select)
        self.open_button.setEnabled(bool(self.apartment_list.count()))
        if not self.store.apartments:
            self.apartment_list.addItem("Пока нет квартир — нажмите «Создать квартиру».")
            self.apartment_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            self.open_button.setEnabled(False)

    def _open_current(self, *_args) -> None:
        item = self.apartment_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole):
            self.openRequested.emit(str(item.data(Qt.ItemDataRole.UserRole)))


class LibraryPanel(QFrame):
    toolSelected = pyqtSignal(str)

    TOOL_LIBRARY = {
        ELECTRICITY: [
            ("select", "Выбрать / переместить", "↖"),
            ("wire", "Провод — отрезок", "━━"),
            ("branch", "Разветвление", "●"),
            ("socket", "Розетка", "⊙"),
            ("switch", "Выключатель", "S"),
            ("lamp", "Светильник", "✳"),
        ],
        INTERNET: [
            ("select", "Выбрать / переместить", "↖"),
            ("wire", "Провод — отрезок", "━━"),
            ("branch", "Разветвление", "●"),
            ("socket", "Сетевая розетка", "RJ"),
        ],
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(310)
        self._buttons: list[QPushButton] = []
        self._active_tool: str | None = None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(13, 13, 13, 13)
        self.root.setSpacing(8)
        heading = QLabel("Библиотека")
        heading.setObjectName("sectionHeading")
        self.root.addWidget(heading)
        self.subheading = QLabel("Выберите слой двойным нажатием")
        self.subheading.setWordWrap(True)
        self.subheading.setObjectName("muted")
        self.root.addWidget(self.subheading)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.root.addWidget(self.list_container)
        self.root.addStretch(1)

    def _clear_buttons(self) -> None:
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def set_state(self, edit_mode: bool, active_layer: str | None, view_is_room: bool, active_tool: str | None = None) -> None:
        self._clear_buttons()
        self._active_tool = active_tool
        self.subheading.setText(
            f"Слой: {LAYER_LABELS.get(active_layer, 'не выбран')}" if active_layer else
            ("Включите режим редактирования, затем дважды нажмите на слой." if view_is_room else "В режиме плана квартиры библиотека недоступна.")
        )
        if not view_is_room:
            tip = QLabel("Для добавления объектов откройте комнату в 3D-окне.")
            tip.setWordWrap(True)
            tip.setObjectName("muted")
            self.list_layout.addWidget(tip)
            return
        if not edit_mode or not active_layer:
            tip = QLabel("В режиме просмотра элементы можно выбирать. Для размещения новых объектов включите редактирование и активируйте слой двойным нажатием.")
            tip.setWordWrap(True)
            tip.setObjectName("muted")
            self.list_layout.addWidget(tip)
            return
        if active_layer == WATER:
            tip = QLabel("Библиотека водоснабжения будет добавлена после испытаний — согласно текущему ТЗ.")
            tip.setWordWrap(True)
            self.list_layout.addWidget(tip)
            return
        for kind, label, icon_text in self.TOOL_LIBRARY.get(active_layer, []):
            button = QPushButton(f"{icon_text}    {label}")
            button.setMinimumHeight(36)
            button.setCheckable(True)
            button.setChecked(kind == active_tool)
            if kind == "wire":
                button.setStyleSheet(f"text-align:left; color:{LAYER_COLORS[active_layer]}; font-weight:700;")
            else:
                button.setStyleSheet("text-align:left;")
            button.clicked.connect(lambda _checked=False, k=kind: self.toolSelected.emit(k))
            self._buttons.append(button)
            self.list_layout.addWidget(button)
        help_label = QLabel("Провод: два щелчка на одной поверхности. Символ: один щелчок.")
        help_label.setWordWrap(True)
        help_label.setObjectName("muted")
        self.list_layout.addSpacing(4)
        self.list_layout.addWidget(help_label)


class PropertiesPanel(QFrame):
    applyRequested = pyqtSignal(str, object)
    deleteRequested = pyqtSignal(str)
    objectSelected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(310)
        self.selected_element: dict[str, Any] | None = None
        self._widgets: dict[str, QWidget] = {}
        self._is_loading = False
        self._selector_loading = False
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(13, 13, 13, 13)
        self.root.setSpacing(8)
        title = QLabel("Свойства")
        title.setObjectName("sectionHeading")
        self.root.addWidget(title)
        self.object_selector = QComboBox()
        self.object_selector.addItem("Выбрать объект на схеме…", "")
        self.object_selector.currentIndexChanged.connect(self._selector_changed)
        self.root.addWidget(self.object_selector)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self.scroll.setWidget(self.body)
        self.root.addWidget(self.scroll, 1)
        self.apply_button = QPushButton("Применить свойства")
        self.apply_button.setObjectName("primaryButton")
        self.delete_button = QPushButton("Удалить выбранный объект")
        self.delete_button.setObjectName("dangerButton")
        self.apply_button.clicked.connect(self._apply)
        self.delete_button.clicked.connect(self._delete)
        self.root.addWidget(self.apply_button)
        self.root.addWidget(self.delete_button)
        self._clear_body()

    def set_object_list(
        self,
        room: dict[str, Any] | None,
        selected_id: str | None,
        edit_mode: bool,
        active_layer: str | None,
    ) -> None:
        self._selector_loading = True
        self.object_selector.clear()
        self.object_selector.addItem("Выбрать объект на схеме…", "")
        if room:
            for element in room.get("elements", []):
                if edit_mode and (not active_layer or element.get("layer") != active_layer):
                    continue
                name = str(element.get("name", "Объект"))
                markers = []
                if element.get("status") == "Скрытый":
                    markers.append("скрытый")
                if element.get("routing") == "Скрытая":
                    markers.append("скрытая прокладка")
                if markers:
                    name += "  [" + ", ".join(markers) + "]"
                self.object_selector.addItem(name, element.get("id"))
        current = 0
        if selected_id:
            for row in range(self.object_selector.count()):
                if self.object_selector.itemData(row) == selected_id:
                    current = row
                    break
        self.object_selector.setCurrentIndex(current)
        self.object_selector.setEnabled(bool(room and self.object_selector.count() > 1))
        self._selector_loading = False

    def _selector_changed(self, _index: int) -> None:
        if not self._selector_loading:
            self.objectSelected.emit(str(self.object_selector.currentData() or ""))

    def _clear_body(self) -> None:
        self._widgets.clear()
        self._clear_layout_items(self.body_layout)
        self.selected_element = None
        self.apply_button.setEnabled(False)
        self.delete_button.setEnabled(False)

    def _clear_layout_items(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout_items(child_layout)
                child_layout.deleteLater()

    def _heading(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("sectionHeading")
        self.body_layout.addWidget(label)

    def _label(self, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("muted")
        self.body_layout.addWidget(label)

    def _form(self) -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(7)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.body_layout.addLayout(form)
        return form

    def _add_line(self, form: QFormLayout, key: str, label: str, value: Any = "", enabled: bool = True) -> None:
        widget = QLineEdit(str(value if value is not None else ""))
        widget.setEnabled(enabled)
        self._widgets[key] = widget
        form.addRow(label, widget)

    def _add_combo(self, form: QFormLayout, key: str, label: str, values: list[str], value: str, enabled: bool = True) -> None:
        widget = QComboBox()
        widget.addItems(values)
        if value in values:
            widget.setCurrentText(value)
        widget.setEnabled(enabled)
        self._widgets[key] = widget
        form.addRow(label, widget)

    def _add_number(self, form: QFormLayout, key: str, label: str, value: Any, max_value: float = 1000.0, enabled: bool = True) -> None:
        widget = QDoubleSpinBox()
        widget.setRange(-max_value if key.startswith("start_") or key.startswith("end_") else 0, max_value)
        widget.setDecimals(3)
        widget.setSingleStep(0.1)
        try:
            widget.setValue(float(value))
        except (ValueError, TypeError):
            widget.setValue(0.0)
        widget.setEnabled(enabled)
        self._widgets[key] = widget
        form.addRow(label, widget)

    def show_room_summary(self, room: dict[str, Any] | None, editing: bool = False) -> None:
        self._clear_body()
        if not room:
            self._heading("Комната не выбрана")
            self._label("Выберите квартиру или добавьте комнату.")
            return
        self._heading(str(room.get("name", "Комната")))
        form = self._form()
        for key, label in (("width", "Ширина, м"), ("depth", "Глубина, м"), ("height", "Высота, м")):
            self._add_line(form, key, label, room.get(key, ""), enabled=False)
        self._label("Выберите объект на схеме, чтобы просмотреть его свойства.")

    def show_wall(self, room: dict[str, Any], wall: str, editable: bool = False) -> None:
        self._clear_body()
        self._heading(WALL_LABELS.get(wall, wall))
        w, d, h = float(room.get("width", 4)), float(room.get("depth", 3)), float(room.get("height", 2.7))
        dimensions = f"{w:g} м × {h:g} м" if wall in ("north", "south") else (
            f"{d:g} м × {h:g} м" if wall in ("east", "west") else f"{w:g} м × {d:g} м"
        )
        self._label(f"Размер поверхности: {dimensions}")
        walls = room.setdefault("wall_properties", {})
        props = walls.setdefault(wall, {"description": ""})
        self._label("Свойства стены доступны для просмотра. Редактирование слоя помещения отложено в текущем ТЗ.")
        self._label("Описание: " + (props.get("description") or "не задано"))

    def show_element(self, room: dict[str, Any], element: dict[str, Any], editable: bool) -> None:
        self._clear_body()
        self.selected_element = element
        self._heading(str(element.get("name", "Объект")))
        self._label(f"Тип: {KIND_LABELS.get(element.get('kind'), element.get('kind', 'Объект'))} · {LAYER_LABELS.get(element.get('layer'), element.get('layer'))}")
        self._label("Координаты указаны в метрах относительно комнаты.")
        can_edit = editable and element.get("layer") in COMMUNICATION_LAYERS
        form = self._form()
        self._add_line(form, "name", "Название", element.get("name", ""), can_edit)
        wall_values = [WALL_LABELS[w] for w in WALLS]
        self._add_combo(form, "wall", "Поверхность", wall_values, WALL_LABELS.get(element.get("wall", "north"), "Северная стена"), can_edit)

        start = element.get("start", {}) if isinstance(element.get("start"), dict) else {}
        w, d, h = float(room.get("width", 4)), float(room.get("depth", 3)), float(room.get("height", 2.7))
        max_dimension = max(100.0, w, d, h)
        self._add_number(form, "start_x", "X начала, м", start.get("x", 0), max_dimension, can_edit)
        self._add_number(form, "start_y", "Y начала, м", start.get("y", 0), max_dimension, can_edit)
        self._add_number(form, "start_z", "Z начала, м", start.get("z", 0), max_dimension, can_edit)
        if element.get("kind") == "wire":
            end = element.get("end", {}) if isinstance(element.get("end"), dict) else {}
            self._add_number(form, "end_x", "X конца, м", end.get("x", 0), max_dimension, can_edit)
            self._add_number(form, "end_y", "Y конца, м", end.get("y", 0), max_dimension, can_edit)
            self._add_number(form, "end_z", "Z конца, м", end.get("z", 0), max_dimension, can_edit)

        self._add_line(form, "install_date", "Монтаж (ГГГГ-ММ-ДД)", element.get("install_date", ""), can_edit)
        self._add_line(form, "removal_date", "Демонтаж (ГГГГ-ММ-ДД)", element.get("removal_date", ""), can_edit)
        self._add_combo(form, "status", "Статус", ["Видимый", "Скрытый"], str(element.get("status", "Видимый")), can_edit)
        self._add_combo(form, "routing", "Прокладка", ["Открытая", "Скрытая"], str(element.get("routing", "Открытая")), can_edit)
        self._add_number(form, "voltage", "Вольтаж, В", element.get("voltage", 0), 100000.0, can_edit)
        self._add_number(form, "diameter", "Диаметр / сечение", element.get("diameter", 0), 10000.0, can_edit)
        self._add_line(form, "material", "Материал", element.get("material", ""), can_edit)
        if element.get("kind") == "socket":
            self._add_line(form, "socket_type", "Тип розетки", element.get("socket_type", "Евро"), can_edit)
        elif element.get("kind") == "switch":
            self._add_line(form, "switch_type", "Тип выключателя", element.get("switch_type", "Одноклавишный"), can_edit)
        elif element.get("kind") == "lamp":
            self._add_line(form, "lamp_type", "Тип лампы", element.get("lamp_type", "LED"), can_edit)
            self._add_number(form, "lamp_count", "Количество ламп", element.get("lamp_count", 1), 10000.0, can_edit)
            self._add_number(form, "watt", "Мощность, Вт", element.get("watt", 40), 100000.0, can_edit)

        all_elements = room.get("elements", [])
        names_by_id = {e.get("id"): e.get("name", "Объект") for e in all_elements}
        connection_names = [names_by_id.get(i, "Удалённый объект") for i in element.get("connections", [])]
        self._label("Связанные объекты: " + (", ".join(connection_names) if connection_names else "нет"))
        if not can_edit:
            self._label("Чтобы менять свойства, включите «Редактирование» и дважды нажмите на слой объекта.")
        self.apply_button.setEnabled(can_edit)
        self.delete_button.setEnabled(can_edit)

    def _read_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, widget in self._widgets.items():
            if isinstance(widget, QLineEdit):
                values[key] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentText()
            elif isinstance(widget, QDoubleSpinBox):
                values[key] = widget.value()
        return values

    def _apply(self) -> None:
        if self.selected_element:
            self.applyRequested.emit(str(self.selected_element.get("id")), self._read_values())

    def _delete(self) -> None:
        if self.selected_element:
            self.deleteRequested.emit(str(self.selected_element.get("id")))


class WorkspaceWidget(QWidget):
    requestManager = pyqtSignal()
    requestExit = pyqtSignal()
    apartmentChanged = pyqtSignal(str)

    def __init__(self, store: DataStore, apartment_id: str, room_id: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.apartment_id = apartment_id
        self.apartment = store.get_apartment(apartment_id)
        self.current_room_id = room_id or ((self.apartment or {}).get("rooms") or [{}])[0].get("id")
        self.view_kind = "room3d"
        self.edit_mode = False
        self.active_layer: str | None = None
        self.active_tool: str | None = None
        self.visible_layers: set[str] = set(COMMUNICATION_LAYERS)
        self.room_layer_visible = True
        self.selected_element_id: str | None = None
        self.selected_wall: str | None = None
        self._info_loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        root.addWidget(self._make_header())
        root.addWidget(self._make_layers_bar())

        workspace_split = QSplitter(Qt.Orientation.Horizontal)
        workspace_split.setChildrenCollapsible(False)
        self.canvas_stack = QStackedWidget()
        self.room_canvas = RoomCanvas()
        self.plan_canvas = ApartmentPlanCanvas()
        self.canvas_stack.addWidget(self.room_canvas)
        self.canvas_stack.addWidget(self.plan_canvas)
        self.canvas_stack.setMinimumWidth(480)
        workspace_split.addWidget(self.canvas_stack)

        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.setChildrenCollapsible(False)
        self.library_panel = LibraryPanel()
        self.properties_panel = PropertiesPanel()
        right_split.addWidget(self.library_panel)
        right_split.addWidget(self.properties_panel)
        right_split.setSizes([260, 460])
        workspace_split.addWidget(right_split)
        workspace_split.setSizes([900, 300])
        root.addWidget(workspace_split, 1)

        self.info_frame = QFrame()
        self.info_frame.setObjectName("infoPanel")
        info_layout = QVBoxLayout(self.info_frame)
        info_layout.setContentsMargins(12, 8, 12, 8)
        info_layout.setSpacing(5)
        info_heading = QLabel("Информационное поле")
        info_heading.setObjectName("sectionHeading")
        info_layout.addWidget(info_heading)
        self.info_edit = QPlainTextEdit()
        self.info_edit.setPlaceholderText("Описание квартиры, комнаты или выбранного объекта")
        self.info_edit.setMaximumHeight(82)
        info_layout.addWidget(self.info_edit)
        root.addWidget(self.info_frame)

        self.status_label = QLabel("Готово.")
        self.status_label.setObjectName("muted")
        root.addWidget(self.status_label)

        self.room_canvas.selectionChanged.connect(self._on_canvas_selection)
        self.room_canvas.wallSelected.connect(self._on_wall_selected)
        self.room_canvas.elementCreated.connect(self._on_element_created)
        self.room_canvas.dataChanged.connect(self._after_model_change)
        self.room_canvas.roomActivated.connect(self._next_room)
        self.room_canvas.cameraChanged.connect(self._sync_camera_combo)
        self.room_canvas.message.connect(self._set_status)
        self.room_canvas.rightClickExit.connect(lambda: self.edit_button.setChecked(False))
        self.plan_canvas.roomActivated.connect(self._open_room)
        self.library_panel.toolSelected.connect(self._set_tool)
        self.properties_panel.applyRequested.connect(self._apply_element_properties)
        self.properties_panel.deleteRequested.connect(self._delete_element)
        self.properties_panel.objectSelected.connect(self._on_object_selector_changed)
        self.info_edit.textChanged.connect(self._on_info_text_changed)

        self.info_timer = QTimer(self)
        self.info_timer.setSingleShot(True)
        self.info_timer.setInterval(450)
        self.info_timer.timeout.connect(self._save_info_text)

        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.undo_shortcut.activated.connect(self._undo)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.redo_shortcut.activated.connect(self._redo)
        self.redo_alt_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self.redo_alt_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.redo_alt_shortcut.activated.connect(self._redo)

        self._refresh_rooms_combo()
        self._sync_room_to_views()
        self._set_mode_state()
        self._refresh_selection_panel()

    def _make_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        self.view_3d_button = QPushButton("ОКНО 3D")
        self.view_3d_button.setCheckable(True)
        self.view_3d_button.setChecked(True)
        self.view_apartment_button = QPushButton("КВАРТИРА")
        self.view_apartment_button.setCheckable(True)
        self.view_group = [self.view_3d_button, self.view_apartment_button]
        self.view_3d_button.clicked.connect(lambda: self._set_view_kind("room3d"))
        self.view_apartment_button.clicked.connect(lambda: self._set_view_kind("apartment"))
        layout.addWidget(self.view_3d_button)
        layout.addWidget(self.view_apartment_button)
        title = QLabel("Квартира:")
        title.setObjectName("sectionHeading")
        layout.addWidget(title)
        self.apartment_title = QLabel((self.apartment or {}).get("name", "—"))
        self.apartment_title.setObjectName("activeLayer")
        self.apartment_title.setMinimumWidth(90)
        layout.addWidget(self.apartment_title)
        self.manage_button = QPushButton("Квартиры / комнаты")
        self.manage_button.clicked.connect(self.requestManager.emit)
        layout.addWidget(self.manage_button)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Комната:"))
        self.room_combo = QComboBox()
        self.room_combo.setMinimumWidth(135)
        self.room_combo.currentIndexChanged.connect(self._room_combo_changed)
        layout.addWidget(self.room_combo)
        self.add_room_button = QPushButton("+ Комната")
        self.add_room_button.clicked.connect(self._add_room)
        layout.addWidget(self.add_room_button)
        self.rename_room_button = QPushButton("Переименовать / размеры")
        self.rename_room_button.clicked.connect(self._edit_room)
        layout.addWidget(self.rename_room_button)
        self.delete_room_button = QPushButton("Удалить комнату")
        self.delete_room_button.setObjectName("dangerButton")
        self.delete_room_button.clicked.connect(self._delete_room)
        layout.addWidget(self.delete_room_button)
        layout.addStretch(1)
        self.exit_button = QPushButton("Выход")
        self.exit_button.clicked.connect(self.requestExit.emit)
        layout.addWidget(self.exit_button)
        return frame

    def _make_layers_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(7)
        label = QLabel("СЛОИ")
        label.setObjectName("sectionHeading")
        layout.addWidget(label)
        self.layer_buttons: dict[str, LayerButton] = {}
        for layer in ALL_LAYERS:
            button = LayerButton(layer, LAYER_LABELS[layer])
            button.setChecked(True)
            button.clicked.connect(lambda checked, l=layer: self._toggle_layer(l, checked))
            button.doubleClicked.connect(lambda l=layer: self._activate_layer_for_edit(l))
            self.layer_buttons[layer] = button
            layout.addWidget(button)
        layout.addSpacing(10)
        self.documents_button = QPushButton("Документы")
        self.documents_button.clicked.connect(self._show_documents_placeholder)
        layout.addWidget(self.documents_button)
        self.edit_button = QPushButton("Редактирование")
        self.edit_button.setCheckable(True)
        self.edit_button.toggled.connect(self._toggle_edit_mode)
        layout.addWidget(self.edit_button)
        layout.addSpacing(6)
        layout.addWidget(QLabel("Ракурс:"))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(RoomCanvas.CAMERA_LABELS)
        self.camera_combo.currentTextChanged.connect(self._camera_changed)
        self.camera_combo.setMinimumWidth(145)
        layout.addWidget(self.camera_combo)
        self.grid_check = QCheckBox("Сетка")
        self.grid_check.toggled.connect(self._update_grid_options)
        layout.addWidget(self.grid_check)
        self.snap_check = QCheckBox("Привязка")
        self.snap_check.toggled.connect(self._update_grid_options)
        layout.addWidget(self.snap_check)
        layout.addWidget(QLabel("Шаг"))
        self.grid_step = QComboBox()
        self.grid_step.addItems(["5 см", "10 см", "25 см", "50 см"])
        self.grid_step.setCurrentText("10 см")
        self.grid_step.currentTextChanged.connect(self._update_grid_options)
        self.grid_step.setMaximumWidth(84)
        layout.addWidget(self.grid_step)
        return frame

    def _toggle_layer(self, layer: str, checked: bool) -> None:
        if layer == ROOM_LAYER:
            self.room_layer_visible = checked
        elif checked:
            self.visible_layers.add(layer)
        else:
            self.visible_layers.discard(layer)
            if self.active_layer == layer:
                self.active_layer = None
                self.active_tool = None
                if self.selected_element_id:
                    selected = next((e for e in (self.current_room or {}).get("elements", []) if e.get("id") == self.selected_element_id), None)
                    if selected and selected.get("layer") == layer:
                        self.selected_element_id = None
                        self.room_canvas.select_element(None)
                if self.edit_mode:
                    self.room_canvas.set_active_layer(None)
        self._apply_visibility()
        self._refresh_library()
        self._refresh_selection_panel()
        self._refresh_info_field()
        self.room_canvas.update()

    def _activate_layer_for_edit(self, layer: str) -> None:
        if not self.edit_mode:
            self._set_status("Сначала включите режим «Редактирование», затем дважды нажмите на нужный слой.")
            return
        if self.view_kind != "room3d":
            self._set_status("Редактирование объектов доступно в окне 3D комнаты.")
            return
        if layer == ROOM_LAYER:
            self._set_status("Слой «Помещение» пока используется только для отображения, его редактирование отложено в ТЗ.")
            return
        if layer not in self.visible_layers:
            self.layer_buttons[layer].setChecked(True)
            self.visible_layers.add(layer)
        self.active_layer = layer
        self.active_tool = None
        self.selected_element_id = None
        self.selected_wall = None
        self.room_canvas.select_element(None)
        self.room_canvas.set_mode(True, layer)
        self._apply_visibility()
        self._refresh_library()
        self._refresh_selection_panel()
        self._set_status(f"Активен слой «{LAYER_LABELS[layer]}». Выберите объект в библиотеке.")

    def _toggle_edit_mode(self, enabled: bool) -> None:
        if enabled and self.view_kind != "room3d":
            self.edit_button.setChecked(False)
            self._set_status("Для редактирования откройте комнату в окне 3D.")
            return
        self.edit_mode = enabled
        self.active_layer = None
        self.active_tool = None
        if enabled:
            self.selected_element_id = None
            self.selected_wall = None
            self.room_canvas.select_element(None)
        self.room_canvas.set_mode(enabled, None)
        self._refresh_library()
        self._refresh_selection_panel()
        if enabled:
            self._set_status("Редактирование включено. Дважды нажмите на слой электричества или интернета.")
        else:
            self._set_status("Режим просмотра.")

    def _set_tool(self, kind: str) -> None:
        if not self.edit_mode or not self.active_layer:
            return
        if self.active_layer == WATER:
            self._set_status("Библиотека водоснабжения будет добавлена после испытаний.")
            return
        self.active_tool = kind
        self.room_canvas.set_tool(kind)
        self._refresh_library()

    def _apply_visibility(self) -> None:
        self.room_canvas.set_visible_layers(self.visible_layers, self.room_layer_visible)

    def _update_grid_options(self, *_args) -> None:
        try:
            step = int(self.grid_step.currentText().split()[0])
        except (ValueError, AttributeError):
            step = 10
        self.room_canvas.set_grid_options(self.grid_check.isChecked(), self.snap_check.isChecked(), step)

    def _camera_changed(self, text: str) -> None:
        if self.view_kind == "room3d":
            self.room_canvas.set_camera(text)

    def _sync_camera_combo(self, text: str) -> None:
        if self.camera_combo.currentText() != text:
            self.camera_combo.blockSignals(True)
            self.camera_combo.setCurrentText(text)
            self.camera_combo.blockSignals(False)

    def _set_view_kind(self, kind: str) -> None:
        # Checkable push buttons can uncheck themselves when clicked a second time;
        # force the active view button back to its expected state even on a no-op click.
        if kind == self.view_kind:
            self.view_3d_button.setChecked(kind == "room3d")
            self.view_apartment_button.setChecked(kind == "apartment")
            return
        self.view_kind = kind
        self.view_3d_button.setChecked(kind == "room3d")
        self.view_apartment_button.setChecked(kind == "apartment")
        self.canvas_stack.setCurrentWidget(self.room_canvas if kind == "room3d" else self.plan_canvas)
        self.camera_combo.setEnabled(kind == "room3d")
        self.grid_check.setEnabled(kind == "room3d")
        self.snap_check.setEnabled(kind == "room3d")
        self.grid_step.setEnabled(kind == "room3d")
        if kind == "apartment" and self.edit_mode:
            self.edit_button.setChecked(False)
        self.plan_canvas.set_apartment(self.apartment, self.current_room_id)
        self._refresh_library()
        self._refresh_selection_panel()
        self._refresh_info_field()
        self._set_status("2D-план квартиры. Нажмите на комнату, чтобы открыть её в окне 3D." if kind == "apartment" else "3D-окно комнаты.")

    def _refresh_rooms_combo(self, select_id: str | None = None) -> None:
        self.apartment = self.store.get_apartment(self.apartment_id)
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        rooms = (self.apartment or {}).get("rooms", [])
        for room in rooms:
            self.room_combo.addItem(str(room.get("name", "Комната")), room.get("id"))
        wanted = select_id or self.current_room_id
        target_row = next((i for i in range(self.room_combo.count()) if self.room_combo.itemData(i) == wanted), 0)
        if self.room_combo.count():
            self.room_combo.setCurrentIndex(target_row)
            self.current_room_id = self.room_combo.currentData()
        else:
            self.current_room_id = None
        self.room_combo.blockSignals(False)
        self.apartment_title.setText((self.apartment or {}).get("name", "—"))
        self.rename_room_button.setEnabled(bool(self.current_room_id))
        self.delete_room_button.setEnabled(bool(self.current_room_id))
        self._sync_room_to_views()

    def _room_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        room_id = self.room_combo.itemData(index)
        if room_id:
            self._open_room(str(room_id))

    def _open_room(self, room_id: str) -> None:
        room = self.store.get_room(self.apartment, room_id)
        if not room:
            return
        self.current_room_id = room_id
        self.selected_element_id = None
        self.selected_wall = None
        self.room_combo.blockSignals(True)
        row = next((i for i in range(self.room_combo.count()) if self.room_combo.itemData(i) == room_id), -1)
        if row >= 0:
            self.room_combo.setCurrentIndex(row)
        self.room_combo.blockSignals(False)
        self._sync_room_to_views()
        if self.view_kind == "apartment":
            self._set_view_kind("room3d")
        self._set_status(f"Открыта комната «{room.get('name', 'Комната')}».")

    def _sync_room_to_views(self) -> None:
        # Rebind the scene after room changes or dimension edits; clear selection
        # because the canvas resets its own selected object and undo snapshots.
        self.selected_element_id = None
        self.selected_wall = None
        room = self.store.get_room(self.apartment, self.current_room_id)
        self.room_canvas.set_room(room)
        self.room_canvas.set_camera(self.camera_combo.currentText() or "Развёртка")
        self._apply_visibility()
        self.plan_canvas.set_apartment(self.apartment, self.current_room_id)
        self._refresh_selection_panel()
        self._refresh_info_field()

    def _add_room(self) -> None:
        if not self.apartment:
            return
        number = len(self.apartment.get("rooms", [])) + 1
        dialog = RoomDialog(self, number=number)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        room = dialog.room_values()
        self.apartment.setdefault("rooms", []).append(room)
        self.store.save()
        self.current_room_id = room["id"]
        self.selected_element_id = None
        self.selected_wall = None
        self._refresh_rooms_combo(room["id"])
        self._set_status(f"Создана комната «{room['name']}».")

    def _edit_room(self) -> None:
        room = self.current_room
        if not room:
            return
        dialog = RoomDialog(self, room=room)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.room_values()
        self.store.save()
        self._refresh_rooms_combo(room["id"])
        self._set_status("Параметры комнаты сохранены.")

    def _delete_room(self) -> None:
        room = self.current_room
        if not room or not self.apartment:
            return
        answer = QMessageBox.question(
            self,
            "Удалить комнату?",
            f"Удалить комнату «{room.get('name')}» вместе со всеми её объектами?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.apartment["rooms"] = [r for r in self.apartment.get("rooms", []) if r.get("id") != room.get("id")]
        self.current_room_id = (self.apartment.get("rooms") or [{}])[0].get("id")
        self.selected_element_id = None
        self.selected_wall = None
        self.store.save()
        self._refresh_rooms_combo(self.current_room_id)
        self._set_status("Комната удалена.")

    @property
    def current_room(self) -> dict[str, Any] | None:
        return self.store.get_room(self.apartment, self.current_room_id)

    def _refresh_library(self) -> None:
        self.library_panel.set_state(self.edit_mode, self.active_layer, self.view_kind == "room3d", self.active_tool)

    def _refresh_selection_panel(self) -> None:
        room = self.current_room
        if not room:
            self.properties_panel.show_room_summary(None)
            self.properties_panel.set_object_list(None, None, self.edit_mode, self.active_layer)
            return
        if self.selected_element_id:
            element = next((e for e in room.get("elements", []) if e.get("id") == self.selected_element_id), None)
            if element:
                can_edit = self.edit_mode and self.active_layer == element.get("layer") and self.view_kind == "room3d"
                self.properties_panel.show_element(room, element, can_edit)
                self.properties_panel.set_object_list(room, self.selected_element_id, self.edit_mode, self.active_layer)
                return
            self.selected_element_id = None
        if self.selected_wall:
            self.properties_panel.show_wall(room, self.selected_wall, False)
        else:
            self.properties_panel.show_room_summary(room, self.edit_mode)
        self.properties_panel.set_object_list(room, self.selected_element_id, self.edit_mode, self.active_layer)

    def _on_object_selector_changed(self, element_id: str) -> None:
        self.selected_element_id = element_id or None
        self.selected_wall = None
        self.room_canvas.select_element(self.selected_element_id)
        self._refresh_selection_panel()
        self._refresh_info_field()

    def _refresh_info_field(self) -> None:
        self._info_loading = True
        room = self.current_room
        value = ""
        editable = False
        if self.view_kind == "apartment":
            value = str((self.apartment or {}).get("description", ""))
            editable = False
        elif room and self.selected_element_id:
            element = next((e for e in room.get("elements", []) if e.get("id") == self.selected_element_id), None)
            if element:
                value = str(element.get("description", ""))
                editable = self.edit_mode and self.active_layer == element.get("layer")
        elif room and self.selected_wall:
            value = str(room.setdefault("wall_properties", {}).setdefault(self.selected_wall, {}).get("description", ""))
            editable = False
        elif room:
            value = str(room.get("description", ""))
            editable = False
        self.info_edit.setPlainText(value)
        self.info_edit.setReadOnly(not editable)
        if editable:
            self.info_edit.setPlaceholderText("Введите описание выбранного объекта…")
        else:
            self.info_edit.setPlaceholderText("Описание квартиры или комнаты")
        self._info_loading = False

    def _on_info_text_changed(self) -> None:
        if self._info_loading or self.info_edit.isReadOnly():
            return
        self.info_timer.start()

    def _save_info_text(self) -> None:
        if self.info_edit.isReadOnly():
            return
        room = self.current_room
        if not room or not self.selected_element_id:
            return
        element = next((e for e in room.get("elements", []) if e.get("id") == self.selected_element_id), None)
        if element and element.get("layer") == self.active_layer:
            element["description"] = self.info_edit.toPlainText()
            self.store.save()

    def _on_canvas_selection(self, element_id: str) -> None:
        self.selected_element_id = element_id or None
        if element_id:
            self.selected_wall = None
        self.room_canvas.select_element(self.selected_element_id)
        self._refresh_selection_panel()
        self._refresh_info_field()

    def _on_wall_selected(self, wall: str) -> None:
        self.selected_wall = wall
        self.selected_element_id = None
        self._refresh_selection_panel()
        self._refresh_info_field()
        self._set_status(f"Выбрана поверхность: {WALL_LABELS.get(wall, wall)}.")

    def _on_element_created(self, element_id: str) -> None:
        self.selected_element_id = element_id
        self.selected_wall = None
        self._refresh_selection_panel()
        self._refresh_info_field()
        QTimer.singleShot(0, lambda element_id=element_id: self._offer_nearby_connection(element_id))

    def _offer_nearby_connection(self, element_id: str) -> None:
        room = self.current_room
        if not room:
            return
        created = next((e for e in room.get("elements", []) if e.get("id") == element_id), None)
        if not created:
            return
        points = [created.get("start", {})]
        if created.get("kind") == "wire" and isinstance(created.get("end"), dict):
            points.append(created["end"])
        candidates: list[dict[str, Any]] = []
        for other in room.get("elements", []):
            if other.get("id") == element_id or other.get("id") in created.get("connections", []):
                continue
            other_points = [other.get("start", {})]
            if other.get("kind") == "wire" and isinstance(other.get("end"), dict):
                other_points.append(other["end"])
            close = False
            for a in points:
                for b in other_points:
                    if math.dist([float(a.get(k, 0)) for k in ("x", "y", "z")], [float(b.get(k, 0)) for k in ("x", "y", "z")]) <= 0.16:
                        close = True
                        break
                if close:
                    break
            if close:
                candidates.append(other)
        if not candidates:
            return
        other = candidates[0]
        answer = QMessageBox.question(
            self,
            "Создать связь?",
            f"Конец нового объекта близко к «{other.get('name', 'объект')}». Создать связь между объектами?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            created.setdefault("connections", []).append(other["id"])
            other.setdefault("connections", []).append(created["id"])
            self.store.save()
            self._refresh_selection_panel()
            self._set_status(f"Создана связь: {created.get('name')} ↔ {other.get('name')}.")

    def _apply_element_properties(self, element_id: str, values: dict[str, Any]) -> None:
        room = self.current_room
        if not room:
            return
        element = next((e for e in room.get("elements", []) if e.get("id") == element_id), None)
        if not element or not self.edit_mode or element.get("layer") != self.active_layer:
            return
        self.room_canvas.record_undo()
        new_wall = LABEL_TO_WALL.get(values.get("wall", "Северная стена"), "north")
        w, d, h = float(room.get("width", 4)), float(room.get("depth", 3)), float(room.get("height", 2.7))

        def coords_from(prefix: str, raw: dict[str, Any]) -> dict[str, float]:
            result = {axis: float(values.get(f"{prefix}_{axis}", raw.get(axis, 0))) for axis in ("x", "y", "z")}
            result = {axis: clamp(result[axis], 0.0, cap) for axis, cap in (("x", w), ("y", d), ("z", h))}
            if new_wall == "north": result["y"] = 0.0
            elif new_wall == "south": result["y"] = d
            elif new_wall == "west": result["x"] = 0.0
            elif new_wall == "east": result["x"] = w
            elif new_wall == "floor": result["z"] = 0.0
            elif new_wall == "ceiling": result["z"] = h
            return result

        element["name"] = values.get("name", element.get("name", "Объект")) or element.get("name", "Объект")
        element["wall"] = new_wall
        element["start"] = coords_from("start", element.get("start", {}))
        if element.get("kind") == "wire":
            element["end"] = coords_from("end", element.get("end", {}))
        for key in ("install_date", "removal_date", "status", "routing", "material", "socket_type", "switch_type", "lamp_type"):
            if key in values:
                element[key] = values[key]
        for key in ("voltage", "diameter", "lamp_count", "watt"):
            if key in values:
                element[key] = values[key]
        self.selected_element_id = element_id
        self.selected_wall = None
        self.store.save()
        self.room_canvas.select_element(element_id)
        self.room_canvas.update()
        self._refresh_selection_panel()
        self._refresh_info_field()
        self._set_status("Свойства объекта сохранены.")

    def _delete_element(self, element_id: str) -> None:
        room = self.current_room
        if not room or not self.edit_mode or not self.active_layer:
            return
        element = next((e for e in room.get("elements", []) if e.get("id") == element_id), None)
        if not element or element.get("layer") != self.active_layer:
            return
        answer = QMessageBox.question(
            self,
            "Удалить объект?",
            f"Удалить «{element.get('name', 'Объект')}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.room_canvas.delete_element(element_id)
            self.selected_element_id = None
            self._refresh_selection_panel()
            self._refresh_info_field()
            self.store.save()

    def _after_model_change(self) -> None:
        self.store.save()
        self.plan_canvas.set_apartment(self.apartment, self.current_room_id)
        self._refresh_library()
        self._refresh_selection_panel()
        self._refresh_info_field()

    def _next_room(self) -> None:
        rooms = (self.apartment or {}).get("rooms", [])
        if len(rooms) < 2:
            self._set_status("Добавьте ещё одну комнату, чтобы перейти в неё через дверь.")
            return
        ids = [r.get("id") for r in rooms]
        try:
            index = ids.index(self.current_room_id)
        except ValueError:
            index = -1
        next_id = ids[(index + 1) % len(ids)]
        self._open_room(str(next_id))

    def _undo(self) -> None:
        if self.view_kind == "room3d" and self.edit_mode:
            if self.room_canvas.undo():
                self._after_model_change()

    def _redo(self) -> None:
        if self.view_kind == "room3d" and self.edit_mode:
            if self.room_canvas.redo():
                self._after_model_change()

    def _show_documents_placeholder(self) -> None:
        QMessageBox.information(
            self,
            "Документы",
            "Блок документов будет добавлен позже — согласно обновлённому ТЗ.",
        )

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_apartment(self, apartment_id: str, room_id: str | None = None) -> None:
        self.apartment_id = apartment_id
        self.apartment = self.store.get_apartment(apartment_id)
        self.current_room_id = room_id or ((self.apartment or {}).get("rooms") or [{}])[0].get("id")
        self.selected_element_id = None
        self.selected_wall = None
        self.edit_button.setChecked(False)
        self._refresh_rooms_combo(self.current_room_id)
        self.apartmentChanged.emit(apartment_id)

    def _open_manager(self) -> None:
        pass


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Инженерная схема квартиры — версия 7")
        self.resize(1500, 920)
        self.setMinimumSize(1150, 700)
        self.store = DataStore()
        self.current_apartment_id: str | None = None
        self.picker = ProjectPicker(self.store)
        self.picker.openRequested.connect(self.open_apartment)
        self.picker.createRequested.connect(self.create_apartment)
        self.picker.manageRequested.connect(self.manage_apartments_from_picker)
        self.picker.exitRequested.connect(self.close)
        self.workbench: WorkspaceWidget | None = None
        self.setCentralWidget(self.picker)

    def _show_picker(self, selected_id: str | None = None) -> None:
        if self.workbench:
            self.store.save()
            self.workbench.deleteLater()
            self.workbench = None
        self.picker.refresh(selected_id)
        self.setCentralWidget(self.picker)

    def create_apartment(self) -> None:
        number = len(self.store.apartments) + 1
        name, ok = QInputDialog.getText(self, "Новая квартира", "Название квартиры:", text=f"Квартира {number}")
        if not ok:
            return
        apartment = self.store.create_apartment(name.strip() or f"Квартира {number}")
        self.open_apartment(apartment["id"])

    def open_apartment(self, apartment_id: str, room_id: str | None = None) -> None:
        if not self.store.get_apartment(apartment_id):
            return
        if self.workbench:
            self.store.save()
            self.workbench.deleteLater()
        self.current_apartment_id = apartment_id
        self.workbench = WorkspaceWidget(self.store, apartment_id, room_id)
        self.workbench.requestManager.connect(self.manage_apartments_from_workbench)
        self.workbench.requestExit.connect(self.close)
        self.setCentralWidget(self.workbench)

    def manage_apartments_from_picker(self) -> None:
        dialog = ApartmentManagerDialog(self.store, self.current_apartment_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_apartment_id:
            self.open_apartment(dialog.selected_apartment_id, dialog.selected_room_id)
        else:
            self.store.save()
            self.picker.refresh(self.current_apartment_id)

    def manage_apartments_from_workbench(self) -> None:
        if not self.workbench:
            return
        current_id = self.workbench.apartment_id
        dialog = ApartmentManagerDialog(self.store, current_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_apartment_id:
            self.open_apartment(dialog.selected_apartment_id, dialog.selected_room_id)
        else:
            # The manager may still have changed room names/dimensions in the current apartment.
            self.workbench.apartment = self.store.get_apartment(self.workbench.apartment_id)
            self.workbench._refresh_rooms_combo(self.workbench.current_room_id)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.store.save()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())