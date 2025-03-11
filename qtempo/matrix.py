from __future__ import annotations

import collections.abc as c
import operator
import re
import typing as t
from collections import UserList
from dataclasses import dataclass

from qgis.core import QgsFeature, QgsField, QgsFields, QgsVectorLayer, edit
from qgis.PyQt.QtCore import QVariant

from ._typing import RequestBody


@dataclass
class Field:
    name: str
    is_time: bool = False
    is_value: bool = False
    is_reg: bool = False
    is_jud: bool = False
    is_loc: bool = False

    def __eq__(self, field: object) -> bool:
        if isinstance(field, Field):
            return self.name == field.name
        return self.name == field

    def __hash__(self) -> int:
        return hash(self.name)

    @property
    def is_geo(self):
        return self.is_reg or self.is_jud or self.is_loc


@dataclass
class Fields(UserList[Field]):
    data: list[Field]

    @property
    def time(self) -> Field:
        for field_ in self.data:
            if field_.is_time:
                return field_
        raise ValueError

    @property
    def value(self) -> Field:
        for field_ in self.data:
            if field_.is_value:
                return field_
        raise ValueError

    @property
    def reg(self) -> Field:
        for field_ in self.data:
            if field_.is_reg:
                return field_
        raise ValueError

    @property
    def jud(self) -> Field:
        for field_ in self.data:
            if field_.is_jud:
                return field_
        raise ValueError

    @property
    def loc(self) -> Field:
        for field_ in self.data:
            if field_.is_loc:
                return field_
        raise ValueError

    def get(self, name: str) -> Field:
        for field_ in self.data:
            if field_.name == name:
                return field_
        raise ValueError


@dataclass
class Matrix(c.Mapping):
    data: list[list[t.Any]]
    fields: Fields
    siruta: list[SIRUTA | None] | None = None

    def __iter__(self) -> c.Iterator[Field]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def __getitem__(self, field: str | Field) -> list[t.Any]:
        if isinstance(field, Field):
            col_index = self.fields.index(field)
        else:
            col_index = 1
        return list(map(operator.itemgetter(col_index), self.data))

    @property
    def has_siruta(self) -> bool:
        # This will return False if siruta is either empty or None
        if self.siruta is not None:
            not_na = [value for value in self.siruta if value is not None]
            return bool(not_na)
        return False

    @staticmethod
    def parse_query_response(response: str) -> dict[str, list[t.Any]]:
        lines_split = iter(response.splitlines())
        columns = next(lines_split).split(', ')
        data: dict[str, list[t.Any]] = {column: [] for column in columns}
        for line in lines_split:
            values = line.split(', ')
            for i, value in enumerate(values):
                data[columns[i]].append(value)
        return data

    @classmethod
    def from_response(
        cls, response: bytes, request_body: RequestBody
    ) -> t.Self:
        data = cls.parse_query_response(response.decode(encoding='UTF-8'))

        def get_fields() -> Fields:
            fields = []
            for i, field_ in enumerate(data, start=1):
                if i == request_body['matTime']:
                    fields.append(Field(field_, is_time=True))
                elif i == request_body['matRegJ']:
                    fields.append(Field(field_, is_reg=True))
                elif i == request_body['nomJud']:
                    fields.append(Field(field_, is_jud=True))
                elif i == request_body['nomLoc']:
                    fields.append(Field(field_, is_loc=True))
                elif i == len(data):
                    fields.append(Field(field_, is_value=True))
                else:
                    fields.append(Field(field_))
            return Fields(fields)

        fields = get_fields()
        rows = [list(row) for row in zip(*data.values())]
        if request_body['matSiruta'] == 1:
            loc_index = request_body['nomLoc'] - 1
            siruta: list[SIRUTA | None] = []
            for row in rows:
                try:
                    siruta.append(SIRUTA.from_value(row[loc_index]))
                except ValueError:
                    siruta.append(None)
            return cls(rows, fields, siruta)
        return cls(rows, fields)

    def as_table(
        self, name: str | None = None, siruta_field_name: str | None = None
    ) -> QgsVectorLayer:
        layer = QgsVectorLayer(
            'none', name if name is not None else '', 'memory'
        )
        provider = layer.dataProvider()
        attributes = QgsFields()
        for field_ in self.fields:
            variant = QVariant.Double if field_.is_value else QVariant.String
            attributes.append(QgsField(field_.name, variant))
        if self.has_siruta:
            attributes.append(
                QgsField(
                    siruta_field_name if siruta_field_name is not None else '',
                    QVariant.String,
                )
            )
        if provider is None:
            raise ValueError(f'Failed to access data provider for a {layer!r}')
        provider.addAttributes(attributes)
        layer.updateFields()
        features = []
        for i, row in enumerate(self.data):
            feature = QgsFeature(attributes)
            if self.has_siruta:
                assert self.siruta
                siruta = self.siruta[i]
                row.append(siruta.code if siruta is not None else None)
            feature.setAttributes(row)
            features.append(feature)
        with edit(layer):
            layer.addFeatures(features)
        return layer

    def get_subset(self, siruta: SIRUTA) -> Matrix:
        assert self.siruta
        subset = [
            row
            for other_siruta, row in zip(self.siruta, self.data)
            if siruta == other_siruta
        ]
        return Matrix(
            subset,
            self.fields,
            t.cast(list[SIRUTA | None], [siruta] * len(subset)),
        )

    def group_by(
        self,
        group_by: Field,
        table_options: c.Mapping[Field, str],
    ) -> Matrix:
        fields = Fields(
            [Field(name, is_value=True) for name in sorted(set(self[group_by]))]
        )

        assert self.siruta
        siruta_notna = [siruta for siruta in self.siruta if siruta is not None]
        siruta_sorted = sorted(
            set(siruta_notna), key=operator.attrgetter('code')
        )

        rows = []
        for siruta in siruta_sorted:
            values: list[str | None] = []
            subset = self.get_subset(siruta)
            filter_options = dict(table_options)
            for field_ in fields:
                if field_.name not in subset[group_by]:
                    values.append(None)
                    continue
                filter_options[group_by] = field_.name
                for row in subset.data:
                    if all(
                        row[subset.fields.index(filter_field)] == value
                        for filter_field, value in filter_options.items()
                    ):
                        values.append(
                            row[subset.fields.index(subset.fields.value)]
                        )
            rows.append(values)
        return Matrix(rows, fields, t.cast(list[SIRUTA | None], siruta_sorted))


class SIRUTA(t.NamedTuple):
    place: str
    code: str
    initial_value: str | None = None

    @classmethod
    def from_value(cls, string: str) -> t.Self:
        siruta = re.fullmatch(r'(\d+)\s(.+)', string)
        if siruta is None:
            raise ValueError(f'Failed to parse SIRUTA from {siruta!r}')
        groups = siruta.groups()
        return cls(groups[1], groups[0], string)
