"""Диалоги приложения: управление квартирами и параметры комнаты."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from model import DataStore, new_id


class RoomDialog(QDialog):
    """Создание/редактирование комнаты: название и размеры в метрах."""

    def __init__(
        self,
        parent: QWidget | None = None,
        room: dict[str, Any] | None = None,
        number: int = 1,
    ) -> None:
        super().__init__(parent)
        self.room = room
        self._created_values: dict[str, Any] | None = None
        self.setWindowTitle("Комната" if room else "Новая комната")
        self.setModal(True)
        self.setMinimumWidth(340)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        title = QLabel("Параметры комнаты" if room else "Создание комнаты")
        title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)
        self.name_edit = QLineEdit(str((room or {}).get("name") or f"Комната {number}"))
        self.width_spin = QDoubleSpinBox()
        self.depth_spin = QDoubleSpinBox()
        self.height_spin = QDoubleSpinBox()
        for spin in (self.width_spin, self.depth_spin, self.height_spin):
            spin.setRange(0.5, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setSuffix(" м")
        self.width_spin.setValue(float((room or {}).get("width", 4.0)))
        self.depth_spin.setValue(float((room or {}).get("depth", 3.0)))
        self.height_spin.setValue(float((room or {}).get("height", 2.7)))
        form.addRow("Название:", self.name_edit)
        form.addRow("Ширина:", self.width_spin)
        form.addRow("Глубина:", self.depth_spin)
        form.addRow("Высота:", self.height_spin)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Сохранить")
        ok.setObjectName("primaryButton")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

    def _on_ok(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Название", "Введите название комнаты.")
            return
        if self.room is not None:
            self.room["name"] = self.name_edit.text().strip()
            self.room["width"] = self.width_spin.value()
            self.room["depth"] = self.depth_spin.value()
            self.room["height"] = self.height_spin.value()
        else:
            self._created_values = {
                "id": new_id(),
                "name": self.name_edit.text().strip(),
                "width": self.width_spin.value(),
                "depth": self.depth_spin.value(),
                "height": self.height_spin.value(),
                "description": "",
                "elements": [],
                "wall_properties": {},
            }
        self.accept()

    def room_values(self) -> dict[str, Any]:
        """Для нового объекта — словарь комнаты; для существующего — сама комната."""
        if self.room is not None:
            return self.room
        if self._created_values is None:
            self._created_values = {
                "id": new_id(),
                "name": self.name_edit.text().strip() or "Комната",
                "width": self.width_spin.value(),
                "depth": self.depth_spin.value(),
                "height": self.height_spin.value(),
                "description": "",
                "elements": [],
                "wall_properties": {},
            }
        return self._created_values


class ApartmentManagerDialog(QDialog):
    """Управление квартирами: выбор, создание, удаление, план, список комнат."""

    def __init__(self, store: DataStore, current_apartment_id: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.selected_apartment_id: str | None = current_apartment_id
        self.selected_room_id: str | None = None
        self.setWindowTitle("Управление квартирами")
        self.setModal(True)
        self.resize(760, 520)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        # --- Левая колонка: список квартир ------------------------------------
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(QLabel("Квартиры"))
        self.apartment_list = QListWidget()
        self.apartment_list.setMinimumWidth(260)
        self.apartment_list.currentItemChanged.connect(lambda *_: self._load_details())
        left.addWidget(self.apartment_list, 1)

        row = QHBoxLayout()
        add_button = QPushButton("+ Создать")
        add_button.clicked.connect(self._create_apartment)
        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self._delete_apartment)
        row.addWidget(add_button)
        row.addWidget(delete_button)
        left.addLayout(row)
        root.addLayout(left)

        # --- Правая колонка: детали квартиры ----------------------------------
        right = QVBoxLayout()
        right.setSpacing(8)
        self.details_title = QLabel("Выберите квартиру")
        self.details_title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        right.addWidget(self.details_title)

        form = QFormLayout()
        form.setSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._apply_name)
        self.description_edit = QLineEdit()
        self.description_edit.editingFinished.connect(self._apply_description)
        form.addRow("Название:", self.name_edit)
        form.addRow("Описание:", self.description_edit)
        right.addLayout(form)

        plan_row = QHBoxLayout()
        self.plan_label = QLabel("План: не загружен")
        self.plan_label.setObjectName("muted")
        load_plan = QPushButton("Загрузить план…")
        load_plan.clicked.connect(self._load_plan)
        clear_plan = QPushButton("Убрать план")
        clear_plan.clicked.connect(self._clear_plan)
        plan_row.addWidget(self.plan_label, 1)
        plan_row.addWidget(load_plan)
        plan_row.addWidget(clear_plan)
        right.addLayout(plan_row)

        self.plan_preview = QLabel()
        self.plan_preview.setMinimumHeight(120)
        self.plan_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plan_preview.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 8px; background: #ffffff;")
        right.addWidget(self.plan_preview, 1)

        right.addWidget(QLabel("Комнаты:"))
        self.room_list = QListWidget()
        self.room_list.setMinimumHeight(90)
        right.addWidget(self.room_list, 1)

        open_row = QHBoxLayout()
        self.open_check = QCheckBox("Открыть выбранную комнату после закрытия")
        self.open_check.setChecked(True)
        open_row.addWidget(self.open_check)
        open_row.addStretch(1)
        right.addLayout(open_row)
        root.addLayout(right, 2)

        # --- Нижняя кнопка ------------------------------------------------------
        bottom = QVBoxLayout()
        close_button = QPushButton("Закрыть и открыть выбранную")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self._accept)
        bottom.addStretch(1)
        bottom.addWidget(close_button)
        root.addLayout(bottom)

        self._populate(current_apartment_id)

    # ---------------------------------------------------------------- helpers
    def _populate(self, select_id: str | None) -> None:
        self.apartment_list.clear()
        for apartment in self.store.apartments:
            item = QListWidgetItem(apartment.get("name", "Квартира"))
            item.setData(Qt.ItemDataRole.UserRole, apartment.get("id"))
            self.apartment_list.addItem(item)
            if apartment.get("id") == select_id:
                self.apartment_list.setCurrentItem(item)
        if self.apartment_list.count() and self.apartment_list.currentItem() is None:
            self.apartment_list.setCurrentRow(0)
        self._load_details()

    def _current_id(self) -> str | None:
        item = self.apartment_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _load_details(self) -> None:
        apartment_id = self._current_id()
        self.selected_apartment_id = apartment_id
        apartment = self.store.get_apartment(apartment_id)
        has = apartment is not None
        for widget in (self.name_edit, self.description_edit, self.room_list):
            widget.setEnabled(has)
        self.details_title.setText(apartment.get("name", "Квартира") if has else "Выберите квартиру")
        self.name_edit.blockSignals(True)
        self.description_edit.blockSignals(True)
        self.name_edit.setText(str((apartment or {}).get("name", "")))
        self.description_edit.setText(str((apartment or {}).get("description", "")))
        self.name_edit.blockSignals(False)
        self.description_edit.blockSignals(False)
        self.room_list.clear()
        for room in (apartment or {}).get("rooms", []):
            item = QListWidgetItem(f"{room.get('name', 'Комната')}  ·  "
                                   f"{room.get('width', 0):g}×{room.get('depth', 0):g}×{room.get('height', 0):g} м")
            item.setData(Qt.ItemDataRole.UserRole, room.get("id"))
            self.room_list.addItem(item)
        self._update_plan_view(apartment)

    def _update_plan_view(self, apartment: dict[str, Any] | None) -> None:
        plan_path = (apartment or {}).get("plan_path")
        self.plan_label.setText(f"План: {plan_path}" if plan_path else "План: не загружен")
        pixmap = QPixmap(plan_path) if plan_path else QPixmap()
        if pixmap.isNull():
            self.plan_preview.setPixmap(QPixmap())
            self.plan_preview.setText("План помещения не загружен" if apartment else "")
        else:
            self.plan_preview.setPixmap(pixmap.scaled(
                self.plan_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    # ----------------------------------------------------------------- actions
    def _create_apartment(self) -> None:
        name, count = f"Квартира {len(self.store.apartments) + 1}", len(self.store.apartments) + 1
        apartment = self.store.create_apartment(name)
        self._populate(apartment["id"])

    def _delete_apartment(self) -> None:
        apartment_id = self._current_id()
        apartment = self.store.get_apartment(apartment_id)
        if not apartment:
            return
        answer = QMessageBox.question(
            self,
            "Удалить квартиру?",
            f"Удалить «{apartment.get('name')}» со всеми комнатами? Действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_apartment(apartment_id)
        if self.selected_apartment_id == apartment_id:
            self.selected_apartment_id = None
            self.selected_room_id = None
        self._populate(None)

    def _apply_name(self) -> None:
        apartment_id = self._current_id()
        text = self.name_edit.text().strip()
        if apartment_id and text:
            self.store.rename_apartment(apartment_id, text)
            item = self.apartment_list.currentItem()
            if item:
                item.setText(text)
            self.details_title.setText(text)

    def _apply_description(self) -> None:
        apartment = self.store.get_apartment(self._current_id())
        if apartment:
            apartment["description"] = self.description_edit.text().strip()
            self.store.save()

    def _load_plan(self) -> None:
        apartment_id = self._current_id()
        if not apartment_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Выберите файл плана", "", "Изображения (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.store.set_plan(apartment_id, path)
            self._update_plan_view(self.store.get_apartment(apartment_id))

    def _clear_plan(self) -> None:
        apartment_id = self._current_id()
        if apartment_id:
            self.store.set_plan(apartment_id, None)
            self._update_plan_view(self.store.get_apartment(apartment_id))

    def _accept(self) -> None:
        self.selected_apartment_id = self._current_id()
        room_item = self.room_list.currentItem()
        self.selected_room_id = str(room_item.data(Qt.ItemDataRole.UserRole)) if (room_item and self.open_check.isChecked()) else None
        self.store.save()
        self.accept()
