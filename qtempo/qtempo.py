from __future__ import annotations

import collections.abc as c
import itertools
import json
import textwrap
import time
import typing as t
from dataclasses import dataclass, field
from urllib.parse import urljoin

import processing
from qgis.core import QgsNetworkAccessManager, QgsProject, QgsVectorLayer
from qgis.gui import QgisInterface, QgsCollapsibleGroupBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QSignalBlocker,
    Qt,
    QThread,
    QUrl,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableView,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import services
from ._typing import (
    Choice,
    Context,
    Dimension,
    Language,
    LeafNode,
    Node,
    RequestBody,
)
from .enums import (
    URL,
    Asset,
    QListWidgetItemRole,
    QTreeWidgetItemRole,
    Tabs,
    WidgetProperty,
)
from .exceptions import RequestError
from .matrix import Field, Matrix
from .utils import (
    add_completer_to_combo_box,
    delete_layout_items,
    fix_trailing_whitespace,
    get_children,
    get_list_widget_items,
    get_tree_widget_items,
    get_tree_widget_items_r,
    get_widgets,
    parse_node_name,
    update_node_ancestors_and_children,
)
from .widgets import LoadingDialog, QListWidgetAlwaysSelected

UI_Dialog = uic.loadUiType(Asset.DIALOG.value.as_posix())[0]


