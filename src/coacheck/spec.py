"""Material specifications, held as data rather than code.

A spec says what an acceptable lot of a raw material looks like: assay between
98 and 102 percent, lead no more than 0.5 ppm, and so on. Specs change. They
change when a supplier changes, when a regulator updates a limit, and when
someone in quality decides a tolerance was too loose.

So specs live in YAML files, not in Python. Changing a limit is a data edit
that an operations person can make and review, not a code change that needs a
developer and a deploy. That single decision is most of why this library is
usable by the people who actually own the specs.

Every spec is validated on load. A spec file with a typo, a missing unit, or a
minimum above its maximum fails immediately and loudly, because a spec that
silently does not mean what its author thought is worse than no spec at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .units import UnknownUnitError, family_of

_LIMIT_KEYS = {"field", "unit", "min", "max", "required", "inclusive", "aliases"}
_SPEC_KEYS = {"material", "supplier", "specs"}


class SpecError(ValueError):
    """The spec file is not usable. Never swallowed, never defaulted around."""


@dataclass(frozen=True)
class Limit:
    """One acceptance criterion for one measured field."""

    field: str
    unit: str
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    required: bool = True
    inclusive: bool = True
    aliases: tuple[str, ...] = ()

    def describe(self) -> str:
        """A human-readable rendering of the limit, for report lines."""
        op_lo = ">=" if self.inclusive else ">"
        op_hi = "<=" if self.inclusive else "<"
        if self.minimum is not None and self.maximum is not None:
            return f"{self.minimum} to {self.maximum} {self.unit}"
        if self.maximum is not None:
            return f"{op_hi} {self.maximum} {self.unit}"
        return f"{op_lo} {self.minimum} {self.unit}"

    def names(self) -> tuple[str, ...]:
        """The field name plus any alternative spellings suppliers use."""
        return (self.field,) + self.aliases


@dataclass(frozen=True)
class MaterialSpec:
    """The full acceptance criteria for one material."""

    material: str
    supplier: str
    limits: tuple[Limit, ...] = dc_field(default_factory=tuple)

    def limit_for(self, name: str) -> Limit | None:
        """Find the limit whose field name or alias matches, case-insensitively."""
        wanted = name.strip().lower()
        for limit in self.limits:
            if any(n.strip().lower() == wanted for n in limit.names()):
                return limit
        return None

    def required_fields(self) -> tuple[str, ...]:
        return tuple(lim.field for lim in self.limits if lim.required)


def _decimal_or_none(raw: Any, where: str) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, float):
        raise SpecError(
            f"{where}: write limits as strings or integers, not floats. "
            f'Use "0.5" rather than 0.5 so the value is exact in the file '
            f"and exact in the comparison."
        )
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise SpecError(f"{where}: {raw!r} is not a number") from None


def _build_limit(raw: Any, index: int) -> Limit:
    where = f"specs[{index}]"
    if not isinstance(raw, dict):
        raise SpecError(f"{where}: each entry must be a mapping, got {type(raw).__name__}")

    unknown = set(raw) - _LIMIT_KEYS
    if unknown:
        raise SpecError(
            f"{where}: unknown key(s) {sorted(unknown)}. Allowed: {sorted(_LIMIT_KEYS)}. "
            f"A misspelled key would otherwise be ignored and the limit would "
            f"not do what its author intended."
        )

    name = raw.get("field")
    if not name or not isinstance(name, str):
        raise SpecError(f"{where}: 'field' is required and must be a non-empty string")

    unit = raw.get("unit")
    if unit is None:
        raise SpecError(
            f"{where} ({name}): 'unit' is required. A limit without a unit cannot "
            f"be compared against a measured value."
        )
    try:
        family_of(str(unit))
    except UnknownUnitError as exc:
        raise SpecError(f"{where} ({name}): {exc}") from None

    minimum = _decimal_or_none(raw.get("min"), f"{where} ({name}) min")
    maximum = _decimal_or_none(raw.get("max"), f"{where} ({name}) max")
    if minimum is None and maximum is None:
        raise SpecError(f"{where} ({name}): needs at least one of 'min' or 'max'")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise SpecError(f"{where} ({name}): min {minimum} is above max {maximum}")

    aliases = raw.get("aliases", []) or []
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise SpecError(f"{where} ({name}): 'aliases' must be a list of strings")

    return Limit(
        field=name,
        unit=str(unit),
        minimum=minimum,
        maximum=maximum,
        required=bool(raw.get("required", True)),
        inclusive=bool(raw.get("inclusive", True)),
        aliases=tuple(aliases),
    )


def load_spec_text(text: str) -> MaterialSpec:
    """Parse and validate a spec from YAML text."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"spec is not valid YAML: {exc}") from None

    if not isinstance(data, dict):
        raise SpecError("spec must be a YAML mapping at the top level")

    unknown = set(data) - _SPEC_KEYS
    if unknown:
        raise SpecError(f"unknown top-level key(s) {sorted(unknown)}")

    material = data.get("material")
    if not material or not isinstance(material, str):
        raise SpecError("'material' is required and must be a non-empty string")

    entries = data.get("specs")
    if not isinstance(entries, list) or not entries:
        raise SpecError("'specs' is required and must be a non-empty list")

    limits = tuple(_build_limit(raw, i) for i, raw in enumerate(entries))

    seen: set[str] = set()
    for lim in limits:
        for name in lim.names():
            key = name.strip().lower()
            if key in seen:
                raise SpecError(
                    f"duplicate field or alias {name!r}. Two limits matching the "
                    f"same name means the second one silently never applies."
                )
            seen.add(key)

    return MaterialSpec(
        material=material,
        supplier=str(data.get("supplier", "Any")),
        limits=limits,
    )


def load_spec(path: str | Path) -> MaterialSpec:
    """Load and validate a spec from a YAML file on disk."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"cannot read spec file {p}: {exc}") from None
    return load_spec_text(text)
