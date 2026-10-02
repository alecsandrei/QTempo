from __future__ import annotations

import collections.abc as c
from types import SimpleNamespace

import pytest
from qgis.core import QgsNetworkAccessManager, QgsProject
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QLabel,
    QListWidgetItem,
    QPushButton,
)

from qtempo.enums import QListWidgetItemRole, Tabs, WidgetProperty
from qtempo.matrix import Field, Fields, Matrix
from qtempo.qtempo import Dialog, MatrixModel
from qtempo.utils import get_widgets

from .helpers import (
    agr101a,
    by_sex,
    localities,
    long_values,
    many_options,
    not_geographic,
    wait_until,
)


@pytest.fixture
def dialog() -> c.Iterator[Dialog]:
    qtempo = SimpleNamespace(network_manager=QgsNetworkAccessManager.instance())
    dialog = Dialog(qtempo)
    yield dialog
    # A shown dialog would stay open
    sip.delete(dialog)


def show(dialog: Dialog, matrix: Matrix) -> None:
    """Shows the matrix as the response of a query."""
    item = QListWidgetItem('AGR101A', dialog.listWidgetMatrices)
    item.setData(QListWidgetItemRole.MATRIX.value, matrix)
    item.setData(QListWidgetItemRole.CONTEXT.value, {'code': 'AGR101A'})
    # Selecting a matrix fetches its dimensions
    dialog.listWidgetMatrices.blockSignals(True)
    dialog.listWidgetMatrices.setCurrentItem(item)
    dialog.listWidgetMatrices.blockSignals(False)
    dialog.update_table()


def combo_boxes(dialog: Dialog) -> dict[str, QComboBox]:
    layout = dialog.frameTableOptions.layout()
    assert layout is not None
    return {
        combo_box.property(WidgetProperty.FIELD.value).name: combo_box
        for combo_box in get_widgets(layout, QComboBox)
    }


def shown(dialog: Dialog) -> Matrix:
    matrix = dialog.get_model_matrix()
    assert matrix is not None
    return matrix


def is_enabled(button: QPushButton) -> bool:
    """Whether the button is enabled, even if its tab is not."""
    return button.isEnabledTo(button.parentWidget())


def assert_options_scroll(dialog: Dialog, scrolls: bool) -> None:
    """Asserts whether the options scroll, which they only do down."""
    area = dialog.scrollAreaTableOptions
    horizontal = area.horizontalScrollBar()
    assert horizontal is not None
    assert horizontal.maximum() == 0
    vertical = area.verticalScrollBar()
    assert vertical is not None
    assert (vertical.maximum() > 0) is scrolls


def names(matrix: Matrix) -> list[str]:
    return [field_.name for field_ in matrix.fields]


def test_years_default_to_columns(dialog: Dialog) -> None:
    show(dialog, agr101a())
    options = combo_boxes(dialog)
    assert {name: box.currentText() for name, box in options.items()} == {
        'Categorii': 'Agricola',
        'Ani': '',
    }
    categories = options['Categorii']
    assert [categories.itemText(i) for i in range(categories.count())] == [
        '',
        'Agricola',
        'Arabila',
    ]
    assert names(shown(dialog)) == ['Judete', 'Anul 1990', 'Anul 2000']
    assert dialog.labelTableSummary.text() == '3 rows × 3 columns'
    assert not dialog.mGroupBoxTableOptions.isHidden()
    assert is_enabled(dialog.pushButtonAddVectorLayer)


def test_an_empty_option_spreads_into_columns(dialog: Dialog) -> None:
    show(dialog, agr101a())
    combo_boxes(dialog)['Categorii'].setCurrentIndex(0)
    assert names(shown(dialog)) == [
        'Judete',
        'Agricola · Anul 1990',
        'Agricola · Anul 2000',
        'Arabila · Anul 2000',
    ]


def test_an_option_keeps_the_rows_of_its_value(dialog: Dialog) -> None:
    show(dialog, agr101a())
    categories = combo_boxes(dialog)['Categorii']
    categories.setCurrentIndex(categories.findText('Arabila'))
    assert names(shown(dialog)) == ['Judete', 'Anul 2000']
    assert shown(dialog).data == [
        ['Municipiul Bucuresti', 100.0],
        ['Ilfov', 200.0],
    ]


def test_options_are_rebuilt_for_another_query(dialog: Dialog) -> None:
    show(dialog, agr101a())
    show(dialog, by_sex())
    assert {
        name: box.currentText() for name, box in combo_boxes(dialog).items()
    } == {'Sexe': 'Total', 'Ani': ''}
    assert shown(dialog).data == [['Cluj', 1.0, 1.0]]


def test_no_options_for_single_values(dialog: Dialog) -> None:
    show(dialog, localities())
    assert combo_boxes(dialog) == {}
    assert dialog.labelTableSummary.text() == '3 rows × 2 columns'


