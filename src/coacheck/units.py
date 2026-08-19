"""Unit normalisation for Certificate of Analysis values.

Comparing a measured value against a spec limit is only meaningful when both
are in the same unit. 0.5 ppm and 500 ppb are the same quantity; 0.05 percent
and 500 ppm are the same quantity. A comparison that ignores units is not a
formatting bug, it is a correctness bug that can silently pass out-of-spec
material.

Two rules are enforced here rather than assumed:

1. Units in different families are never compared. Converting cfu/g to ppm is
   not a rounding question, it is nonsense, so it raises instead of guessing.
2. Unknown units raise. Silently treating an unrecognised unit as "probably
   the same as the spec" is exactly the failure this module exists to prevent.

All arithmetic uses Decimal. Floats are rejected at the boundary because a
limit of 0.5 compared against a float-parsed 0.5000000001 fails for no reason,
and the reverse case passes something it should not.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final


class UnitError(ValueError):
    """Base class for unit problems."""


class UnknownUnitError(UnitError):
    """The unit string was not recognised. We refuse to guess."""


class IncompatibleUnitsError(UnitError):
    """Two units describe different physical quantities."""


MASS_FRACTION: Final = "mass_fraction"
CFU_PER_MASS: Final = "cfu_per_mass"
CFU_PER_VOLUME: Final = "cfu_per_volume"
COUNT: Final = "count"

# unit alias -> (family, multiplier to the family's canonical unit)
# Canonical units: mass fraction -> ppm, cfu -> cfu/g and cfu/mL, count -> 1
_UNITS: Final[dict[str, tuple[str, Decimal]]] = {
    "percent": (MASS_FRACTION, Decimal("10000")),
    "%": (MASS_FRACTION, Decimal("10000")),
    "pct": (MASS_FRACTION, Decimal("10000")),
    "g/100g": (MASS_FRACTION, Decimal("10000")),
    "ppm": (MASS_FRACTION, Decimal("1")),
    "mg/kg": (MASS_FRACTION, Decimal("1")),
    "ug/g": (MASS_FRACTION, Decimal("1")),
    "ppb": (MASS_FRACTION, Decimal("0.001")),
    "ug/kg": (MASS_FRACTION, Decimal("0.001")),
    "ng/g": (MASS_FRACTION, Decimal("0.001")),
    "mg/g": (MASS_FRACTION, Decimal("1000")),
    "cfu/g": (CFU_PER_MASS, Decimal("1")),
    "cfu/kg": (CFU_PER_MASS, Decimal("0.001")),
    "cfu/ml": (CFU_PER_VOLUME, Decimal("1")),
    "cfu/l": (CFU_PER_VOLUME, Decimal("0.001")),
    "count": (COUNT, Decimal("1")),
    "": (COUNT, Decimal("1")),
}


def canonicalise_unit(unit: str) -> str:
    """Fold a written unit down to a lookup key.

    Handles the spellings that actually turn up on certificates: casing,
    surrounding whitespace, micro sign vs the letter u, and CFU/G vs cfu/g.
    """
    if not isinstance(unit, str):
        raise UnknownUnitError(f"unit must be a string, got {type(unit).__name__}")
    cleaned = unit.strip().lower().replace("µ", "u").replace("μ", "u")
    cleaned = cleaned.replace(" ", "")
    return cleaned


def family_of(unit: str) -> str:
    """Return the physical quantity family a unit belongs to."""
    key = canonicalise_unit(unit)
    try:
        return _UNITS[key][0]
    except KeyError:
        raise UnknownUnitError(
            f"unrecognised unit {unit!r}. Add it to coacheck.units rather than "
            f"letting it through, because an unrecognised unit compared as if "
            f"it matched is how bad material passes."
        ) from None


def compatible(left: str, right: str) -> bool:
    """True when two units describe the same physical quantity."""
    return family_of(left) == family_of(right)


def to_canonical(value: Decimal, unit: str) -> Decimal:
    """Convert a value into its family's canonical unit.

    Raises TypeError on float input. This is deliberate and matches the rest
    of the library: money and measurement both deserve exact arithmetic, and
    accepting a float here would quietly reintroduce binary rounding into
    every comparison downstream.
    """
    if isinstance(value, float):
        raise TypeError(
            "value must be Decimal, int or str, not float. Use "
            'Decimal("0.5") rather than 0.5 so the comparison is exact.'
        )
    if not isinstance(value, Decimal):
        value = Decimal(value)
    key = canonicalise_unit(unit)
    if key not in _UNITS:
        raise UnknownUnitError(f"unrecognised unit {unit!r}")
    return value * _UNITS[key][1]


def convert(value: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """Convert between two units of the same family.

    Raises IncompatibleUnitsError across families rather than returning a
    number that looks plausible.
    """
    src, dst = family_of(from_unit), family_of(to_unit)
    if src != dst:
        raise IncompatibleUnitsError(
            f"cannot convert {from_unit!r} ({src}) to {to_unit!r} ({dst}). "
            f"These are different physical quantities."
        )
    canonical = to_canonical(value, from_unit)
    return canonical / _UNITS[canonicalise_unit(to_unit)][1]


def known_units() -> tuple[str, ...]:
    """Every unit spelling the library accepts, for error messages and docs."""
    return tuple(sorted(u for u in _UNITS if u))
