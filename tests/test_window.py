from __future__ import annotations

import collections.abc as c
import json
import sys
import typing as t
from types import SimpleNamespace

import pytest
from qgis.core import QgsProject, QgsSettings
from qgis.gui import QgisInterface
from qgis.PyQt import sip
from qgis.PyQt.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from qtempo.enums import QListWidgetItemRole, Setting, Tabs
from qtempo.exceptions import RequestError
from qtempo.matrix import Matrix
from qtempo.qtempo import TUTORIAL_PANEL_MARGIN, Dialog, QTempo

from .helpers import (
    agr101a,
    localities,
    long_values,
    many_options,
    not_geographic,
    wait_until,
)

# The usable area of the MacBook Air the dialog was too big for
MACBOOK_AIR = QRect(0, 0, 1470, 844)


class FakeReply(QObject):
    """A reply that finishes when the test says so."""

    finished = pyqtSignal()
    errorOccurred = pyqtSignal(QNetworkReply.NetworkError)

    def __init__(self) -> None:
        super().__init__()
        self.code = QNetworkReply.NetworkError.NoError
        self.body = b''

    def error(self) -> QNetworkReply.NetworkError:
        return self.code

    def readAll(self) -> QByteArray:
        return QByteArray(self.body)

    def errorString(self) -> str:
        return 'Simulated request failure'

    def succeed(self, body: bytes = b'') -> None:
        self.body = body
        self.finished.emit()

    def fail(self) -> None:
        self.code = QNetworkReply.NetworkError.HostNotFoundError
        self.errorOccurred.emit(self.code)
        self.finished.emit()


class FakeManager:
    def __init__(self) -> None:
        self.replies: list[FakeReply] = []

    def reply(self) -> FakeReply:
        self.replies.append(FakeReply())
        return self.replies[-1]

    def get(self, request: QNetworkRequest) -> FakeReply:
        return self.reply()

    def post(self, request: QNetworkRequest, data: bytes) -> FakeReply:
        return self.reply()


def table_of_contents() -> bytes:
    context = {
        'code': '1',
        'name': 'A. STATISTICA SOCIALA',
        'childrenUrl': '',
        'comment': '',
        'url': '',
    }
    nodes = [{'parentCode': None, 'level': 0, 'context': context}]
    return json.dumps(nodes).encode('UTF-8')


