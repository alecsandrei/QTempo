from __future__ import annotations

import collections.abc as c
import json
import sys
import typing as t
from types import SimpleNamespace

import pytest
from qgis.gui import QgisInterface
from qgis.PyQt import sip
from qgis.PyQt.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QObject,
    QTimer,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import QApplication, QDialog, QWidget

from qtempo.exceptions import RequestError
from qtempo.qtempo import Dialog, QTempo

from .helpers import wait_until


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


def messages(dialog: Dialog) -> list[str]:
    return [item.text() for item in dialog.messageBar.items()]


def requests(plugin: QTempo) -> list[FakeReply]:
    return t.cast(FakeManager, plugin.network_manager).replies


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
def dialog(
    qgis_iface: QgisInterface, main_window: QWidget, manager: FakeManager
) -> c.Iterator[Dialog]:
    qtempo = SimpleNamespace(network_manager=manager, iface=qgis_iface)
    dialog = Dialog(qtempo, main_window)
    yield dialog
    # The QGIS window of the session would keep it
    sip.delete(dialog)


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
    assert [item.title() for item in dialog.messageBar.items()] == [
        'RequestError'
    ]
    plugin.run()
    assert len(requests(plugin)) == 2


def test_unload_deletes_the_dialog(plugin: QTempo) -> None:
    plugin.run()
    dialog = plugin.dialog
    plugin.unload()
    delete_later_objects()
    assert sip.isdeleted(dialog)
