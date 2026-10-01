from __future__ import annotations

import collections.abc as c
import operator
import typing as t
from collections import UserList
from dataclasses import dataclass

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorLayer,
    edit,
)
from qgis.PyQt.QtCore import QVariant

from ._typing import LeafNode, RequestBody
from .enums import Level
from .units import TerritorialUnit, resolve_dimension


@dataclass
class Field:
    name: str
    is_time: bool = False
    is_value: bool = False
    is_reg: bool = False
    is_jud: bool = False
    is_loc: bool = False
    is_unit: bool = False

    def __eq__(self, field: object) -> bool:
        if isinstance(field, Field):
            return self.name == field.name
        return self.name == field

    def __hash__(self) -> int:
        return hash(self.name)

    @property
    def is_geo(self):
        return self.is_reg or self.is_jud or self.is_loc or self.is_unit


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

    @property
    def unit(self) -> Field:
        for field_ in self.data:
            if field_.is_unit:
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
    units: list[TerritorialUnit | None] | None = None

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
    def has_units(self) -> bool:
        # This will return False if units is either empty or None
        if self.units is not None:
            return any(unit is not None for unit in self.units)
        return False

    @property
    def levels(self) -> list[Level]:
        if self.units is None:
            return []
        levels = {unit.level for unit in self.units if unit is not None}
        return sorted(levels, key=operator.attrgetter('value'))

    @property
    def unresolved_labels(self) -> list[str]:
        """The labels of the geographic field which are not mappable."""
        if self.units is None or not any(f.is_unit for f in self.fields):
            return []
        index = self.fields.index(self.fields.unit)
        return sorted(
            {
                row[index]
                for row, unit in zip(self.data, self.units)
                if unit is None
            }
        )

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
        cls,
        response: bytes,
        request_body: RequestBody,
        leaf_node: LeafNode,
        leaf_node_ro: LeafNode | None = None,
    ) -> t.Self:
        """Parses a pivot response and resolves its territorial units.

        The Romanian definition (leaf_node_ro) is needed to resolve the
        units when the response is in another language.
        """
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
            fields[loc_index].is_unit = True
            units: list[TerritorialUnit | None] = []
            for row in rows:
                try:
                    units.append(
                        TerritorialUnit.from_siruta_label(row[loc_index])
                    )
                except ValueError:
                    units.append(None)
            return cls(rows, fields, units)

        # The geography flags are often 0, so every dimension is checked,
        # starting with the flagged ones
        dimensions = leaf_node['dimensionsMap'][: len(fields) - 1]
        ro_options = {
            dimension['dimCode']: dimension['options']
            for dimension in (leaf_node_ro or leaf_node)['dimensionsMap']
        }
        flagged = [
            i - 1
            for i in (request_body['matRegJ'], request_body['nomJud'])
            if 0 < i <= len(dimensions)
        ]
        others = [i for i in range(len(dimensions)) if i not in flagged]
        for i in flagged + others:
            dimension = dimensions[i]
            resolved = resolve_dimension(
                dimension['options'],
                ro_options.get(dimension['dimCode'], dimension['options']),
            )
            if resolved is None:
                continue
            fields[i].is_unit = True
            units = [resolved.get(row[i].strip()) for row in rows]
            return cls(rows, fields, units)
        return cls(rows, fields)

    def as_table(
        self, name: str | None = None, code_field_name: str | None = None
    ) -> QgsVectorLayer:
        layer = QgsVectorLayer(
            'none', name if name is not None else '', 'memory'
        )
        provider = layer.dataProvider()
        attributes = QgsFields()
        for field_ in self.fields:
            variant = QVariant.Double if field_.is_value else QVariant.String  # pyright: ignore[reportAttributeAccessIssue]
            attributes.append(QgsField(field_.name, variant))
        if self.has_units:
            if code_field_name is None:
                code_field_name = (
                    'SIRUTA' if Level.LOCALITY in self.levels else 'NUTS_ID'
                )
            attributes.append(
                QgsField(
                    code_field_name,
                    QVariant.String,  # pyright: ignore[reportAttributeAccessIssue]
                )
            )
        if provider is None:
            raise ValueError(f'Failed to access data provider for a {layer!r}')
        provider.addAttributes(attributes)
        layer.updateFields()
        features = []
        for i, row in enumerate(self.data):
            feature = QgsFeature(attributes)
            if self.has_units:
                assert self.units
                unit = self.units[i]
                row = [*row, unit.code if unit is not None else None]
            feature.setAttributes(row)
            features.append(feature)
        with edit(layer):
            layer.addFeatures(features)
        return layer

    def get_units(self, level: Level) -> list[TerritorialUnit]:
        """The distinct units of a level, sorted by code."""
        assert self.units is not None
        units = {
            unit.code: unit
            for unit in self.units
            if unit is not None and unit.level is level
        }
        return [units[code] for code in sorted(units)]

    def filter_level(self, level: Level) -> Matrix:
        assert self.units is not None
        rows, units = [], []
        for row, unit in zip(self.data, self.units):
            if unit is not None and unit.level is level:
                rows.append(row)
                units.append(unit)
        return Matrix(rows, self.fields, units)

    def group_by(
        self,
        group_by: Field,
        table_options: c.Mapping[Field, str],
    ) -> Matrix:
        """Pivots the matrix to one row per unit and one column per value
        of the group_by field, keeping the rows that match table_options."""
        assert self.units is not None
        names = sorted(set(self[group_by]))
        columns = {name: i for i, name in enumerate(names)}
        group_index = self.fields.index(group_by)
        value_index = self.fields.index(self.fields.value)
        filters = [
            (self.fields.index(field_), value)
            for field_, value in table_options.items()
        ]

        units: dict[str, TerritorialUnit] = {}
        rows: dict[str, list[t.Any]] = {}
        for unit, row in zip(self.units, self.data):
            if unit is None:
                continue
            units.setdefault(unit.code, unit)
            values = rows.setdefault(unit.code, [None] * len(names))
            if all(row[index] == value for index, value in filters):
                column = columns[row[group_index]]
                if values[column] is None:
                    values[column] = row[value_index]

        codes = sorted(rows)
        return Matrix(
            [rows[code] for code in codes],
            Fields([Field(name, is_value=True) for name in names]),
            [units[code] for code in codes],
        )

    def join_boundaries(
        self,
        fields: QgsFields,
        features: c.Iterable[QgsFeature],
        key_field: str,
        name: str,
        crs: str = 'EPSG:4326',
    ) -> QgsVectorLayer:
        """Joins the rows to the boundaries with the same unit code.

        Boundaries without a matching row are discarded.
        """
        assert self.units is not None
        rows = {
            unit.code: row
            for unit, row in zip(self.units, self.data)
            if unit is not None
        }
        layer = QgsVectorLayer(f'MultiPolygon?crs={crs}', name, 'memory')
        provider = layer.dataProvider()
        if provider is None:
            raise ValueError(f'Failed to access data provider for a {layer!r}')
        attributes = QgsFields(fields)
        for field_ in self.fields:
            variant = QVariant.Double if field_.is_value else QVariant.String  # pyright: ignore[reportAttributeAccessIssue]
            attributes.append(QgsField(field_.name, variant))
        provider.addAttributes(attributes.toList())
        layer.updateFields()

        boundary_names = fields.names()
        joined = []
        for feature in features:
            row = rows.get(str(feature.attribute(key_field)))
            if row is None:
                continue
            geometry = QgsGeometry(feature.geometry())
            geometry.convertToMultiType()
            output = QgsFeature(attributes)
            output.setGeometry(geometry)
            # Read by name, as the boundary schema can vary between features
            boundary = [
                feature.attribute(name_)
                if feature.fields().lookupField(name_) != -1
                else None
                for name_ in boundary_names
            ]
            values = [
                to_float(value) if field_.is_value else value
                for field_, value in zip(self.fields, row)
            ]
            output.setAttributes(boundary + values)
            joined.append(output)
        provider.addFeatures(joined)
        layer.updateExtents()
        return layer


def to_float(value: t.Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