def delete_later_objects() -> None:
    """Deletes the objects given to deleteLater, which wait for an event loop
    otherwise."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def reject_next_modal_dialog() -> list[str]:
    """Rejects the modal dialog about to open. The returned list gets its
    title, so the test can tell it opened."""
    titles: list[str] = []

    def reject() -> None:
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QDialog):
            titles.append(modal.windowTitle())
            modal.reject()

    QTimer.singleShot(0, reject)
    return titles


def visible_windows() -> set[QWidget]:
    return {
        widget
        for widget in QApplication.topLevelWidgets()
        if widget.isVisible()
    }


def rect_in_dialog(dialog: Dialog, widget: QWidget) -> QRect:
    return QRect(widget.mapTo(dialog, QPoint(0, 0)), widget.size())


def assert_panel_on(dialog: Dialog, pane: QWidget) -> None:
    """Asserts that the tutorial panel floats at the bottom of the pane."""
    rect = rect_in_dialog(dialog, pane)
    panel = dialog.tutorialPanel.geometry()
    assert rect.contains(panel)
    assert panel.left() == rect.left() + TUTORIAL_PANEL_MARGIN
    assert panel.bottom() == rect.bottom() - TUTORIAL_PANEL_MARGIN


def messages(dialog: Dialog) -> list[str]:
    return [item.text() for item in dialog.messageBar.items()]


def requests(plugin: QTempo) -> list[FakeReply]:
    return t.cast(FakeManager, plugin.network_manager).replies


def prepare_tutorial_work(dialog: Dialog, matrix: Matrix) -> None:
    """Load a selected dataset, data table, values and returned data."""
    from qgis.PyQt.QtCore import QSignalBlocker
    from qgis.PyQt.QtWidgets import QTreeWidgetItem
    from qtempo.enums import QTreeWidgetItemRole
    from qtempo.utils import get_children
    from .helpers import CATEGORIES, YEARS, request_body

    node = {'context': {'code': 'parent', 'name': 'Dataset'}}
    dataset = QTreeWidgetItem(dialog.treeWidgetTableOfContents)
    dataset.setData(0, QTreeWidgetItemRole.NODE.value, node)
    with QSignalBlocker(dialog.treeWidgetTableOfContents):
        dialog.treeWidgetTableOfContents.setCurrentItem(dataset)
    item = QListWidgetItem('Data table', dialog.listWidgetMatrices)
    item.setData(QListWidgetItemRole.PARENT_NODE.value, node)
    item.setData(QListWidgetItemRole.CONTEXT.value, {'code': 'TEST'})
    leaf = {
        'dimensionsMap': [CATEGORIES, YEARS],
        'details': request_body(matTime=2),
    }
    item.setData(QListWidgetItemRole.LEAF_NODE.value, leaf)
    item.setData(QListWidgetItemRole.LEAF_NODE_RO.value, leaf)
    with QSignalBlocker(dialog.listWidgetMatrices):
        dialog.listWidgetMatrices.setCurrentItem(item)
    dialog.add_dimensions_to_frame_query(leaf['dimensionsMap'])
    for widget in get_children(dialog.frameQuery, QListWidget):
        with QSignalBlocker(widget):
            widget.item(0).setSelected(True)
    item.setData(QListWidgetItemRole.MATRIX.value, matrix)
    item.setData(
        QListWidgetItemRole.QUERY_SIGNATURE.value,
        dialog._query_signature(),
    )
    dialog.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, matrix.has_units)
    dialog.update_table()


def go_to_tutorial_step(dialog: Dialog, name: str) -> None:
    """Advance through completed steps with the visible Next control."""
    while dialog._tutorial_steps()[dialog.tutorial_step] != name:
        assert dialog.pushButtonTutorialNext.isEnabled()
        dialog.pushButtonTutorialNext.click()


def test_tutorial_gates_dataset_and_locks_other_controls(
    dialog: Dialog,
) -> None:
    dialog.display_dialog()
    dialog.pushButtonTutorial.click()
    assert dialog.tutorial_step == 0
    assert not dialog.pushButtonTutorialNext.isEnabled()
    assert dialog.lineEditSearch.isEnabled()
    assert dialog.treeWidgetTableOfContents.isEnabled()
    assert not dialog.listWidgetMatrices.isEnabled()
    assert not dialog.tableViewMatrix.isEnabled()
    assert not dialog.checkBoxRomanian.isEnabled()
    assert not dialog.buttonBox.isEnabled()
    assert not dialog.pushButtonTutorial.isEnabled()
    assert not dialog.tabWidgetMatrix.tabBar().isEnabled()
    dialog.pushButtonTutorialNext.click()
    assert dialog.tutorial_step == 0
    dialog.pushButtonTutorialExit.click()
    assert dialog.checkBoxRomanian.isEnabled()
    assert dialog.buttonBox.isEnabled()
    assert dialog.pushButtonTutorial.isEnabled()


def test_tutorial_loads_dataset_and_data_table_before_advancing(
    dialog: Dialog, manager: FakeManager
) -> None:
    from qgis.PyQt.QtWidgets import QTreeWidgetItem
    from qtempo.enums import QTreeWidgetItemRole
    from .helpers import CATEGORIES, YEARS, request_body

    node = {
        'context': {'code': 'parent', 'name': 'Dataset'},
        'children': [
            {'code': 'TEST', 'name': 'Data table', 'childrenUrl': 'matrix'}
        ],
    }
    dataset = QTreeWidgetItem(dialog.treeWidgetTableOfContents)
    dataset.setData(0, QTreeWidgetItemRole.NODE.value, node)
    dialog.pushButtonTutorial.click()
    dialog.treeWidgetTableOfContents.setCurrentItem(dataset)
    assert dialog.tutorial_step == 0
    assert not dialog.pushButtonTutorialNext.isEnabled()
    assert len(manager.replies) == 1
    manager.replies[0].succeed(json.dumps(node).encode())
    wait_until(lambda: dialog.tutorial_step == 1)
    assert dialog.listWidgetMatrices.isEnabled()
    assert not dialog.pushButtonTutorialNext.isEnabled()
    dialog.listWidgetMatrices.setCurrentRow(0)
    leaf = {
        'dimensionsMap': [CATEGORIES, YEARS],
        'details': request_body(matTime=2),
    }
    manager.replies[1].succeed(json.dumps(leaf).encode())
    if len(manager.replies) > 2:
        manager.replies[2].succeed(json.dumps(leaf).encode())
    wait_until(lambda: dialog.tutorial_step == 2)
    assert dialog.scrollAreaQuery.isEnabled()
    assert dialog.pushButtonTutorialNext.isEnabled()


def test_tutorial_existing_work_table_route_and_escape(
    dialog: Dialog, manager: FakeManager, qgis_new_project: None
) -> None:
    prepare_tutorial_work(dialog, not_geographic())
    project = QgsProject.instance()
    assert project is not None
    before = set(project.mapLayers())
    dialog.display_dialog()
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'table_layer')
    assert dialog.tabWidgetMatrix.currentIndex() == Tabs.TABLE.value
    assert dialog.labelTutorialStep.text() == 'Step 6 of 6'
    assert not dialog.tabWidgetMatrix.isTabEnabled(Tabs.MAP.value)
    assert not dialog.tabWidgetMatrix.tabBar().isEnabled()
    assert 'boundaries' not in dialog._tutorial_steps()
    assert dialog.pushButtonAddTableLayer.isEnabled()
    assert not dialog.pushButtonTutorialNext.isEnabled()
    assert manager.replies == []
    assert set(project.mapLayers()) == before
    dialog.pushButtonTutorialBack.click()
    assert dialog._tutorial_steps()[dialog.tutorial_step] == 'table_options'
    dialog.pushButtonTutorialNext.click()
    assert dialog._tutorial_steps()[dialog.tutorial_step] == 'table_layer'
    dialog.add_table_layer()
    wait_until(lambda: dialog.tutorial_step == -1)
    assert len(project.mapLayers()) == len(before) + 1
    dialog.pushButtonTutorial.click()
    assert dialog.tutorial_step == 0
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.tutorial_step == -1
    assert dialog.isVisible()
    dialog.pushButtonTutorial.click()
    dialog.reject()
    assert dialog.tutorial_step == -1


def test_tutorial_query_and_request_stale_data(
    dialog: Dialog, qgis_new_project: None
) -> None:
    from qtempo.utils import get_children
    from qgis.PyQt.QtWidgets import QListWidget

    prepare_tutorial_work(dialog, not_geographic())
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'query')
    assert dialog.scrollAreaQuery.isEnabled()
    assert not dialog.pushButtonRequestData.isEnabled()
    dialog.pushButtonTutorialNext.click()
    assert dialog.pushButtonRequestData.isEnabled()
    assert not dialog.scrollAreaQuery.isEnabled()
    assert dialog.pushButtonTutorialNext.isEnabled()
    dialog.pushButtonTutorialBack.click()
    widgets = get_children(dialog.frameQuery, QListWidget)
    widgets[0].item(1).setSelected(True)
    dialog.pushButtonTutorialNext.click()
    assert dialog.tutorial_step == 3
    assert not dialog.pushButtonTutorialNext.isEnabled()
    dialog.pushButtonTutorialBack.click()
    widgets[0].item(1).setSelected(False)
    dialog.pushButtonTutorialNext.click()
    assert dialog.tutorial_step == 3
    assert dialog.pushButtonTutorialNext.isEnabled()


def test_tutorial_query_ctrl_a_selects_all_visible_options(
    dialog: Dialog, qgis_new_project: None
) -> None:
    from qtempo.utils import get_children

    prepare_tutorial_work(dialog, not_geographic())
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'query')
    options = get_children(dialog.frameQuery, QListWidget)[0]
    assert options.count() > 1
    wait_until(options.hasFocus)
    QTest.mouseClick(
        options.viewport(),
        Qt.MouseButton.LeftButton,
        pos=options.visualItemRect(options.item(1)).center(),
    )
    assert options.hasFocus()
    QTest.keyClick(
        t.cast(QWidget, QApplication.focusWidget()),
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert len(options.selectedItems()) == options.count()
    assert options.hasFocus()


def test_tutorial_table_options_require_valid_current_choices(
    dialog: Dialog, qgis_new_project: None
) -> None:
    from qtempo.utils import get_widgets
    from qgis.PyQt.QtWidgets import QComboBox

    prepare_tutorial_work(dialog, agr101a())
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'table_options')
    layout = dialog.frameTableOptions.layout()
    assert layout is not None
    combos = get_widgets(layout, QComboBox)
    assert combos
    assert dialog.pushButtonTutorialNext.isEnabled()
    combos[0].setCurrentIndex(-1)
    assert not dialog.pushButtonTutorialNext.isEnabled()
    combos[0].setCurrentIndex(0)
    wait_until(
        lambda: dialog._tutorial_steps()[dialog.tutorial_step] == 'boundaries'
    )


def test_tutorial_omits_column_choice_prompt_without_combos(
    dialog: Dialog, qgis_new_project: None
) -> None:
    from qgis.PyQt.QtWidgets import QComboBox
    from qtempo.utils import get_widgets

    prepare_tutorial_work(dialog, localities())
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'table_options')
    layout = dialog.frameTableOptions.layout()
    assert layout is not None
    assert get_widgets(layout, QComboBox) == []
    assert dialog.labelTutorialText.text() == (
        'The table is ready; no column options are needed.'
    )
    assert dialog.pushButtonTutorialNext.isEnabled()
    dialog.set_language('ro')
    assert dialog.labelTutorialText.text() == (
        'Tabelul este pregătit; nu sunt necesare opțiuni pentru coloane.'
    )


def test_tutorial_accepts_an_existing_matching_table_layer(
    dialog: Dialog, qgis_new_project: None
) -> None:
    prepare_tutorial_work(dialog, not_geographic())
    dialog.add_table_layer()
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'table_layer')
    assert dialog.pushButtonTutorialNext.isEnabled()
    dialog.pushButtonTutorialNext.click()
    assert dialog.tutorial_step == -1


@pytest.mark.parametrize(
    ('step', 'matrix_factory'),
    [('table_options', agr101a), ('table_layer', not_geographic)],
)
def test_tutorial_table_keeps_select_all_shortcut(
    dialog: Dialog,
    qgis_new_project: None,
    step: str,
    matrix_factory: c.Callable[[], Matrix],
) -> None:
    prepare_tutorial_work(dialog, matrix_factory())
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, step)
    wait_until(dialog.tableViewMatrix.hasFocus)
    QTest.keyClick(
        t.cast(QWidget, QApplication.focusWidget()),
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )
    selection = dialog.tableViewMatrix.selectionModel()
    assert selection is not None
    model = dialog.tableViewMatrix.model()
    assert model is not None
    assert (
        len(selection.selectedIndexes())
        == model.rowCount() * model.columnCount()
    )


def test_escape_exits_tutorial_from_the_table(
    dialog: Dialog, qgis_new_project: None
) -> None:
    prepare_tutorial_work(dialog, not_geographic())
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'table_options')
    wait_until(dialog.tableViewMatrix.hasFocus)
    QTest.keyClick(dialog.tableViewMatrix, Qt.Key.Key_Escape)
    assert dialog.tutorial_step == -1
    assert dialog.isVisible()


def test_tutorial_request_failure_keeps_gate_closed(
    dialog: Dialog, manager: FakeManager, qgis_new_project: None
) -> None:
    prepare_tutorial_work(dialog, not_geographic())
    item = dialog.listWidgetMatrices.currentItem()
    assert item is not None
    item.setData(QListWidgetItemRole.MATRIX.value, None)
    dialog.clear_table()
    errors: list[Exception] = []
    dialog.qtempo._handle_error_signal = errors.append
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'request')
    assert not dialog.pushButtonTutorialNext.isEnabled()
    dialog.pushButtonRequestData.click()
    assert not dialog.pushButtonRequestData.isEnabled()
    assert dialog.pushButtonTutorialExit.isEnabled()
    manager.replies[-1].fail()
    wait_until(lambda: not dialog.request_handler.replies)
    assert errors
    assert dialog.tutorial_step == 3
    assert not dialog.pushButtonTutorialNext.isEnabled()
    assert dialog.pushButtonRequestData.isEnabled()


def test_tutorial_successful_request_advances_after_data_is_loaded(
    dialog: Dialog, manager: FakeManager, qgis_new_project: None
) -> None:
    from .helpers import pivot

    prepare_tutorial_work(dialog, not_geographic())
    item = dialog.listWidgetMatrices.currentItem()
    assert item is not None
    item.setData(QListWidgetItemRole.MATRIX.value, None)
    dialog.clear_table()
    dialog.pushButtonTutorial.click()
    go_to_tutorial_step(dialog, 'request')
    dialog.pushButtonRequestData.click()
    assert dialog.tutorial_step == 3
    assert not dialog.pushButtonTutorialNext.isEnabled()
    manager.replies[-1].succeed(
        pivot(
            ['Categorii', 'Ani', 'Valoare'],
            ['Agricola', 'Anul 1990', '1'],
        )
    )
    wait_until(lambda: dialog.tutorial_step == 4)
    assert dialog.get_matrix() is not None
    assert dialog.get_model_matrix() is not None
    assert dialog.pushButtonTutorialNext.isEnabled()
    assert not dialog.checkBoxRomanian.isEnabled()


@pytest.mark.parametrize('matrix_factory', [localities, agr101a])
def test_tutorial_map_route_requires_boundaries_and_layers(
    dialog: Dialog,
    manager: FakeManager,
    qgis_new_project: None,
    monkeypatch: pytest.MonkeyPatch,
    matrix_factory: c.Callable[[], Matrix],
) -> None:
    from qgis.core import QgsField, QgsFields, QgsVectorLayer
    from qgis.PyQt.QtCore import QVariant
    from qtempo.services import nuts

    matrix = matrix_factory()
    monkeypatch.setattr(dialog, 'load_nuts_index', lambda *args: None)
    prepare_tutorial_work(dialog, matrix)
    if matrix_factory is agr101a:
        dialog.comboBoxGiscoYear.addItem('2024')
        dialog.comboBoxGiscoScale.addItem('03m')
        dialog.comboBoxGiscoProjection.addItem('4326')
        units = nuts.Units(
            [nuts.Unit('RO', nuts.SPATIAL_TYPE, '03m', '4326', '2024')]
        )
        monkeypatch.setattr(dialog, 'get_nuts_units', lambda: units)
    else:
        dialog.mGroupBoxServices.show()
    project = QgsProject.instance()
    assert project is not None
    dialog.display_dialog()
    dialog.pushButtonTutorial.click()
    assert dialog.tabWidgetMatrix.currentIndex() == Tabs.TABLE.value
    assert 'table_layer' not in dialog._tutorial_steps()
    go_to_tutorial_step(dialog, 'boundaries')
    assert dialog._tutorial_steps()[dialog.tutorial_step] == 'boundaries'
    assert dialog.labelTutorialStep.text() == (
        'Step 6 of 8' if matrix_factory is agr101a else 'Step 6 of 7'
    )
    assert dialog.tabWidgetMatrix.currentIndex() == Tabs.MAP.value
    assert not dialog.tabWidgetMatrix.tabBar().isEnabled()
    assert not dialog.pushButtonAddTableLayer.isEnabled()
    if matrix_factory is localities:
        assert dialog.pushButtonServiceInformation.isEnabled()
        titles = reject_next_modal_dialog()
        dialog.pushButtonServiceInformation.click()
        assert titles
        assert dialog._tutorial_steps()[dialog.tutorial_step] == 'boundaries'
        assert dialog.pushButtonServiceInformation.isEnabled()
    dialog.pushButtonTutorialBack.click()
    assert dialog._tutorial_steps()[dialog.tutorial_step] == 'table_options'
    assert dialog.tabWidgetMatrix.currentIndex() == Tabs.TABLE.value
    assert not dialog.pushButtonServiceInformation.isEnabled()
    dialog.pushButtonTutorialNext.click()
    assert dialog._tutorial_steps()[dialog.tutorial_step] == 'boundaries'
    assert dialog.pushButtonTutorialNext.isEnabled()
    dialog.pushButtonTutorialNext.click()
    if matrix_factory is agr101a:
        assert dialog._tutorial_steps()[dialog.tutorial_step] == 'join'
        assert not dialog.pushButtonTutorialNext.isEnabled()
        dialog.pushButtonValidateJoin.click()
        wait_until(
            lambda: (
                dialog._tutorial_steps()[dialog.tutorial_step] == 'vector_layer'
            )
        )
        assert any(not row.matched for row in dialog.join_report)
    else:
        assert dialog._tutorial_steps()[dialog.tutorial_step] == 'vector_layer'
    assert not dialog.pushButtonTutorialNext.isEnabled()
    assert manager.replies == []
    assert project.mapLayers() == {}
    if matrix_factory is agr101a:
        dialog.add_nuts_boundaries(
            {},
            'TEST',
            '4326',
            nuts.Boundaries(QgsFields(), [], {'RO': 'failed'}),
        )
        assert not dialog.pushButtonTutorialNext.isEnabled()
        assert project.mapLayers() == {}
    code = dialog.get_matrix_code()
    assert code is not None
    shown = dialog.get_model_matrix()
    assert shown is not None
    for level in dialog.get_map_levels(matrix):
        layer = QgsVectorLayer(
            'MultiPolygon?crs=EPSG:4326', f'{code} — {level.label}', 'memory'
        )
        provider = layer.dataProvider()
        assert provider is not None
        provider.addAttributes(
            [QgsField(field.name, QVariant.String) for field in shown.fields]
        )
        layer.updateFields()
        project.addMapLayer(layer)
    dialog.show_tutorial_step()
    wait_until(lambda: dialog.tutorial_step == -1)


def test_tutorial_exit_stays_enabled_during_request(
    dialog: Dialog, manager: FakeManager
) -> None:
    dialog.pushButtonTutorial.click()
    dialog.request_handler.get(QNetworkRequest(), 'Fetching')
    assert not dialog.treeWidgetTableOfContents.isEnabled()
    assert dialog.tutorialPanel.isEnabled()
    assert dialog.pushButtonTutorialExit.isEnabled()
    assert not dialog.pushButtonTutorialNext.isEnabled()
    dialog.pushButtonTutorialExit.click()
    assert not dialog.tutorialPanel.isVisible()
    manager.replies[0].succeed()
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert dialog.pushButtonTutorial.isEnabled()


def test_tutorial_updates_when_language_is_set_programmatically(
    dialog: Dialog,
) -> None:
    dialog.pushButtonTutorial.click()
    dialog.set_language('ro')
    assert dialog.pushButtonTutorialBack.text() == 'Înapoi'
    assert dialog.labelTutorialStep.text() == 'Pasul 1 din 6'
    assert dialog.labelTutorialText.text().startswith('Căutați')
    assert not dialog.checkBoxEnglish.isEnabled()


def test_the_tutorial_does_not_resize_the_dialog(dialog: Dialog) -> None:
    dialog.display_dialog()
    size = dialog.size()
    minimum = dialog.minimumSizeHint()
    dialog.pushButtonTutorial.click()
    QCoreApplication.processEvents()
    assert dialog.tutorialPanel.isVisible()
    assert dialog.size() == size
    assert dialog.minimumSizeHint() == minimum
    dialog.pushButtonTutorialExit.click()
    QCoreApplication.processEvents()
    assert dialog.size() == size
    assert dialog.minimumSizeHint() == minimum


def test_the_tutorial_panel_avoids_the_highlighted_control(
    dialog: Dialog, qgis_new_project: None
) -> None:
    prepare_tutorial_work(dialog, not_geographic())
    dialog.display_dialog()
    # A laptop screen, where each pane is wider than the panel
    size = QSize(1400, 800)
    dialog.resize(size)
    wait_until(lambda: dialog.size() == size)
    dialog.pushButtonTutorial.click()
    for step in dialog._tutorial_steps():
        go_to_tutorial_step(dialog, step)
        target = dialog.tutorial_target
        assert target is not None
        panel = dialog.tutorialPanel.geometry()
        assert dialog.rect().contains(panel)
        assert not panel.intersects(rect_in_dialog(dialog, target))
        if step == 'dataset':
            assert_panel_on(dialog, dialog.splitterMatrix)
        else:
            assert_panel_on(dialog, dialog.widgetCatalogue)


def test_the_tutorial_panel_follows_its_pane(dialog: Dialog) -> None:
    dialog.display_dialog()
    dialog.pushButtonTutorial.click()
    assert_panel_on(dialog, dialog.splitterMatrix)
    # Dragging the handle between the panes
    sizes = dialog.splitterCatalogue.sizes()
    dialog.splitterCatalogue.setSizes([sizes[0] + 100, sizes[1] - 100])
    assert dialog.splitterCatalogue.sizes() != sizes
    assert_panel_on(dialog, dialog.splitterMatrix)
    size = dialog.size() + QSize(120, 80)
    dialog.resize(size)
    wait_until(lambda: dialog.size() == size)
    assert_panel_on(dialog, dialog.splitterMatrix)


def test_the_tutorial_panel_wraps_its_text_in_a_narrow_pane(
    dialog: Dialog,
) -> None:
    dialog.display_dialog()
    dialog.pushButtonTutorial.click()
    dialog.splitterCatalogue.setSizes([10_000, 1])
    # The longer text
    dialog.set_language('ro')
    panel = dialog.tutorialPanel
    assert panel.width() >= panel.minimumSizeHint().width()
    assert panel.height() >= panel.heightForWidth(panel.width())
    assert dialog.rect().contains(panel.geometry())


@pytest.fixture
def main_window(qgis_iface: QgisInterface) -> QWidget:
    """The QGIS window, active as when the toolbar icon is clicked. It stays
    shown, as offscreen windows can't be activated again once hidden."""
    window = qgis_iface.mainWindow()
    assert window is not None
    window.show()
    window.activateWindow()
    wait_until(window.isActiveWindow)
    return window


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def new_dialog(
    qgis_iface: QgisInterface, main_window: QWidget, manager: FakeManager
) -> c.Iterator[c.Callable[[], Dialog]]:
    """Creates dialogs, e.g. one opened after QGIS restarts."""
    dialogs: list[Dialog] = []

    def create() -> Dialog:
        qtempo = SimpleNamespace(network_manager=manager, iface=qgis_iface)
        dialogs.append(Dialog(qtempo, main_window))
        return dialogs[-1]

    yield create
    # The QGIS window of the session would keep them
    for dialog in dialogs:
        sip.delete(dialog)


