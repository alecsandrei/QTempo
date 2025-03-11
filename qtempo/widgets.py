from __future__ import annotations

from qgis.PyQt.QtCore import QItemSelection, QModelIndex, Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .utils import get_list_widget_items


class QListWidgetAlwaysSelected(QListWidget):
    """Ensures there is always an item selected."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.MultiSelection)
        self.model().rowsInserted.connect(self._select_first_row)

    def _select_first_row(
        self, index: QModelIndex, first: int, last: int
    ) -> None:
        self.setCurrentRow(first)
        self.model().rowsInserted.disconnect()

    def _get_first_visible_item(self) -> QListWidgetItem | None:
        for item in get_list_widget_items(self):
            if not item.isHidden():
                return item
        return None

    def selectionChanged(
        self, selected: QItemSelection, deselected: QItemSelection
    ):
        if not self.selectedItems():
            last_deselected = deselected.last().indexes()[-1]
            is_row_hidden = self.isRowHidden(last_deselected.row())
            if not is_row_hidden:
                self.setCurrentIndex(last_deselected)
            else:
                self.setCurrentItem(self._get_first_visible_item())
        super().selectionChanged(selected, deselected)


class LoadingDialog(QDialog):
    def __init__(self, base: QWidget | None = None):
        self.base = base
        super().__init__(base)
        self.setWindowTitle(' ')
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(QFont(self.label.font().family(), 15))
        self.layout().addWidget(self.label)

    def update_loading_label(self, text: str) -> None:
        self.label.setText(text)
