from __future__ import annotations

import pytest

from qtempo.enums import Level


@pytest.mark.parametrize(
    ('nuts_id', 'level'),
    [
        ('RO', Level.COUNTRY),
        ('RO1', Level.MACROREGION),
        ('RO11', Level.REGION),
        ('RO111', Level.COUNTY),
    ],
)
def test_level_from_nuts_id(nuts_id: str, level: Level) -> None:
    assert Level.from_nuts_id(nuts_id) is level


def test_only_localities_are_not_nuts() -> None:
    assert [level for level in Level if not level.is_nuts] == [Level.LOCALITY]
