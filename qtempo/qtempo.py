from __future__ import annotations

import collections.abc as c
import itertools
import json
import textwrap
import typing as t
from dataclasses import dataclass, field
from functools import partial
from urllib.parse import urljoin

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsFields,
    QgsNetworkAccessManager,
    QgsProject,
    QgsSettings,
    QgsTask,
    QgsVectorLayer,
)
from qgis.gui import (
    QgisInterface,
    QgsCollapsibleGroupBox,
    QgsMessageBar,
    QgsMessageBarItem,
)
from qgis.PyQt import sip, uic
from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QObject,
    QSignalBlocker,
    Qt,
    QTimer,
    QTranslator,
    QUrl,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTableView,
    QTableWidget,
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
    Level,
    QListWidgetItemRole,
    QTreeWidgetItemRole,
    Setting,
    Tabs,
    WidgetProperty,
)
from .exceptions import RequestError
from .matrix import Field, Matrix
from .services import nuts
from .units import TerritorialUnit
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
    set_combo_box_items,
    update_node_ancestors_and_children,
)
from .widgets import (
    JoinReportDialog,
    JoinReportRow,
    QListWidgetAlwaysSelected,
)

UI_Dialog = uic.loadUiType(Asset.DIALOG.value.as_posix())[0]

# The pivot service returns no data for a dimension with more options
MAX_QUERY_OPTIONS = 1000