@pytest.fixture
def dialog(new_dialog: c.Callable[[], Dialog]) -> Dialog:
    return new_dialog()


@pytest.fixture
def plugin(
    qgis_iface: QgisInterface,
    main_window: QWidget,
    monkeypatch: pytest.MonkeyPatch,
) -> c.Iterator[QTempo]:
    monkeypatch.setattr('qtempo.qtempo.QgsNetworkAccessManager', FakeManager)
    plugin = QTempo(qgis_iface)
    plugin.initGui()
    yield plugin
    if not plugin.first_start and not sip.isdeleted(plugin.dialog):
        plugin.unload()
        delete_later_objects()


def test_a_request_shows_its_progress_inside_the_dialog(
    dialog: Dialog, manager: FakeManager, main_window: QWidget
) -> None:
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    dialog.request_handler.get(QNetworkRequest(), 'Fetching')
    assert not dialog.treeWidgetTableOfContents.isEnabled()
    assert dialog.messageBar.isEnabled()
    assert messages(dialog) == ['Fetching']
    assert visible_windows() == {main_window, dialog}
    assert dialog.isActiveWindow()
    manager.replies[0].succeed()
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert messages(dialog) == []
    assert dialog.isActiveWindow()


def test_chained_requests_keep_the_dialog_disabled(
    dialog: Dialog, manager: FakeManager
) -> None:
    handler = dialog.request_handler
    handler.get(QNetworkRequest(), 'First')
    [first] = manager.replies
    enabled: list[bool] = []

    def start_second() -> None:
        enabled.append(dialog.treeWidgetTableOfContents.isEnabled())
        handler.get(QNetworkRequest(), 'Second')

    first.finished.connect(start_second)
    first.succeed()
    wait_until(lambda: first not in handler.replies)
    assert enabled == [False]
    assert not dialog.treeWidgetTableOfContents.isEnabled()
    assert messages(dialog) == ['Second']
    manager.replies[1].succeed()
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert messages(dialog) == []


