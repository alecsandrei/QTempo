from __future__ import annotations

import collections
import collections.abc as c
import re
import typing as t
import unicodedata

from .enums import Level

if t.TYPE_CHECKING:
    from ._typing import Choice

# Romanian NUTS 2024 names, from GISCO's NUTS_AT_2024.csv
NUTS_NAMES = {
    'RO': 'România',
    'RO1': 'Macroregiunea Unu',
    'RO11': 'Nord-Vest',
    'RO111': 'Bihor',
    'RO112': 'Bistriţa-Năsăud',
    'RO113': 'Cluj',
    'RO114': 'Maramureş',
    'RO115': 'Satu Mare',
    'RO116': 'Sălaj',
    'RO12': 'Centru',
    'RO121': 'Alba',
    'RO122': 'Braşov',
    'RO123': 'Covasna',
    'RO124': 'Harghita',
    'RO125': 'Mureş',
    'RO126': 'Sibiu',
    'RO2': 'Macroregiunea Doi',
    'RO21': 'Nord-Est',
    'RO211': 'Bacău',
    'RO212': 'Botoşani',
    'RO213': 'Iaşi',
    'RO214': 'Neamţ',
    'RO215': 'Suceava',
    'RO216': 'Vaslui',
    'RO22': 'Sud-Est',
    'RO221': 'Brăila',
    'RO222': 'Buzău',
    'RO223': 'Constanţa',
    'RO224': 'Galaţi',
    'RO225': 'Tulcea',
    'RO226': 'Vrancea',
    'RO3': 'Macroregiunea Trei',
    'RO31': 'Sud-Muntenia',
    'RO311': 'Argeş',
    'RO312': 'Călăraşi',
    'RO313': 'Dâmboviţa',
    'RO314': 'Giurgiu',
    'RO315': 'Ialomiţa',
    'RO316': 'Prahova',
    'RO317': 'Teleorman',
    'RO32': 'Bucureşti-Ilfov',
    'RO321': 'Bucureşti',
    'RO322': 'Ilfov',
    'RO4': 'Macroregiunea Patru',
    'RO41': 'Sud-Vest Oltenia',
    'RO411': 'Dolj',
    'RO412': 'Gorj',
    'RO413': 'Mehedinţi',
    'RO414': 'Olt',
    'RO415': 'Vâlcea',
    'RO42': 'Vest',
    'RO421': 'Arad',
    'RO422': 'Caraş-Severin',
    'RO423': 'Hunedoara',
    'RO424': 'Timiş',
}

# TEMPO labels which differ from the NUTS names after normalization.
# 'Mun. Bucuresti -incl. SAI' (Bucharest and the Ilfov Agricultural Sector,
# i.e. today's Bucharest and Ilfov) is left unmapped, as no unit matches it.
NUTS_ALIASES = {
    'TOTAL': 'RO',
    'Nivel national': 'RO',
    'Municipiul Bucuresti': 'RO321',
}

# A dimension is geographic when at least this share of its options are units
GEOGRAPHIC_SHARE = 0.6

# Only region prefixes are removed, as many municipalities share the name of
# their county (e.g. 'Municipiul Arad' is not the county of Arad)
NAME_PREFIX = re.compile(r'^REGIUNEA\s+')
NAME_SEPARATORS = re.compile(r'[\s-]+')


def normalize(label: str) -> str:
    """Normalizes a unit name, e.g. 'Regiunea BUCURESTI - ILFOV' and
    'Bucureşti-Ilfov' both become 'BUCURESTI-ILFOV'."""
    decomposed = unicodedata.normalize('NFKD', label)
    stripped = ''.join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return NAME_SEPARATORS.sub(
        '-', NAME_PREFIX.sub('', stripped.strip().upper())
    )


NUTS_RO = {normalize(name): nuts_id for nuts_id, name in NUTS_NAMES.items()} | {
    normalize(label): nuts_id for label, nuts_id in NUTS_ALIASES.items()
}


class TerritorialUnit(t.NamedTuple):
    level: Level
    code: str
    label: str

    @classmethod
    def from_siruta_label(cls, label: str) -> t.Self:
        siruta = re.fullmatch(r'(\d+)\s(.+)', label)
        if siruta is None:
            raise ValueError(f'Failed to parse SIRUTA from {label!r}')
        return cls(Level.LOCALITY, siruta.group(1), label)

    @classmethod
    def from_nuts_label(cls, label: str, ro_label: str) -> t.Self | None:
        """Matches the Romanian label against the NUTS names."""
        nuts_id = NUTS_RO.get(normalize(ro_label))
        if nuts_id is None:
            return None
        return cls(Level.from_nuts_id(nuts_id), nuts_id, label)


def resolve_dimension(
    options: c.Sequence[Choice], ro_options: c.Sequence[Choice]
) -> dict[str, TerritorialUnit | None] | None:
    """Maps the option labels of a dimension to NUTS units.

    The Romanian options are used for matching, as the labels in other
    languages (e.g. 'NORTH - WEST') are translated. Labels which resolve to
    the same unit are ambiguous and left unmapped. Returns None if the
    dimension is not geographic.
    """
    ro_labels = {option['nomItemId']: option['label'] for option in ro_options}
    units: dict[str, TerritorialUnit | None] = {}
    for option in options:
        label = option['label'].strip()
        ro_label = ro_labels.get(option['nomItemId'], label)
        units[label] = TerritorialUnit.from_nuts_label(label, ro_label)
    codes = collections.Counter(
        unit.code for unit in units.values() if unit is not None
    )
    for label, unit in units.items():
        if unit is not None and codes[unit.code] > 1:
            units[label] = None
    resolved = [unit for unit in units.values() if unit is not None]
    if len(resolved) < GEOGRAPHIC_SHARE * len(units) or all(
        unit.level is Level.COUNTRY for unit in resolved
    ):
        # A lone 'TOTAL' option is not enough to call a dimension geographic
        return None
    return units