class Dialog(QDialog, UI_Dialog):  # type: ignore
    def __init__(self, qtempo, parent: QWidget | None = None):
        super().__init__(parent)
        self.setupUi(self)
        self.qtempo = t.cast(QTempo, qtempo)
        self.request_handler = RequestHandler(self.qtempo.network_manager, self)
        self.progress_item: QgsMessageBarItem | None = None
        self.focus_widget: QWidget | None = None
        # Deleting the dialog uninstalls it
        self.translator = QTranslator(self)
        language = self.load_language()
        self.checkBoxEnglish.setChecked(language == 'en')
        self.checkBoxRomanian.setChecked(language == 'ro')

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
        self.pushButtonAddTableLayer.clicked.connect(self.add_table_layer)
        self.pushButtonAddVectorLayer.clicked.connect(self.add_vector_layer)
        self.checkBoxEnglish.clicked.connect(self.handle_changed_language)
        self.checkBoxRomanian.clicked.connect(self.handle_changed_language)
        self.comboBoxGiscoYear.currentIndexChanged.connect(
            self.fill_nuts_combo_boxes
        )
        self.comboBoxGiscoYear.currentIndexChanged.connect(
            self.reset_join_report
        )
        self.comboBoxGiscoScale.currentIndexChanged.connect(
            self.reset_join_report
        )
        self.comboBoxGiscoProjection.currentIndexChanged.connect(
            self.reset_join_report
        )
        self.pushButtonValidateJoin.clicked.connect(self.validate_join)
        self.pushButtonJoinReport.clicked.connect(self.display_join_report)

        # tasks
        self.nuts_index_task: nuts.FetchNutsIndexTask | None = None
        self.downloader: nuts.BoundaryDownloader | None = None
        self.localities_task: FetchLocalitiesTask | None = None
        self.join_report: list[JoinReportRow] = []

        # style
        self.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, False)
        self.mGroupBoxTableOptions.setVisible(False)
        self.treeWidgetTableOfContents.setHeaderLabel('')
        self.add_services()
        self.set_language(language)

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
        self.mGroupBoxTableOptions = t.cast(
            QgsCollapsibleGroupBox, self.mGroupBoxTableOptions
        )
        self.frameTableOptions = t.cast(QFrame, self.frameTableOptions)
        self.labelTableSummary = t.cast(QLabel, self.labelTableSummary)
        self.pushButtonAddTableLayer = t.cast(
            QPushButton, self.pushButtonAddTableLayer
        )
        self.pushButtonAddVectorLayer = t.cast(
            QPushButton, self.pushButtonAddVectorLayer
        )
        self.checkBoxEnglish = t.cast(QCheckBox, self.checkBoxEnglish)
        self.checkBoxRomanian = t.cast(QCheckBox, self.checkBoxRomanian)
        self.labelMapLevels = t.cast(QLabel, self.labelMapLevels)
        self.mGroupBoxGisco = t.cast(
            QgsCollapsibleGroupBox, self.mGroupBoxGisco
        )
        self.comboBoxGiscoYear = t.cast(QComboBox, self.comboBoxGiscoYear)
        self.comboBoxGiscoScale = t.cast(QComboBox, self.comboBoxGiscoScale)
        self.comboBoxGiscoProjection = t.cast(
            QComboBox, self.comboBoxGiscoProjection
        )
        self.pushButtonValidateJoin = t.cast(
            QPushButton, self.pushButtonValidateJoin
        )
        self.pushButtonJoinReport = t.cast(
            QPushButton, self.pushButtonJoinReport
        )
        self.labelJoinStatus = t.cast(QLabel, self.labelJoinStatus)
        self.tableWidgetDownloads = t.cast(
            QTableWidget, self.tableWidgetDownloads
        )
        self.messageBar = t.cast(QgsMessageBar, self.messageBar)
        self.buttonBox = t.cast(QDialogButtonBox, self.buttonBox)

    def display_dialog(self) -> None:
        """Shows the dialog, or brings it back above QGIS if it is already
        open."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def get_message_bar(self) -> QgsMessageBar:
        """The message bar of the dialog, or the QGIS one if the dialog is
        closed."""
        if self.isVisible():
            return self.messageBar
        message_bar = self.qtempo.iface.messageBar()
        assert message_bar
        return message_bar

    def show_progress(self, text: str) -> None:
        """Shows a busy bar with the text of the running request."""
        if self.progress_item is not None and not sip.isdeleted(
            self.progress_item
        ):
            self.progress_item.setText(text)
            return None
        item = self.messageBar.createMessage(text)
        assert item is not None
        progress_bar = QProgressBar(item)
        progress_bar.setRange(0, 0)
        layout = item.layout()
        assert layout is not None
        layout.addWidget(progress_bar)
        self.messageBar.pushWidget(item, Qgis.MessageLevel.Info)
        self.progress_item = item

    def hide_progress(self) -> None:
        # The close button of the message bar deletes the item
        if self.progress_item is not None and not sip.isdeleted(
            self.progress_item
        ):
            self.messageBar.popWidget(self.progress_item)
        self.progress_item = None

    def fill_table_of_contents(self) -> None:
        reply = self.table_of_contents_reply
        if reply.error() != QNetworkReply.NetworkError.NoError:  # pyright: ignore[reportCallIssue]
            return None
        nodes = t.cast(
            list[Node],
            json.loads(reply.readAll().data()),
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

    def preprocess_url(self, url: str) -> str:
        lang = self.get_language()
        return url if lang == 'ro' else urljoin(url, f'?lang={lang}')

    def fetch_table_of_contents(self) -> QNetworkReply:
        text = self.tr('Fetching the table of contents')
        request = QNetworkRequest(QUrl(self.preprocess_url(URL.TOC.value)))
        self.table_of_contents_reply = self.request_handler.get(request, text)
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

    def load_language(self) -> Language:
        """The saved language, else Romanian if QGIS is in Romanian."""
        language = QgsSettings().value(Setting.LANGUAGE.value)
        if language in ('en', 'ro'):
            return language
        return 'ro' if QgsApplication.locale().startswith('ro') else 'en'

    def set_language(self, language: Language) -> None:
        """Translates the dialog. The TEMPO data is fetched separately."""
        QCoreApplication.removeTranslator(self.translator)
        self.translator.load(f'QTempo_{language}', Asset.I18N.value.as_posix())
        QCoreApplication.installTranslator(self.translator)
        self.retranslate()

    def retranslate(self) -> None:
        self.retranslateUi(self)
        # Qt translates the standard buttons in the language of QGIS
        buttons = {
            QDialogButtonBox.StandardButton.Ok: self.tr('OK'),
            QDialogButtonBox.StandardButton.Cancel: self.tr('Cancel'),
        }
        for button, text in buttons.items():
            push_button = self.buttonBox.button(button)
            assert push_button is not None
            push_button.setText(text)
        for item in get_list_widget_items(self.listWidgetServices):
            service = t.cast(
                services.Service, item.data(QListWidgetItemRole.SERVICE.value)
            )
            item.setText(service.full_name)

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
            self.tr('Loading the matrices of {name}').format(
                name=parse_node_name(node['context']['name'])
            ),
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
        language = self.get_language()
        QgsSettings().setValue(Setting.LANGUAGE.value, language)
        self.set_language(language)
        self.fetch_table_of_contents()

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
        self.mGroupBoxTableOptions.setVisible(False)
        self.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, False)
        self.reset_downloads()

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
            self.tr('Loading the matrices of {name}').format(
                name=selected_dataset.text(0)
            ),
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
            request,
            self.tr('Fetching the information of {code}').format(
                code=dataset_code
            ),
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
            frame_layout = self.frameQuery.layout()
            assert frame_layout is not None
            layouts = get_children(frame_layout, QVBoxLayout)
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

    def add_leaf_node_ro(self) -> None:
        """Stores the Romanian definition of the selected matrix.

        Territorial units are resolved from the Romanian labels, as the
        labels in other languages are translated.
        """
        current_item = self.listWidgetMatrices.currentItem()
        if (
            current_item is None
            or current_item.data(QListWidgetItemRole.LEAF_NODE_RO.value)
            is not None
        ):
            return None
        if self.get_language() == 'ro':
            current_item.setData(
                QListWidgetItemRole.LEAF_NODE_RO.value,
                current_item.data(QListWidgetItemRole.LEAF_NODE.value),
            )
            return None
        dataset_code = self.get_matrix_code()
        request = QNetworkRequest(
            QUrl(URL.DATASET.value.format(code=dataset_code))
        )
        reply = self.request_handler.get(
            request,
            self.tr('Fetching the information of {code}').format(
                code=dataset_code
            ),
        )

        def set_leaf_node_ro():
            current_item.setData(
                QListWidgetItemRole.LEAF_NODE_RO.value,
                json.loads(reply.readAll().data()),
            )

        reply.finished.connect(set_leaf_node_ro)

    def add_queries(self) -> None:
        self.tabWidgetMatrix.setCurrentIndex(Tabs.QUERY.value)
        self.clear_table()
        reply = self.get_leaf_node()

        def add_dimensions() -> None:
            assert reply is not None
            leaf_node = t.cast(LeafNode, json.loads(reply.readAll().data()))
            self.add_leaf_node_to_list_widget_item(leaf_node)
            if leaf_node is not None:
                self.add_dimensions_to_frame_query(leaf_node['dimensionsMap'])

        if reply is not None:
            reply.finished.connect(add_dimensions)
            reply.finished.connect(self.add_leaf_node_ro)

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

    def construct_queries(self) -> list[str]:
        """The encoded queries of the selected options. A dimension with
        more than MAX_QUERY_OPTIONS selected options is split between
        several queries."""
        list_widgets = get_children(self.frameQuery, QListWidget)
        dimensions: list[list[str]] = []
        for list_widget in list_widgets:
            choices = t.cast(
                list[Choice],
                [
                    selected_item.data(QListWidgetItemRole.CHOICE.value)
                    for selected_item in list_widget.selectedItems()
                ],
            )
            ids = [str(choice['nomItemId']) for choice in choices]
            dimensions.append(
                [
                    ','.join(ids[i : i + MAX_QUERY_OPTIONS])
                    for i in range(0, len(ids), MAX_QUERY_OPTIONS)
                ]
            )
        return [':'.join(query) for query in itertools.product(*dimensions)]

    def construct_body(self, query: str) -> RequestBody:
        current_item = self.listWidgetMatrices.currentItem()
        assert current_item
        leaf_node = t.cast(
            LeafNode, current_item.data(QListWidgetItemRole.LEAF_NODE.value)
        )
        return t.cast(
            RequestBody,
            {
                'language': self.get_language(),
                'encQuery': query,
                'matCode': self.get_matrix_code(),
                **leaf_node['details'],
            },
        )

    def get_matrix(self) -> Matrix | None:
        """The queried data of the selected matrix."""
        current_item = self.listWidgetMatrices.currentItem()
        if current_item is None:
            return None
        return current_item.data(QListWidgetItemRole.MATRIX.value)

    def get_model_matrix(self) -> Matrix | None:
        """The pivoted data shown in the table."""
        model = self.tableViewMatrix.model()
        if model is None:
            return None
        return t.cast(MatrixModel, model)._matrix

    def add_table_options(self, matrix: Matrix) -> None:
        """Adds a combo box for each dimension with more than one value. An
        empty choice spreads all the values into columns."""
        default = matrix.default_fixed()
        layout = self.frameTableOptions.layout()
        if layout is not None:
            delete_layout_items(layout)
        else:
            layout = QGridLayout(self.frameTableOptions)
            self.frameTableOptions.setLayout(layout)
        layout = t.cast(QGridLayout, layout)
        dimensions = [
            field_
            for field_ in matrix.dimensions
            if len(matrix.distinct(field_)) > 1
        ]
        for i, field_ in enumerate(dimensions):
            label = QLabel(
                textwrap.fill(field_.name, width=40), self.frameTableOptions
            )
            combo_box = QComboBox(self.frameTableOptions)
            add_completer_to_combo_box(combo_box)
            combo_box.setToolTip(
                self.tr('Leave empty to show every value as a column.')
            )
            combo_box.addItem('', None)
            for value in matrix.distinct(field_):
                combo_box.addItem(value, value)
            if field_ in default:
                combo_box.setCurrentIndex(combo_box.findText(default[field_]))
            else:
                combo_box.setCurrentIndex(0)
            combo_box.setProperty(WidgetProperty.FIELD.value, field_)
            combo_box.currentIndexChanged.connect(self.update_table_view)
            row, column = divmod(i, 2)
            layout.addWidget(label, row, column * 2)
            layout.addWidget(combo_box, row, column * 2 + 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

    def get_fixed(self, matrix: Matrix) -> dict[Field, str]:
        """The value chosen for each dimension. The dimensions with a single
        value are fixed to it."""
        fixed = {
            field_: values[0]
            for field_ in matrix.dimensions
            if len(values := matrix.distinct(field_)) == 1
        }
        layout = self.frameTableOptions.layout()
        # Read from the layout, as the replaced combo boxes are only
        # deleted later
        combo_boxes = [] if layout is None else get_widgets(layout, QComboBox)
        for combo_box in combo_boxes:
            value = combo_box.currentData()
            if value is not None:
                field_ = combo_box.property(WidgetProperty.FIELD.value)
                fixed[t.cast(Field, field_)] = value
        return fixed

    def update_table_view(self) -> None:
        """Shows one row per unit, or the queried rows if the data has no
        units."""
        matrix = self.get_matrix()
        if matrix is None:
            return None
        shown = (
            matrix.pivot(self.get_fixed(matrix)) if matrix.has_units else matrix
        )
        old_model = self.tableViewMatrix.model()
        self.tableViewMatrix.setModel(MatrixModel(shown, self.tableViewMatrix))
        if old_model is not None:
            old_model.deleteLater()
        self.tableViewMatrix.resizeColumnsToContents()
        rows = self.tr('%n row(s)', '', len(shown.data))
        columns = self.tr('%n column(s)', '', len(shown.fields))
        self.labelTableSummary.setText(f'{rows} × {columns}')

    def get_map_levels(self, matrix: Matrix) -> list[Level]:
        """The levels to map, one layer each. The national total is only
        mapped when the data has no other level."""
        levels = matrix.levels
        if len(levels) > 1 and Level.COUNTRY in levels:
            levels.remove(Level.COUNTRY)
        return levels

    def handle_map_tab(self) -> None:
        data = self.get_matrix()
        assert data is not None
        self.tabWidgetMatrix.setTabEnabled(Tabs.MAP.value, data.has_units)
        if not data.has_units:
            return None
        levels = self.get_map_levels(data)
        counts = []
        for level in levels:
            units = self.tr('%n unit(s)', '', len(data.get_units(level)))
            counts.append(f'{level.label}: {units}')
        self.labelMapLevels.setText(', '.join(counts))
        is_nuts = levels[0].is_nuts
        self.mGroupBoxServices.setVisible(not is_nuts)
        self.mGroupBoxGisco.setVisible(is_nuts)
        self.reset_join_report()
        self.reset_downloads()
        if is_nuts and not self.comboBoxGiscoYear.count():
            self.load_nuts_index()

    def load_nuts_index(self, year: str | None = None) -> None:
        if self.nuts_index_task is not None:
            return None
        task = nuts.FetchNutsIndexTask(year)
        task.taskCompleted.connect(partial(self.handle_nuts_index, task))
        task.taskTerminated.connect(partial(self.handle_nuts_index, task))
        self.nuts_index_task = task
        manager = QgsApplication.taskManager()
        assert manager is not None
        manager.addTask(task)

    def handle_nuts_index(self, task: nuts.FetchNutsIndexTask) -> None:
        self.nuts_index_task = None
        if task.exception is not None:
            message_bar = self.get_message_bar()
            message_bar.pushCritical(
                self.tr('Failed to fetch the GISCO NUTS index'),
                str(task.exception),
            )
            return None
        if task.status() == QgsTask.TaskStatus.Complete:
            self.fill_nuts_combo_boxes()

    def fill_nuts_combo_boxes(self) -> None:
        if not self.comboBoxGiscoYear.count():
            with QSignalBlocker(self.comboBoxGiscoYear):
                self.comboBoxGiscoYear.addItems(nuts.CACHED_YEARS)
        units = nuts.CACHED_UNITS.get(self.comboBoxGiscoYear.currentText())
        if units is None:
            self.load_nuts_index(self.comboBoxGiscoYear.currentText())
            return None
        units = units.filter(spatial_type=[nuts.SPATIAL_TYPE])
        set_combo_box_items(
            self.comboBoxGiscoScale, units.values('scale'), nuts.DEFAULT_SCALE
        )
        set_combo_box_items(
            self.comboBoxGiscoProjection,
            units.values('projection'),
            nuts.DEFAULT_PROJECTION,
        )

    def get_nuts_units(self) -> nuts.Units | None:
        """The NUTS files for the selected year, scale and projection."""
        units = nuts.CACHED_UNITS.get(self.comboBoxGiscoYear.currentText())
        if units is None:
            return None
        return units.filter(
            spatial_type=[nuts.SPATIAL_TYPE],
            scale=[self.comboBoxGiscoScale.currentText()],
            projection=[self.comboBoxGiscoProjection.currentText()],
        )

    def push_nuts_index_warning(self) -> None:
        self.load_nuts_index()
        message_bar = self.get_message_bar()
        message_bar.pushWarning(
            'GISCO',
            self.tr('The NUTS index is still loading. Try again shortly.'),
        )

    def validate_join(self) -> None:
        matrix = self.get_matrix()
        assert matrix is not None
        available = self.get_nuts_units()
        if available is None:
            return self.push_nuts_index_warning()
        ids = {unit.id for unit in available}
        report = [
            JoinReportRow(unit.label, level.label, unit.code, unit.code in ids)
            for level in self.get_map_levels(matrix)
            for unit in matrix.get_units(level)
        ]
        matched = sum(row.matched for row in report)
        text = self.tr(
            '{matched} of %n unit(s) are in NUTS {year}.', '', len(report)
        ).format(matched=matched, year=self.comboBoxGiscoYear.currentText())
        unresolved = matrix.unresolved_labels
        if unresolved:
            report.extend(
                JoinReportRow(label, '', '', False) for label in unresolved
            )
            text += ' ' + self.tr(
                '%n label(s) could not be mapped.', '', len(unresolved)
            )
        self.join_report = report
        self.labelJoinStatus.setText(text)
        self.pushButtonJoinReport.setEnabled(True)

    def reset_join_report(self) -> None:
        self.join_report = []
        self.labelJoinStatus.clear()
        self.pushButtonJoinReport.setEnabled(False)

    def reset_downloads(self) -> None:
        self.tableWidgetDownloads.clear()
        self.tableWidgetDownloads.setRowCount(0)
        self.tableWidgetDownloads.setColumnCount(0)

    def display_join_report(self) -> None:
        JoinReportDialog(self.join_report, self).exec()
        # On macOS, closing a modal dialog activates the QGIS window
        self.activateWindow()

    def fetch_data(self) -> None:
        """Sends the queries one after another and shows their merged
        data."""
        code = self.get_matrix_code()
        bodies = [
            self.construct_body(query) for query in self.construct_queries()
        ]
        responses: list[bytes] = []

        def post() -> None:
            request = QNetworkRequest(
                QUrl(self.preprocess_url(URL.TABLE.value))
            )
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                'application/json',
            )
            text = self.tr('Fetching the data of {code}').format(code=code)
            if len(bodies) > 1:
                text += f' ({len(responses) + 1}/{len(bodies)})'
            reply = self.request_handler.post(
                request,
                json.dumps(bodies[len(responses)]).encode('UTF-8'),
                text,
            )
            reply.finished.connect(partial(handle_reply, reply))

        def handle_reply(reply: QNetworkReply) -> None:
            if reply.error() != QNetworkReply.NetworkError.NoError:  # pyright: ignore[reportCallIssue]
                self.qtempo._handle_error_signal(
                    RequestError(
                        self.tr(
                            'Failed to fetch the data of {code}: {error}'
                        ).format(code=code, error=reply.errorString())
                    )
                )
                return None
            responses.append(reply.readAll().data())  # pyright: ignore[reportArgumentType]
            if len(responses) < len(bodies):
                post()
            else:
                set_matrix()

        def set_matrix() -> None:
            current_item = self.listWidgetMatrices.currentItem()
            assert current_item
            current_item.setData(
                QListWidgetItemRole.MATRIX.value,
                Matrix.from_response(
                    Matrix.merge_responses(responses),
                    bodies[0],
                    current_item.data(QListWidgetItemRole.LEAF_NODE.value),
                    current_item.data(QListWidgetItemRole.LEAF_NODE_RO.value),
                ),
            )
            self.handle_map_tab()
            self.update_table()
            self.pushButtonAddTableLayer.setEnabled(True)

        post()

    def clear_table_options(self) -> None:
        delete_layout_items(self.frameTableOptions.layout())
        self.labelTableSummary.clear()

    def update_table(self) -> None:
        matrix = self.get_matrix()
        if matrix is None:
            return None
        self.clear_table_options()
        self.mGroupBoxTableOptions.setVisible(matrix.has_units)
        if matrix.has_units:
            self.add_table_options(matrix)
        self.update_table_view()
        self.pushButtonAddVectorLayer.setEnabled(matrix.has_units)
        self.tabWidgetMatrix.setCurrentIndex(Tabs.TABLE.value)

    def display_service_information(self) -> None:
        if not (items := self.listWidgetServices.selectedItems()):
            return None
        service = t.cast(
            services.Service, items[0].data(QListWidgetItemRole.SERVICE.value)
        )
        information = QLabel(
            self.tr('Name: {name}<br>URL: {url}').format(
                name=service.full_name,
                url=f'<a href="{service.url}">{service.url}</a>',
            )
        )
        information.setTextFormat(Qt.TextFormat.RichText)
        information.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse  # pyright: ignore[reportArgumentType]
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        information.setOpenExternalLinks(True)
        dialog = QDialog(self)
        layout = QVBoxLayout()
        layout.addWidget(information)
        dialog.setWindowTitle(service.short_name)
        dialog.setLayout(layout)
        dialog.exec()
        self.activateWindow()

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

    def add_vector_layer(self) -> None:
        matrix = self.get_model_matrix()
        assert matrix is not None
        levels = self.get_map_levels(matrix)
        if (self.downloader is not None and self.downloader.is_running) or (
            self.localities_task is not None
        ):
            message_bar = self.get_message_bar()
            message_bar.pushInfo(
                'QTempo', self.tr('A download is already running.')
            )
        elif levels[0].is_nuts:
            self.add_nuts_layers(matrix, levels)
        else:
            self.add_localities_layer(matrix)

    def add_nuts_layers(self, matrix: Matrix, levels: list[Level]) -> None:
        year = self.comboBoxGiscoYear.currentText()
        scale = self.comboBoxGiscoScale.currentText()
        projection = self.comboBoxGiscoProjection.currentText()
        if not (year and scale and projection):
            return self.push_nuts_index_warning()
        code = self.get_matrix_code()
        assert code is not None
        by_level = {level: matrix.filter_level(level) for level in levels}
        units = dict.fromkeys(
            nuts.Unit(unit.code, nuts.SPATIAL_TYPE, scale, projection, year)
            for level_matrix in by_level.values()
            for unit in level_matrix.units or []
            if unit is not None
        )
        self.downloader = nuts.BoundaryDownloader(
            units, self.tableWidgetDownloads
        )
        self.downloader.finished.connect(
            partial(self.add_nuts_boundaries, by_level, code, projection)
        )
        self.pushButtonAddVectorLayer.setEnabled(False)
        self.downloader.start()

    def add_nuts_boundaries(
        self,
        by_level: dict[Level, Matrix],
        name: str,
        projection: str,
        boundaries: nuts.Boundaries,
    ) -> None:
        self.pushButtonAddVectorLayer.setEnabled(True)
        message_bar = self.get_message_bar()
        if not boundaries.features:
            message_bar.pushCritical(
                'GISCO',
                self.tr(
                    'No boundaries were downloaded. See the errors in the download table.'
                ),
            )
            return None
        if boundaries.errors:
            message_bar.pushWarning(
                'GISCO',
                self.tr(
                    '%n boundary(ies) failed to download. See the errors in the download table.',
                    '',
                    len(boundaries.errors),
                ),
            )
        self.add_layers(
            [
                level_matrix.join_boundaries(
                    boundaries.fields,
                    boundaries.features,
                    'NUTS_ID',
                    f'{name} — {level.label}',
                    f'EPSG:{projection}',
                )
                for level, level_matrix in by_level.items()
            ]
        )

    def add_localities_layer(self, matrix: Matrix) -> None:
        service = self.get_selected_service()
        assert service is not None
        task = FetchLocalitiesTask(
            service, [unit for unit in matrix.units or [] if unit is not None]
        )
        task.taskCompleted.connect(
            partial(
                self.add_localities_boundaries,
                task,
                matrix,
                f'{self.get_matrix_code()} — {Level.LOCALITY.label}',
            )
        )
        task.taskTerminated.connect(partial(self.handle_localities_error, task))
        self.localities_task = task
        self.pushButtonAddVectorLayer.setEnabled(False)
        manager = QgsApplication.taskManager()
        assert manager is not None
        manager.addTask(task)
        message_bar = self.get_message_bar()
        message_bar.pushInfo(
            service.short_name,
            self.tr(
                'Downloading the boundaries. The layer is added when the download finishes.'
            ),
        )

    def add_localities_boundaries(
        self, task: FetchLocalitiesTask, matrix: Matrix, name: str
    ) -> None:
        self.localities_task = None
        self.pushButtonAddVectorLayer.setEnabled(True)
        self.add_layers(
            [
                matrix.join_boundaries(
                    task.fields,
                    task.features,
                    task.service.siruta_field,
                    name,
                )
            ]
        )

    def handle_localities_error(self, task: FetchLocalitiesTask) -> None:
        self.localities_task = None
        self.pushButtonAddVectorLayer.setEnabled(True)
        if task.exception is not None:
            self.qtempo._handle_error_signal(task.exception)

    def add_layers(self, layers: list[QgsVectorLayer]) -> None:
        """Adds the layers, from the coarsest level up, and zooms to the
        first one."""
        project = QgsProject.instance()
        assert project is not None
        for layer in layers:
            project.addMapLayer(layer)
        self.qtempo.iface.setActiveLayer(layers[0])
        self.qtempo.iface.zoomToActiveLayer()

    def cancel_tasks(self) -> None:
        if self.downloader is not None:
            self.downloader.cancel()
        for task in (self.nuts_index_task, self.localities_task):
            if task is not None:
                task.cancel()

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
            if isinstance(obj, QWidget) and obj is not self.messageBar:
                obj.setEnabled(state)

    def enable_gui(self) -> None:
        self.set_gui_state(True)
        # Disabling a widget takes away its focus
        widget = self.focus_widget
        if (
            widget is not None
            and not sip.isdeleted(widget)
            and widget.isVisible()
        ):
            widget.setFocus()
        self.focus_widget = None

    def disable_gui(self) -> None:
        self.focus_widget = self.focusWidget()
        self.set_gui_state(False)


class FetchLocalitiesTask(QgsTask):
    """Fetches the boundaries of localities from a service."""

    def __init__(self, service: services.Service, units: list[TerritorialUnit]):
        super().__init__(
            QCoreApplication.translate(
                'FetchLocalitiesTask', 'Fetching the boundaries from {service}'
            ).format(service=service.short_name),
            QgsTask.Flag.CanCancel,
        )
        self.service = service
        self.units = units
        self.fields = QgsFields()
        self.features: list[QgsFeature] = []
        self.exception: Exception | None = None

    def run(self) -> bool:
        try:
            self.fields, self.features = self.service.get_features(self.units)
        except Exception as e:
            self.exception = e
            return False
        return not self.isCanceled()


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
        if not index.isValid():
            return None
        is_value = self._matrix.fields[index.column()].is_value
        if role == Qt.ItemDataRole.DisplayRole:
            value = self._matrix.data[index.row()][index.column()]
            if value is None:
                return ''
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and is_value:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
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


@dataclass
class RequestHandler:
    """Sends the requests of the dialog, which shows their progress and is
    disabled until they all finish."""

    manager: QgsNetworkAccessManager
    parent: Dialog
    replies: list[QNetworkReply] = field(init=False, default_factory=list)

    def keep_until_finished(self, reply: QNetworkReply) -> None:
        """Keeps a reference to the reply until its finished slots ran.

        The slots are often closures over the reply. Without a reference,
        the garbage collector can clear them while the request runs, which
        crashes QGIS when the reply finishes.
        """
        self.replies.append(reply)

        def release() -> None:
            # Runs after the finished slots, so the requests they start keep
            # the dialog disabled
            QTimer.singleShot(0, lambda: self.release(reply))

        reply.finished.connect(release)

    def release(self, reply: QNetworkReply) -> None:
        self.replies.remove(reply)
        if not self.replies:
            self.parent.hide_progress()
            self.parent.enable_gui()

    def show_progress(self, text: str) -> None:
        if not self.replies:
            self.parent.disable_gui()
        self.parent.show_progress(text)

    def post(
        self, request: QNetworkRequest, data: bytes, text: str
    ) -> QNetworkReply:
        self.show_progress(text)
        reply = self.manager.post(request, data)
        assert reply is not None
        self.keep_until_finished(reply)
        return reply

    def get(self, request: QNetworkRequest, text: str) -> QNetworkReply:
        self.show_progress(text)
        reply = self.manager.get(request)
        assert reply is not None
        self.keep_until_finished(reply)
        return reply


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
        if not self.first_start:
            self.dialog.cancel_tasks()
            # The dialog is owned by the QGIS window, which outlives the plugin
            self.dialog.close()
            self.dialog.deleteLater()

    def _handle_error_signal(self, error: Exception) -> None:
        message_bar = self.dialog.get_message_bar()
        message_bar.pushCritical(
            QCoreApplication.translate('QTempo', 'Error'), str(error)
        )
        raise error

    def _handle_table_of_contents_error(self):
        self._handle_error_signal(
            RequestError(
                QCoreApplication.translate(
                    'QTempo',
                    'Failed to fetch the table of contents. Check your internet connection and try again.',
                )
            )
        )

    def run(self) -> None:
        if self.first_start is True:
            self.first_start = False
            self.network_manager = QgsNetworkAccessManager()
            self.dialog = Dialog(self, self.iface.mainWindow())
        # Fetched again if it failed before
        if (
            not self.dialog.treeWidgetTableOfContents.topLevelItemCount()
            and not self.dialog.request_handler.replies
        ):
            reply = self.dialog.fetch_table_of_contents()
            reply.errorOccurred.connect(self._handle_table_of_contents_error)
        self.dialog.display_dialog()