def test_the_focused_widget_gets_its_focus_back(
    dialog: Dialog, manager: FakeManager
) -> None:
    dialog.display_dialog()
    dialog.lineEditSearch.setFocus()
    wait_until(dialog.lineEditSearch.hasFocus)
    dialog.request_handler.get(QNetworkRequest(), 'Fetching')
    assert not dialog.lineEditSearch.hasFocus()
    manager.replies[0].succeed()
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert dialog.lineEditSearch.hasFocus()


def test_a_closed_progress_message_is_shown_again(
    dialog: Dialog, manager: FakeManager
) -> None:
    handler = dialog.request_handler
    handler.get(QNetworkRequest(), 'First')
    [first] = manager.replies
    first.finished.connect(lambda: handler.get(QNetworkRequest(), 'Second'))
    # The close button of the message bar
    dialog.messageBar.popWidget()
    delete_later_objects()
    assert messages(dialog) == []
    first.succeed()
    wait_until(lambda: first not in handler.replies)
    assert messages(dialog) == ['Second']
    manager.replies[1].succeed()
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert messages(dialog) == []


def test_display_dialog_brings_the_dialog_back(
    dialog: Dialog, main_window: QWidget
) -> None:
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    # Clicking the QGIS window
    main_window.activateWindow()
    wait_until(main_window.isActiveWindow)
    assert not dialog.isActiveWindow()
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)


