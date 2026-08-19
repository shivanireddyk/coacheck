"""Pull measured values out of a certificate, with a confidence on each one.

Extraction is where this project lives or dies, so it is built to be honest
about what it does not know. Every extraction carries a confidence and the
text it came from. Nothing is returned as certain because it happened to
parse.

Three things certificates do that a naive parser gets wrong:

* They use different names for the same test. "Moisture" and "Loss on Drying"
  are the same field to a quality team. Aliases live in the spec.
* They report below-detection results as "<0.01 ppm" or "ND". A "<" result is
  not a number, it is a bound, and whether it passes depends on the limit. It
  is carried through as a qualifier rather than flattened to a number.
* They put the unit somewhere other than next to the value. When the unit is
  missing, this module does not assume the spec's unit. It lowers confidence
  and lets the checker escalate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .spec import Limit, MaterialSpec

# A number with optional thousands separators, optionally preceded by a
# less-than or greater-than qualifier.
_VALUE = re.compile(
    r"(?P<qual>[<>≤≥]|less\s+than|greater\s+than)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>%|[A-Za-zµμ]+(?:\s*/\s*[A-Za-z]+)?)?",
    re.IGNORECASE,
)

_NOT_DETECTED = re.compile(r"\b(not\s+detected|none\s+detected|n\.?d\.?)\b", re.IGNORECASE)

# Phrases that introduce a printed specification rather than a second result.
# Certificates almost always print the result and the acceptance criterion on
# the same line, so a bare "more than one number here" rule would flag every
# well-formed document. These markers separate the two cases.
_SPEC_MARKER = re.compile(
    r"(nmt|nlt|not\s+more\s+than|not\s+less\s+than|\bmax\b|\bmin\b|"
    r"specification|\bto\b|\d\s*[-–]\s*\d)",
    re.IGNORECASE,
)

HIGH_CONFIDENCE = Decimal("0.90")
ALIAS_CONFIDENCE = Decimal("0.80")
NO_UNIT_CONFIDENCE = Decimal("0.50")
AMBIGUOUS_CONFIDENCE = Decimal("0.40")


@dataclass(frozen=True)
class Extraction:
    """One value found in the document, with everything needed to defend it."""

    field: str
    value: Decimal | None
    unit: str | None
    confidence: Decimal
    source: str
    qualifier: str | None = None
    not_detected: bool = False

    def cite(self) -> str:
        """Where this came from, short enough to put in a report line."""
        snippet = " ".join(self.source.split())[:70]
        return f'"{snippet}" (confidence {self.confidence})'


def _normalise_qualifier(raw: str | None) -> str | None:
    if not raw:
        return None
    token = raw.strip().lower()
    if token in {"<", "≤", "less than"}:
        return "<"
    if token in {">", "≥", "greater than"}:
        return ">"
    return None


def _find_line(text: str, label: str) -> str | None:
    """Return the line containing the label, matched on a word boundary."""
    pattern = re.compile(r"\b" + re.escape(label) + r"\b", re.IGNORECASE)
    for line in text.splitlines():
        if pattern.search(line):
            return line
    return None


def extract_field(text: str, limit: Limit) -> Extraction | None:
    """Find one field's value, trying the spec name first, then aliases."""
    for position, name in enumerate(limit.names()):
        line = _find_line(text, name)
        if line is None:
            continue

        after = line[line.lower().index(name.lower()) + len(name):]
        matches = list(_VALUE.finditer(after))
        base = HIGH_CONFIDENCE if position == 0 else ALIAS_CONFIDENCE

        # "Arsenic   Not detected   NMT 0.2 ppm" is a not-detected result, not
        # a reading of 0.2 ppm. Whichever comes first after the label is the
        # result; anything after it belongs to the printed specification.
        nd = _NOT_DETECTED.search(after)
        if nd and (not matches or nd.start() < matches[0].start()):
            return Extraction(
                field=limit.field,
                value=None,
                unit=None,
                confidence=base,
                source=line,
                not_detected=True,
            )

        if not matches:
            continue

        match = matches[0]
        try:
            value = Decimal(match.group("num").replace(",", ""))
        except InvalidOperation:
            continue

        unit = match.group("unit")
        unit = unit.replace(" ", "") if unit else None

        confidence = base
        if unit is None:
            # The unit is genuinely absent. Assuming the spec's unit here is
            # the single most dangerous shortcut available, so instead the
            # confidence drops far enough that the checker will escalate.
            confidence = NO_UNIT_CONFIDENCE
        elif len(matches) > 1 and not _SPEC_MARKER.search(after[match.end():]):
            # More than one number after the label, and nothing marking the
            # extras as a printed specification. It could be a second column,
            # a repeated test, or a range. A human should look rather than the
            # parser picking the leftmost and hoping.
            confidence = min(confidence, AMBIGUOUS_CONFIDENCE)

        return Extraction(
            field=limit.field,
            value=value,
            unit=unit,
            confidence=confidence,
            source=line,
            qualifier=_normalise_qualifier(match.group("qual")),
        )
    return None


def extract_all(text: str, spec: MaterialSpec) -> dict[str, Extraction]:
    """Extract every field the spec asks about. Missing fields are absent."""
    found: dict[str, Extraction] = {}
    for limit in spec.limits:
        extraction = extract_field(text, limit)
        if extraction is not None:
            found[limit.field] = extraction
    return found


def text_from_pdf(path: str) -> str:
    """Read a native-text PDF. Scans are out of scope and say so.

    OCR is deliberately not attempted. A scanned certificate silently producing
    an empty string would look like a document with no results, so this raises
    instead.
    """
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError(
            f"{path} contains no selectable text. It is probably a scan. "
            f"OCR is out of scope for this version, and returning an empty "
            f"result would look like a certificate with no findings."
        )
    return text