class Dialog(QDialog, UI_Dialog):  # type: ignore
    def __init__(self, qtempo):
        super().__init__()
        self.setupUi(self)
        self.qtempo = t.cast(QTempo, qtempo)
        self.request_handler = RequestHandler(self.qtempo.network_manager, self)

        # signals
        self.treeWidgetTableOfContents.itemSelectionChanged.connect(
            self.fill_matrices
        )
        self.treeWidgetTableOfContents.itemSelectionChanged.connect(
            self.reset_tabs
        )
        self.listWidgetMatrices.itemSelectionChanged.connect(self.add_queries)
        self.listWidgetMatrices.itemSelectionChanged.connect(self.reset_tabs)
        self.pushButtonRequestData.clicked.connect(self.fetch_data)
        self.lineEditSearch.textChanged.connect(self.filter_toc)
        self.pushButtonServiceInformation.clicked.connect(
            self.display_service_information
        )
        self.comboBoxGroupByField.currentIndexChanged.connect(
            self.add_table_options
        )
        self.pushButtonAddTableLayer.clicked.connect(self.add_table_layer)
        self.pushButtonAddVectorLayer.clicked.connect(self.add_vector_layer)
        self.checkBoxEnglish.clicked.connect(self.handle_changed_language)
        self.checkBoxRomanian.clicked.connect(self.handle_changed_language)

        # style
        self.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, False)
        self.treeWidgetTableOfContents.setHeaderLabel('')
        self.add_services()

    def _cast_types(self):
        # no need to call this function
        self.pushButtonRequestData = t.cast(
            QPushButton, self.pushButtonRequestData
        )
        self.treeWidgetTableOfContents = t.cast(
            QTreeWidget, self.treeWidgetTableOfContents
        )
        self.listWidgetMatrices = t.cast(QListWidget, self.listWidgetMatrices)
        self.tabWidgetMatrix = t.cast(QTabWidget, self.tabWidgetMatrix)
        self.scrollAreaQuery = t.cast(QFrame, self.scrollAreaQuery)
        self.tableViewMatrix = t.cast(QTableView, self.tableViewMatrix)
        self.frameQuery = t.cast(QFrame, self.frameQuery)
        self.lineEditSearch = t.cast(QLineEdit, self.lineEditSearch)
        self.mGroupBoxServices = t.cast(
            QgsCollapsibleGroupBox, self.mGroupBoxServices
        )
        self.mGroupBoxTableSubset = t.cast(
            QgsCollapsibleGroupBox, self.mGroupBoxServices
        )
        self.pushButtonServiceInformation = t.cast(
            QPushButton, self.pushButtonServiceInformation
        )
        self.listWidgetServices = t.cast(QListWidget, self.listWidgetServices)
        self.comboBoxGroupByField = t.cast(QComboBox, self.comboBoxGroupByField)
        self.frameTableOptions = t.cast(QFrame, self.frameTableOptions)
        self.pushButtonAddTableLayer = t.cast(
            QPushButton, self.pushButtonAddTableLayer
        )
        self.pushButtonAddVectorLayer = t.cast(
            QPushButton, self.pushButtonAddVectorLayer
        )
        self.checkBoxEnglish = t.cast(QCheckBox, self.checkBoxEnglish)
        self.checkBoxRomanian = t.cast(QCheckBox, self.checkBoxRomanian)

    def display_dialog(self) -> None:
        self.show()
        self.exec()

    def fill_table_of_contents(self) -> None:
        nodes = t.cast(
            list[Node],
            json.loads(self.table_of_contents_reply.readAll().data()),
        )
        if self.treeWidgetTableOfContents.topLevelItemCount():
            self.treeWidgetTableOfContents.clear()

        items: dict[str, QTreeWidgetItem] = {}
        for node in nodes:
            parent_item = items.get(node['parentCode'], None)
            item = QTreeWidgetItem(
                parent_item
                if parent_item is not None
                else self.treeWidgetTableOfContents
            )
            items[node['context']['code']] = item
            parsed_node_name = parse_node_name(node['context']['name'])
            wrapped_node_name = textwrap.fill(parsed_node_name, width=40)
            item.setData(0, QTreeWidgetItemRole.NODE.value, node)
            item.setText(0, parsed_node_name.title())
            item.setToolTip(0, wrapped_node_name.lower())
            if parent_item is None:
                self.treeWidgetTableOfContents.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
        self.display_dialog()

    def preprocess_url(self, url: str) -> str:
        lang = self.get_language()
        return url if lang == 'ro' else urljoin(url, f'?lang={lang}')

    def fetch_table_of_contents(self) -> QNetworkReply:
        text = 'Fetching the table of contents'
        request = QNetworkRequest(QUrl(self.preprocess_url(URL.TOC.value)))
        self.table_of_contents_reply = self.qtempo.request_handler.get(
            request, text
        )
        if self.treeWidgetTableOfContents.topLevelItemCount():
            self.table_of_contents_reply.finished.connect(self.switch_language)
        else:
            self.table_of_contents_reply.finished.connect(
                self.fill_table_of_contents
            )
        return self.table_of_contents_reply

    def get_language(self) -> Language:
        if self.checkBoxEnglish.checkState() == Qt.CheckState.Checked:
            return 'en'
        elif self.checkBoxRomanian.checkState() == Qt.CheckState.Checked:
            return 'ro'
        raise ValueError('unreachable')

    def switch_language_table_of_contents(self):
        nodes = t.cast(
            list[Node],
            json.loads(self.table_of_contents_reply.readAll().data()),
        )

        def find_node(item: QTreeWidgetItem) -> Node:
            item_node = t.cast(
                Node, item.data(0, QTreeWidgetItemRole.NODE.value)
            )
            for node in nodes:
                if node['context']['code'] == item_node['context']['code']:
                    return node
            raise Exception('unreachable')

        items = get_tree_widget_items_r(self.treeWidgetTableOfContents)
        for item in items:
            node = find_node(item)
            parsed_node_name = parse_node_name(node['context']['name'])
            wrapped_node_name = textwrap.fill(parsed_node_name, width=40)
            item.setData(0, QTreeWidgetItemRole.NODE.value, node)
            item.setText(0, parsed_node_name.title())
            item.setToolTip(0, wrapped_node_name.lower())

    def switch_language_matrices_list(self) -> QNetworkReply:
        items = get_list_widget_items(self.listWidgetMatrices)
        node = t.cast(
            Node, items[0].data(QListWidgetItemRole.PARENT_NODE.value)
        )
        reply = update_node_ancestors_and_children(
            self.request_handler,
            node,
            self.preprocess_url(
                URL.CONTEXT.value.format(code=node['context']['code'])
            ),
            f'Loading matrices for {parse_node_name(node["context"]["name"])}',
        )

        def find_child(context: Context) -> Context:
            assert 'children' in node
            for child in node['children']:
                if child['code'] == context['code']:
                    return child
            raise ValueError('unreachable')

        def switch_matrices_language():
            assert 'children' in node
            for item in items:
                context = item.data(QListWidgetItemRole.CONTEXT.value)
                child = find_child(context)
                item.setData(QListWidgetItemRole.CONTEXT.value, child)
                item.setData(QListWidgetItemRole.PARENT_NODE.value, node)
                item.setText(
                    f'[{child["code"]}] {parse_node_name(child["name"])}'
                )

        reply.finished.connect(switch_matrices_language)
        return reply

    def switch_language(self):
        self.switch_language_table_of_contents()
        if self.listWidgetMatrices.count():
            switch_language_task = self.switch_language_matrices_list()
            if self.listWidgetMatrices.selectedItems():
                switch_language_task.finished.connect(
                    self.switch_language_queries
                )

    def handle_changed_language(self):
        language = 'romanian' if self.get_language() == 'ro' else 'english'
        self.disable_gui()
        loading_dialog, loading_label = start_loading_dialog_loop(
            self, f'Fetching table of contents in the {language} language.'
        )
        reply = self.fetch_table_of_contents()
        reply.finished.connect(loading_dialog.close)
        reply.finished.connect(loading_label.requestInterruption)
        reply.finished.connect(self.enable_gui)

    def filter_toc(
        self,
        search_string: str,
        tree_widget_item: QTreeWidgetItem | None = None,
    ) -> None:
        search_string = search_string.lower()
        items = get_tree_widget_items(
            tree_widget_item
            if tree_widget_item is not None
            else self.treeWidgetTableOfContents
        )

        for item in items:
            assert item is not None
            if item.childCount():
                self.filter_toc(search_string, item)
                item.setHidden(
                    all(item.isHidden() for item in get_tree_widget_items(item))
                )
            else:
                item.setHidden(search_string not in item.text(0).lower())
        if tree_widget_item is None:
            if search_string:
                self.treeWidgetTableOfContents.expandAll()
            else:
                self.treeWidgetTableOfContents.collapseAll()

    def reset_tabs(self) -> None:
        if self.frameTableOptions.children():
            self.clear_table_options()
        self.clear_table()
        self.pushButtonAddTableLayer.setEnabled(False)
        self.pushButtonAddVectorLayer.setEnabled(False)
        self.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, False)

    def get_selected_dataset(self) -> QTreeWidgetItem | None:
        selected_item = self.treeWidgetTableOfContents.selectedItems()[0]
        if selected_item.childCount():  # there should be a better check I guess
            return None
        return selected_item

    def fill_matrices(self) -> None:
        selected_dataset = self.get_selected_dataset()
        if selected_dataset is None:
            return None

        if self.listWidgetMatrices.selectedItems():
            delete_layout_items(t.cast(QLayout, self.frameQuery.layout()))
        if self.listWidgetMatrices.count():
            with QSignalBlocker(self.listWidgetMatrices):
                self.listWidgetMatrices.clear()
        node = t.cast(
            Node, selected_dataset.data(0, QTreeWidgetItemRole.NODE.value)
        )
        reply = update_node_ancestors_and_children(
            self.request_handler,
            node,
            self.preprocess_url(
                URL.CONTEXT.value.format(code=node['context']['code'])
            ),
            f'Loading matrices for {selected_dataset.text(0)!r}',
        )

        def add_items():
            assert 'children' in node
            for child in node['children']:
                if child['childrenUrl'] != 'matrix':
                    continue
                item = QListWidgetItem(self.listWidgetMatrices)
                item.setData(QListWidgetItemRole.CONTEXT.value, child)
                item.setData(QListWidgetItemRole.PARENT_NODE.value, node)
                item.setText(
                    f'[{child["code"]}] {parse_node_name(child["name"])}'
                )
                self.listWidgetMatrices.addItem(item)

        reply.finished.connect(add_items)

    def get_matrix_code(self) -> str | None:
        selected_items = self.listWidgetMatrices.selectedItems()
        assert selected_items
        return t.cast(
            Context, selected_items[0].data(QListWidgetItemRole.CONTEXT.value)
        )['code']

    def get_leaf_node(self) -> QNetworkReply | None:
        dataset_code = self.get_matrix_code()

        request = QNetworkRequest(
            QUrl(
                self.preprocess_url(URL.DATASET.value.format(code=dataset_code))
            )
        )
        return self.request_handler.get(
            request, f'Fetching information for {dataset_code!r}'
        )

    def clear_table(self) -> None:
        if self.tableViewMatrix.model() is not None:
            self.tableViewMatrix.setModel(None)

    def switch_language_queries(self):
        reply = self.get_leaf_node()
        assert reply is not None

        def find_dimension(
            dimensions: list[Dimension], dimension_code: int
        ) -> Dimension:
            for dimension in dimensions:
                if dimension['dimCode'] == dimension_code:
                    return dimension
            raise ValueError('unreachable')

        def find_choice(choices: list[Choice], nom_item_id: int) -> Choice:
            for choice in choices:
                if choice['nomItemId'] == nom_item_id:
                    return choice
            raise ValueError('unreachable')

        def switch_language():
            leaf_node = t.cast(LeafNode, json.loads(reply.readAll().data()))
            self.add_leaf_node_to_list_widget_item(leaf_node)
            layouts = get_children(self.frameQuery.layout(), QVBoxLayout)
            for layout in layouts:
                list_widget = get_widgets(layout, QListWidgetAlwaysSelected)[0]
                label = get_widgets(layout, QLabel)[0]
                dimension = find_dimension(
                    leaf_node['dimensionsMap'],
                    t.cast(
                        Dimension,
                        layout.property(WidgetProperty.DIMENSION.value),
                    )['dimCode'],
                )
                label.setText(fix_trailing_whitespace(dimension['label']))
                for item in get_list_widget_items(list_widget):
                    choice = find_choice(
                        dimension['options'],
                        t.cast(
                            Choice, item.data(QListWidgetItemRole.CHOICE.value)
                        )['nomItemId'],
                    )
                    item.setData(QListWidgetItemRole.CHOICE.value, choice)
                    item.setText(fix_trailing_whitespace(choice['label']))
                    item.setToolTip(item.text())
            if self.get_model_matrix() is not None:
                self.fetch_data()

        reply.finished.connect(switch_language)

    def add_leaf_node_to_list_widget_item(self, leaf_node: LeafNode) -> None:
        current_item = self.listWidgetMatrices.currentItem()
        if current_item is not None:
            current_item.setData(
                QListWidgetItemRole.LEAF_NODE.value,
                leaf_node,
            )

    def add_queries(self) -> None | QNetworkReply:
        self.tabWidgetMatrix.setCurrentIndex(Tabs.QUERY.value)
        self.clear_table()
        self.disable_gui()
        reply = self.get_leaf_node()

        def add_dimensions() -> None:
            assert reply is not None
            leaf_node = t.cast(LeafNode, json.loads(reply.readAll().data()))
            self.add_leaf_node_to_list_widget_item(leaf_node)
            if leaf_node is not None:
                self.add_dimensions_to_frame_query(leaf_node['dimensionsMap'])

        if reply is not None:
            reply.finished.connect(add_dimensions)
            reply.finished.connect(self.enable_gui)
            return reply
        else:
            self.enable_gui()
            return None

    def set_query_children_hidden(self) -> None:
        parent_widget = t.cast(QListWidget, self.sender())
        frame_children = get_children(self.frameQuery, QListWidget)
        child_widget = frame_children[frame_children.index(parent_widget) + 1]
        selected_parent_choices = []
        for item in parent_widget.selectedItems():
            selected_parent_choices.append(
                t.cast(Choice, item.data(QListWidgetItemRole.CHOICE.value))[
                    'nomItemId'
                ]
            )
        for item in get_list_widget_items(child_widget):
            if item is None:
                continue
            choice = t.cast(Choice, item.data(QListWidgetItemRole.CHOICE.value))
            bool_ = choice['parentId'] in selected_parent_choices
            item.setHidden(not bool_)
            if bool_ is False and item.isSelected():
                item.setSelected(False)

    def add_dimensions_to_frame_query(
        self, dimensions: c.Iterable[Dimension]
    ) -> None:
        layout = self.frameQuery.layout()
        if layout is not None:
            delete_layout_items(layout)
        else:
            layout = QHBoxLayout(self.frameQuery)
            self.frameQuery.setLayout(layout)
        for i, dimension in enumerate(dimensions):
            layout = QVBoxLayout()
            layout.setProperty(WidgetProperty.DIMENSION.value, dimension)
            label = QLabel(
                text=fix_trailing_whitespace(dimension['label']),
                parent=self.frameQuery,
            )
            list_widget = QListWidgetAlwaysSelected(self.frameQuery)

            layout.addWidget(label)
            layout.addWidget(list_widget)
            t.cast(QHBoxLayout, self.frameQuery.layout()).addLayout(layout)
            has_parent = False
            for choice in dimension['options']:
                item = QListWidgetItem(list_widget)
                item.setData(QListWidgetItemRole.CHOICE.value, choice)
                item.setText(fix_trailing_whitespace(choice['label']))
                if choice['parentId'] is not None:
                    item.setHidden(True)
                    has_parent = True
                item.setToolTip(item.text())
            if has_parent:
                # If it has a parent, the parent is always the previous dimension
                get_children(self.frameQuery, QListWidget)[
                    -2
                ].itemSelectionChanged.connect(self.set_query_children_hidden)
                has_parent = False
            list_widget.setMinimumWidth(list_widget.width() + 5)

    def construct_query(self) -> str:
        list_widgets = get_children(self.frameQuery, QListWidget)
        query: list[str] = []
        for list_widget in list_widgets:
            choices = t.cast(
                list[Choice],
                [
                    selected_item.data(QListWidgetItemRole.CHOICE.value)
                    for selected_item in list_widget.selectedItems()
                ],
            )
            query.append(
                ','.join([str(choice['nomItemId']) for choice in choices])
            )
        return ':'.join(query)

    def construct_body(self) -> RequestBody | None:
        current_item = self.listWidgetMatrices.currentItem()
        assert current_item
        leaf_node = t.cast(
            LeafNode, current_item.data(QListWidgetItemRole.LEAF_NODE.value)
        )
        return t.cast(
            RequestBody,
            {
                'language': self.get_language(),
                'encQuery': self.construct_query(),
                'matCode': self.get_matrix_code(),
                **leaf_node['details'],
            },
        )

    def add_fields_to_group_by_combo_box(self) -> None:
        model = self.get_model_matrix()
        assert model is not None
        fields = model.fields
        with QSignalBlocker(self.comboBoxGroupByField):
            if self.comboBoxGroupByField.count():
                self.comboBoxGroupByField.clear()
            self.comboBoxGroupByField.addItems(
                [
                    field_.name
                    for field_ in fields
                    if not field_.is_geo and not field_.is_value
                ]
            )
        self.comboBoxGroupByField.setCurrentIndex(0)
        self.comboBoxGroupByField.currentIndexChanged.emit(0)

    def get_model_matrix(self) -> Matrix | None:
        model = self.tableViewMatrix.model()
        if model is None:
            return None
        return t.cast(MatrixModel, model)._matrix

    def add_table_options(self) -> None:
        matrix = self.get_model_matrix()
        self.pushButtonAddVectorLayer.setEnabled(True)
        assert matrix is not None
        group_by_field = self.comboBoxGroupByField.currentText()
        layout = self.frameTableOptions.layout()
        if layout is not None:
            delete_layout_items(layout)
        else:
            layout = QVBoxLayout(self.frameTableOptions)
            self.frameTableOptions.setLayout(layout)
        for field_, values in matrix.items():
            if (
                field_.is_geo
                or field_.is_value
                or field_.name == group_by_field
            ):
                continue
            label = QLabel(
                textwrap.fill(field_.name, width=40), self.frameTableOptions
            )
            combo_box = QComboBox(self.frameTableOptions)
            add_completer_to_combo_box(combo_box)
            combo_box.addItems(sorted(set(values)))
            combo_box.setProperty(WidgetProperty.FIELD.value, field_)
            if combo_box.count() == 1:
                combo_box.setCurrentIndex(0)
            layout.addWidget(label)
            layout.addWidget(combo_box)

    def handle_map_tab(self) -> None:
        current_item = self.listWidgetMatrices.currentItem()
        assert current_item
        data = t.cast(
            Matrix, current_item.data(QListWidgetItemRole.MATRIX.value)
        )
        self.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, data.has_siruta)

    def fetch_data(self) -> QNetworkReply | None:
        body = self.construct_body()
        if body is None:
            return None

        request = QNetworkRequest(QUrl(self.preprocess_url(URL.TABLE.value)))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json'
        )
        self.disable_gui()
        reply = self.request_handler.post(
            request,
            json.dumps(body).encode('UTF-8'),
            f'Fetching data for {self.get_matrix_code()}',
        )

        def set_matrix():
            current_item = self.listWidgetMatrices.currentItem()
            assert current_item
            current_item.setData(
                QListWidgetItemRole.MATRIX.value,
                Matrix.from_response(reply.readAll().data(), body),
            )

        reply.finished.connect(set_matrix)
        reply.finished.connect(self.handle_map_tab)
        reply.finished.connect(self.update_table)
        reply.finished.connect(
            lambda: self.pushButtonAddTableLayer.setEnabled(True)
        )
        reply.finished.connect(self.enable_gui)
        return reply

    def clear_table_options(self) -> None:
        delete_layout_items(self.frameTableOptions.layout())
        with QSignalBlocker(self.comboBoxGroupByField):
            self.comboBoxGroupByField.clear()

    def update_table(self) -> None:
        current_item = self.listWidgetMatrices.currentItem()
        if current_item is None:
            return None
        data = t.cast(
            Matrix, current_item.data(QListWidgetItemRole.MATRIX.value)
        )
        model = MatrixModel(data, self.tabWidgetMatrix)
        self.tableViewMatrix.setModel(model)
        self.tableViewMatrix.resizeColumnsToContents()
        self.tabWidgetMatrix.setCurrentIndex(Tabs.TABLE.value)
        self.clear_table_options()
        self.add_fields_to_group_by_combo_box()

    def display_service_information(self) -> None:
        if not (items := self.listWidgetServices.selectedItems()):
            return None
        service = t.cast(
            services.Service, items[0].data(QListWidgetItemRole.SERVICE.value)
        )
        information = QLabel(f"""
            name: {service.full_name}<br>
            url: <a href=\"{service.url}\">{service.url}</a>
            """)
        information.setTextFormat(Qt.RichText)
        information.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        information.setOpenExternalLinks(True)
        dialog = QDialog(self)
        layout = QVBoxLayout()
        layout.addWidget(information)
        dialog.setWindowTitle(service.short_name)
        dialog.setLayout(layout)
        dialog.exec_()

    def add_services(self) -> None:
        self.mGroupBoxServices.setLayout(QVBoxLayout())

        for service in services.__dict__.values():
            if (
                service is services.Service
                or not isinstance(service, type)
                or not issubclass(service, services.Service)
            ):
                continue
            item = QListWidgetItem(self.listWidgetServices)
            # NOTE: look more into this, mypy error
            class_ = service()  # type: ignore
            item.setText(class_.full_name)
            item.setData(QListWidgetItemRole.SERVICE.value, class_)
            self.listWidgetServices.addItem(item)
            if class_.is_default:
                item.setSelected(True)

    def get_table_options(self) -> dict[Field, str]:
        options_combo_boxes = get_children(self.frameTableOptions, QComboBox)
        return {
            combo_box.property(
                WidgetProperty.FIELD.value
            ): combo_box.currentText()
            for combo_box in options_combo_boxes
        }

    def get_grouped_matrix(self) -> Matrix:
        matrix = self.get_model_matrix()
        group_by_field = self.comboBoxGroupByField.currentText()
        assert matrix is not None
        return matrix.group_by(
            matrix.fields.get(group_by_field), self.get_table_options()
        )

    def get_siruta_field_name(self) -> str:
        return 'SIRUTA'

    def add_vector_layer(self) -> None:
        # NOTE: This function throws the a warning:
        # Warning: QObject::setParent: Cannot set parent
        # It is related to the
        handler = ServiceHandler(self)
        assert handler.service is not None

        self.disable_gui()
        loading_dialog, loading_label = start_loading_dialog_loop(
            self,
            f'Fetching data from service {handler.service.short_name}',
        )
        handler.error_ocurred.connect(self.qtempo._handle_error_signal)
        handler.finished.connect(loading_dialog.close)
        handler.finished.connect(loading_label.requestInterruption)
        handler.finished.connect(self.enable_gui)
        handler.start()

    def add_table_layer(self) -> None:
        model = self.get_model_matrix()
        if model is None:
            return None
        table_layer = model.as_table(self.get_matrix_code())
        instance = QgsProject().instance()
        assert instance
        instance.addMapLayer(table_layer)

    def get_selected_service(self) -> services.Service | None:
        if not (items := self.listWidgetServices.selectedItems()):
            self.listWidgetServices.setCurrentRow(0)
            return self.get_selected_service()
        return t.cast(
            services.Service, items[0].data(QListWidgetItemRole.SERVICE.value)
        )

    def set_gui_state(self, state: bool) -> None:
        for obj in self.children():
            if isinstance(obj, QWidget):
                obj.setEnabled(state)

    def enable_gui(self) -> None:
        self.set_gui_state(True)

    def disable_gui(self) -> None:
        self.set_gui_state(False)