def test_display_dialog_restores_a_minimized_dialog(dialog: Dialog) -> None:
    dialog.display_dialog()
    dialog.showMinimized()
    wait_until(dialog.isMinimized)
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    assert dialog.isVisible()
    assert not dialog.isMinimized()


@pytest.mark.parametrize('matrix_factory', [None, long_values, many_options])
def test_a_reopened_dialog_fits_a_small_screen(
    dialog: Dialog,
    monkeypatch: pytest.MonkeyPatch,
    matrix_factory: c.Callable[[], Matrix] | None,
) -> None:
    screen = SimpleNamespace(availableGeometry=lambda: MACBOOK_AIR)
    monkeypatch.setattr(dialog, 'screen', lambda: screen)
    if matrix_factory is not None:
        prepare_tutorial_work(dialog, matrix_factory())
    # The size of the window frame is known once the dialog was shown
    dialog.display_dialog()
    dialog.close()
    # As if it was left on a larger screen
    dialog.move(1300, 700)
    dialog.resize(2000, 1200)
    dialog.display_dialog()
    assert MACBOOK_AIR.contains(dialog.frameGeometry())


def test_an_open_dialog_keeps_the_size_it_was_given(dialog: Dialog) -> None:
    dialog.display_dialog()
    # Larger than the screen, e.g. stretched over two
    size = QSize(2000, 1200)
    dialog.resize(size)
    wait_until(lambda: dialog.size() == size)
    dialog.display_dialog()
    assert dialog.size() == size


