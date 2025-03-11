from __future__ import annotations

import json
import string
import typing as t

from qgis.PyQt.QtCore import (
    QObject,
    QUrl,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ._typing import Node

if t.TYPE_CHECKING:
    from .qtempo import RequestHandler


def sort_nodes(nodes: list[Node]) -> None:
    nodes.sort(key=lambda node: int(node['context']['code']))


def add_completer_to_combo_box(combobox: QComboBox) -> None:
    combobox.setEditable(True)
    combobox.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combobox.completer().setCompletionMode(
        QCompleter.CompletionMode.PopupCompletion
    )
    combobox.setCurrentIndex(-1)


def delete_layout_items(layout: QLayout | None) -> None:
    if layout is not None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                delete_layout_items(item.layout())


def parse_node_name(name: str) -> str:
    if '<a href' in name:
        name = name[: name.index('<a href')]
    return fix_trailing_whitespace(name)


def fix_trailing_whitespace(str_: str) -> str:
    return str_.rstrip(string.whitespace)


T = t.TypeVar('T', bound=QObject)


def get_children(parent: QWidget | QLayout, search_for: t.Type[T]) -> list[T]:
    children = []
    for child in parent.children():
        if isinstance(child, search_for):
            children.append(child)
    return children


def get_widgets(parent: QLayout, search_for: t.Type[T]) -> list[T]:
    widgets = []
    for i in range(parent.count()):
        item = parent.itemAt(i).widget()
        if item is not None and isinstance(item, search_for):
            widgets.append(item)
    return widgets


def get_list_widget_items(list_widget: QListWidget) -> list[QListWidgetItem]:
    return t.cast(
        list[QListWidgetItem],
        [list_widget.item(i) for i in range(list_widget.count())],
    )


def update_node_ancestors_and_children(
    handler: RequestHandler, node: Node, url: str, text: str
) -> QNetworkReply:
    """Adds the ancestors and the children to a node."""
    request = QNetworkRequest(QUrl(url))
    reply = handler.get(request, text)

    def update_node():
        data = reply.readAll().data()
        node.update(json.loads(data))

    reply.finished.connect(update_node)
    return reply


def get_tree_widget_items(
    tree_widget: QTreeWidget | QTreeWidgetItem,
) -> list[QTreeWidgetItem]:
    if isinstance(tree_widget, QTreeWidget):
        return t.cast(
            list[QTreeWidgetItem],
            [
                tree_widget.topLevelItem(i)
                for i in range(tree_widget.topLevelItemCount())
            ],
        )
    elif isinstance(tree_widget, QTreeWidgetItem):
        return t.cast(
            list[QTreeWidgetItem],
            [tree_widget.child(i) for i in range(tree_widget.childCount())],
        )
    raise ValueError(f'Did not expect {tree_widget!r}')


def get_tree_widget_items_r(
    tree_widget: QTreeWidget | QTreeWidgetItem,
) -> list[QTreeWidgetItem]:
    items = []
    if isinstance(tree_widget, QTreeWidgetItem):
        items.append(tree_widget)
    children = get_tree_widget_items(tree_widget)
    if children:
        for child in children:
            items.extend(get_tree_widget_items_r(child))
    return items
