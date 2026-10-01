from __future__ import annotations

import collections.abc as c
import typing as t

from qgis.PyQt.QtCore import QItemSelection, QModelIndex, Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .utils import color_row, get_list_widget_items, get_table_item


class QListWidgetAlwaysSelected(QListWidget):
    """Ensures there is always an item selected."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        model = self.model()
        assert model is not None
        model.rowsInserted.connect(self._select_first_row)

    def _select_first_row(
        self, index: QModelIndex, first: int, last: int
    ) -> None:
        self.setCurrentRow(first)
        model = self.model()
        assert model is not None
        model.rowsInserted.disconnect()

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
        layout.addWidget(self.label)

    def update_loading_label(self, text: str) -> None:
        self.label.setText(text)


class JoinReportRow(t.NamedTuple):
    label: str
    level: str
    code: str
    matched: bool


class JoinReportDialog(QDialog):
    """Lists the units of a matrix and whether GISCO has their boundaries."""

    HEADERS = ['Label', 'Level', 'NUTS code', 'Matched']

    def __init__(
        self, rows: c.Sequence[JoinReportRow], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle('Join report')
        table = QTableWidget(len(rows), len(self.HEADERS), self)
        table.setHorizontalHeaderLabels(self.HEADERS)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, row in enumerate(rows):
            texts = (
                row.label,
                row.level,
                row.code,
                '✔' if row.matched else '✘',
            )
            for column, text in enumerate(texts):
                get_table_item(table, i, column).setText(text)
            color = QColor('green' if row.matched else 'red')
            color.setAlpha(50)
            color_row(table, i, color)
        table.resizeColumnsToContents()
        layout = QVBoxLayout(self)
        layout.addWidget(table)
        self.setLayout(layout)
        self.resize(500, 400)