def test_the_dialog_reopens_with_its_size_and_splitters(
    dialog: Dialog, new_dialog: c.Callable[[], Dialog]
) -> None:
    dialog.display_dialog()
    # Smaller than the default size and the screen
    size = QSize(700, 500)
    dialog.resize(size)
    wait_until(lambda: dialog.size() == size)
    splitters = [dialog.splitterCatalogue, dialog.splitterMatrix]
    default = [splitter.sizes() for splitter in splitters]
    for splitter, (first, second) in zip(splitters, default):
        splitter.setSizes([first + 40, second - 40])
    sizes = [splitter.sizes() for splitter in splitters]
    assert sizes != default
    dialog.close()
    reopened = new_dialog()
    reopened.display_dialog()
    assert reopened.size() == size
    assert [
        reopened.splitterCatalogue.sizes(),
        reopened.splitterMatrix.sizes(),
    ] == sizes


def test_an_unreadable_splitter_state_is_ignored(
    dialog: Dialog, new_dialog: c.Callable[[], Dialog]
) -> None:
    settings = QgsSettings()
    for setting in (Setting.CATALOGUE_SPLITTER, Setting.MATRIX_SPLITTER):
        settings.setValue(setting.value, QByteArray(b'not a state'))
    restored = new_dialog()
    for opened in (dialog, restored):
        opened.display_dialog()
    assert restored.size() == dialog.size()
    assert (
        restored.splitterCatalogue.sizes() == dialog.splitterCatalogue.sizes()
    )
    assert restored.splitterMatrix.sizes() == dialog.splitterMatrix.sizes()


