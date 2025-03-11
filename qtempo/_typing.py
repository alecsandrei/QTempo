from __future__ import annotations

import typing as t

Language = t.Literal['en', 'ro']


class Context(t.TypedDict):
    name: str
    code: str
    childrenUrl: str
    comment: str
    url: str


class Node(t.TypedDict):
    parentCode: str
    level: int
    context: Context
    ancestors: t.NotRequired[list[Context]]
    children: t.NotRequired[list[Context]]


class DataSources(t.TypedDict):
    nume: str
    tip: str
    linkNumber: int
    codTip: int


class Choice(t.TypedDict):
    label: str
    nomItemId: int
    offset: int
    parentId: None | int


class Dimension(t.TypedDict):
    options: list[Choice]
    dimCode: int
    label: str


class Details(t.TypedDict):
    nomJud: int
    nomLoc: int
    matMaxDim: int
    matUMSpec: int
    matSiruta: int
    matCaen1: int
    matCaen2: int
    matRegJ: int
    matCharge: int
    matViews: int
    matDownloads: int
    matActive: int
    matTime: int


class LeafNode(t.TypedDict):
    ancestors: list[Context]
    matrixName: str
    periodicitati: list[str]
    surseDeDate: list[DataSources]
    definitie: str
    persoaneResponsabile: t.Any
    dimensionsMap: list[Dimension]
    intrerupere: t.Any
    continuareSerie: t.Any
    details: Details


class RequestBody(t.TypedDict):
    language: Language
    encQuery: str
    matCode: str
    nomJud: int
    nomLoc: int
    matMaxDim: int
    matUMSpec: int
    matSiruta: int
    matCaen1: int
    matCaen2: int
    matRegJ: int
    matCharge: int
    matViews: int
    matDownloads: int
    matActive: int
    matTime: int


class GISCO:
    class DatasetMetadata(t.TypedDict):
        pdf: str
        url: str
        xml: str

    class TitleMultilingual(t.TypedDict):
        de: str
        en: str
        fr: str

    class DatasetDetails(t.TypedDict):
        date: str
        documentation: str
        files: str
        hashtag: str
        metadata: GISCO.DatasetMetadata
        packages: str
        title: str
        titleMultilingual: GISCO.TitleMultilingual

    class DatasetFiles(t.TypedDict):
        csv: dict[str, str]
        geojson: dict[str, str]
        gpkg: dict[str, str]
        pbf: dict[str, str]
        shp: dict[str, str]
        svg: dict[str, str]
        topojson: dict[str, str]