class ServiceHandler(QThread):
    error_ocurred = pyqtSignal(Exception)

    def __init__(self, dialog: Dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.service = self.dialog.get_selected_service()
        assert self.service is not None

    def _run(self):
        grouped_matrix = self.dialog.get_grouped_matrix()
        matrix = grouped_matrix.as_table(
            self.dialog.get_matrix_code(), self.dialog.get_siruta_field_name()
        )
        assert grouped_matrix.siruta is not None
        assert self.service is not None

        assert self.service is not None

        service_layer = self.service.get_layer(
            [siruta for siruta in grouped_matrix.siruta if siruta is not None]
        )
        processing_result = t.cast(
            QgsVectorLayer,
            processing.run(
                'native:joinattributestable',
                {
                    'INPUT': service_layer,
                    'FIELD': self.service.siruta_field,
                    'INPUT_2': matrix,
                    'FIELD_2': self.dialog.get_siruta_field_name(),
                    'FIELDS_TO_COPY': [],
                    'METHOD': 1,
                    'DISCARD_NONMATCHING': True,
                    'PREFIX': '',
                    'OUTPUT': 'TEMPORARY_OUTPUT',
                },
            )['OUTPUT'],
        )

        processing_result.setName(
            f'{self.service.short_name} [{self.dialog.get_matrix_code()}]'
        )
        instance = QgsProject().instance()
        if instance is not None:
            instance.addMapLayer(processing_result)
            canvas = self.dialog.qtempo.iface.mapCanvas()
            assert canvas
            canvas.setExtent(processing_result.extent())

    def run(self):
        assert self.service
        try:
            self._run()
        except Exception as e:
            self.error_ocurred.emit(e)


class MatrixModel(QAbstractTableModel):
    def __init__(self, matrix: Matrix, parent: QObject | None = None):
        super().__init__(parent)
        self._matrix = matrix

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return len(self._matrix.data)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return len(self._matrix.fields)

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> t.Any | None:
        if index.isValid():
            if role == Qt.ItemDataRole.DisplayRole:
                return self._matrix.data[index.row()][index.column()]
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int | None = None
    ) -> str | None:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return self._matrix.fields[section].name
        return None