def test_no_options_without_units(dialog: Dialog) -> None:
    matrix = not_geographic()
    show(dialog, matrix)
    assert dialog.mGroupBoxTableOptions.isHidden()
    assert shown(dialog) is matrix
    assert not is_enabled(dialog.pushButtonAddVectorLayer)


def test_long_values_do_not_widen_the_options(dialog: Dialog) -> None:
    # Combo boxes may fit their values when they are first shown
    dialog.show()
    show(dialog, agr101a())
    QCoreApplication.processEvents()
    width = combo_boxes(dialog)['Categorii'].sizeHint().width()
    dialog_width = dialog.minimumSizeHint().width()
    show(dialog, long_values())
    QCoreApplication.processEvents()
    categories = combo_boxes(dialog)['Categorii']
    assert categories.isVisible()
    assert categories.sizeHint().width() == width
    assert dialog.minimumSizeHint().width() == dialog_width
    view = categories.view()
    assert view is not None
    assert view.minimumWidth() >= view.sizeHintForColumn(0)
    values = [categories.itemText(i) for i in range(1, categories.count())]
    assert [
        categories.itemData(i, Qt.ItemDataRole.ToolTipRole)
        for i in range(1, categories.count())
    ] == values


# A dialog with one column of options, and one with two
NARROW = 800
WIDE = 2400


@pytest.mark.parametrize(
    ('width', 'count', 'scrolls'),
    [(NARROW, 3, False), (NARROW, 4, True), (WIDE, 6, False), (WIDE, 7, True)],
)
def test_options_past_three_rows_scroll(
    dialog: Dialog, width: int, count: int, scrolls: bool
) -> None:
    show(dialog, many_options(count))
    assert len(combo_boxes(dialog)) == count
    # Resized from the other width, so that the options reflow
    dialog.resize(NARROW + WIDE - width, 700)
    dialog.show()
    QCoreApplication.processEvents()
    dialog.resize(width, 700)
    wait_until(lambda: dialog.width() == width)
    QCoreApplication.processEvents()
    assert_options_scroll(dialog, scrolls)


def test_options_fit_when_their_tab_is_shown(dialog: Dialog) -> None:
    dialog.resize(NARROW, 700)
    dialog.show()
    show(dialog, many_options(3))
    QCoreApplication.processEvents()
    # The data of a query is shown from the query tab
    dialog.tabWidgetMatrix.setCurrentIndex(Tabs.QUERY.value)
    show(dialog, many_options(4))
    QCoreApplication.processEvents()
    assert_options_scroll(dialog, True)


def test_option_labels_wrap_no_more_than_they_prefer(dialog: Dialog) -> None:
    show(dialog, many_options(4))
    # Wide enough for the options in one column, not in two
    dialog.resize(1300, 700)
    dialog.show()
    QCoreApplication.processEvents()
    layout = dialog.frameTableOptions.layout()
    assert layout is not None
    for label in get_widgets(layout, QLabel):
        # The height of the text, as the rows are as tall as combo boxes
        assert label.heightForWidth(label.width()) <= label.sizeHint().height()


def test_squeezed_options_hide_no_row(dialog: Dialog) -> None:
    show(dialog, agr101a())
    dialog.resize(NARROW, 700)
    dialog.show()
    QCoreApplication.processEvents()
    # Dragging the handle as far right as it goes
    dialog.splitterCatalogue.setSizes([10_000, 1])
    for event in range(5):
        QCoreApplication.processEvents()
    area = dialog.scrollAreaTableOptions
    horizontal = area.horizontalScrollBar()
    assert horizontal is not None
    assert horizontal.maximum() > 0
    vertical = area.verticalScrollBar()
    assert vertical is not None
    assert vertical.maximum() == 0


def test_add_table_layer_exports_the_shown_table(
    dialog: Dialog, qgis_new_project: None
) -> None:
    show(dialog, agr101a())
    dialog.add_table_layer()
    project = QgsProject.instance()
    assert project is not None
    [layer] = project.mapLayersByName('AGR101A')
    assert layer.fields().names() == [
        'Judete',
        'Anul 1990',
        'Anul 2000',
        'NUTS_ID',
    ]
    assert layer.featureCount() == 3


def test_matrix_model_formats_the_values() -> None:
    matrix = Matrix(
        [['Cluj', 23787.0], ['Ilfov', 1.5], ['Bihor', None]],
        Fields([Field('Judete', is_jud=True), Field('Valoare', is_value=True)]),
    )
    model = MatrixModel(matrix)
    assert [
        model.data(model.index(row, 1)) for row in range(model.rowCount())
    ] == ['23787', '1.5', '']
    alignment = Qt.ItemDataRole.TextAlignmentRole
    assert model.data(model.index(0, 1), alignment) == (
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    assert model.data(model.index(0, 0), alignment) is None
    assert [
        model.headerData(
            column, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        )
        for column in range(model.columnCount())
    ] == ['Judete', 'Valoare']