@pytest.mark.parametrize(
    'method', ['display_join_report', 'display_service_information']
)
def test_closing_a_child_dialog_reactivates_the_dialog(
    dialog: Dialog, method: str
) -> None:
    dialog.display_dialog()
    wait_until(dialog.isActiveWindow)
    titles = reject_next_modal_dialog()
    getattr(dialog, method)()
    assert titles
    wait_until(dialog.isActiveWindow)


def test_messages_go_to_the_open_dialog(
    dialog: Dialog, qgis_iface: QgisInterface
) -> None:
    dialog.display_dialog()
    assert dialog.get_message_bar() is dialog.messageBar
    dialog.close()
    assert dialog.get_message_bar() is qgis_iface.messageBar()


def test_the_toolbar_icon_opens_the_dialog_over_qgis(
    plugin: QTempo, main_window: QWidget
) -> None:
    plugin.run()
    dialog = plugin.dialog
    assert dialog.parent() is main_window
    wait_until(dialog.isActiveWindow)
    assert messages(dialog) == ['Fetching the table of contents']
    assert not dialog.treeWidgetTableOfContents.isEnabled()


def test_the_toolbar_icon_fetches_the_table_of_contents_once(
    plugin: QTempo, main_window: QWidget
) -> None:
    plugin.run()
    plugin.run()
    [reply] = requests(plugin)
    reply.succeed(table_of_contents())
    dialog = plugin.dialog
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert dialog.treeWidgetTableOfContents.topLevelItemCount() == 1
    main_window.activateWindow()
    wait_until(main_window.isActiveWindow)
    plugin.run()
    assert len(requests(plugin)) == 1
    wait_until(dialog.isActiveWindow)


def test_a_failed_table_of_contents_is_fetched_again(
    plugin: QTempo, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[BaseException] = []
    # The error is raised again after it is shown
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args[1]))
    plugin.run()
    requests(plugin)[0].fail()
    dialog = plugin.dialog
    wait_until(dialog.treeWidgetTableOfContents.isEnabled)
    assert [type(error) for error in errors] == [RequestError]
    assert [item.title() for item in dialog.messageBar.items()] == ['Error']
    plugin.run()
    assert len(requests(plugin)) == 2


def test_unload_deletes_the_dialog(plugin: QTempo) -> None:
    plugin.run()
    dialog = plugin.dialog
    plugin.unload()
    delete_later_objects()
    assert sip.isdeleted(dialog)