class LoadingLabel(QThread):
    update_label = pyqtSignal(str)

    def __init__(self, label: str, base: QWidget | None = None):
        self.base = base
        super().__init__(self.base)
        self.label = label

    def spin(self) -> None:
        for char in itertools.cycle('🌏🌍🌎'):
            self.update_label.emit(f'{self.label}\n{char}  ')
            time.sleep(0.5)
            if self.isInterruptionRequested():
                break

    def run(self) -> None:
        self.spin()


def start_loading_dialog_loop(
    parent: QWidget, text: str
) -> tuple[LoadingDialog, LoadingLabel]:
    loading_dialog = LoadingDialog(parent)
    loading_label = LoadingLabel(text)
    loading_label.update_label.connect(loading_dialog.update_loading_label)
    loading_label.start()
    loading_dialog.show()
    return (loading_dialog, loading_label)


@dataclass
class RequestHandler:
    manager: QgsNetworkAccessManager
    parent: Dialog
    loading_label: LoadingLabel = field(init=False)
    loading_dialog: LoadingDialog = field(init=False)

    def show_dialog(self, text: str):
        self.loading_dialog, self.loading_label = start_loading_dialog_loop(
            self.parent, text
        )

    def post(
        self, request: QNetworkRequest, data: bytes, text: str
    ) -> QNetworkReply:
        self.show_dialog(text)
        reply = self.manager.post(request, data)
        reply.finished.connect(self.close_dialog)
        return reply

    def get(self, request: QNetworkRequest, text: str) -> QNetworkReply:
        self.show_dialog(text)
        reply = self.manager.get(request)
        reply.finished.connect(self.close_dialog)
        return reply

    def close_dialog(self) -> None:
        self.loading_label.requestInterruption()
        self.loading_dialog.close()


class QTempo:
    def __init__(self, iface: QgisInterface):
        self.iface = iface

    def initGui(self) -> None:
        self.action = QAction(
            QIcon(Asset.ICON.value.as_posix()),
            'QTempo',
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('&QTempo', self.action)

        self.first_start = True

    def unload(self) -> None:
        self.iface.removePluginMenu('&QTempo', self.action)
        self.iface.removeToolBarIcon(self.action)

    def _handle_error_signal(self, error: Exception) -> None:
        message_bar = self.iface.messageBar()
        assert message_bar
        message_bar.pushCritical(error.__class__.__name__, str(error))
        raise error

    def _handle_table_of_contents_error(self):
        self.first_start = True
        self._handle_error_signal(
            RequestError(
                'Error occured when trying to fetch the table of contents. Check your internet connection and try again.'
            )
        )

    def run(self) -> None:
        if self.first_start is True:
            self.first_start = False
            self.network_manager = QgsNetworkAccessManager()
            self.dialog = Dialog(self)
            main_window = self.iface.mainWindow()
            assert main_window
            self.request_handler = RequestHandler(
                self.network_manager, main_window
            )
            self.table_of_contents_reply = self.dialog.fetch_table_of_contents()
            self.table_of_contents_reply.errorOccurred.connect(
                self._handle_table_of_contents_error
            )
        else:
            self.dialog.show()
