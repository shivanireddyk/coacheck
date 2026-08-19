"""coacheck: check supplier Certificates of Analysis against material specs.

    from coacheck import load_spec, check_document, render

    spec = load_spec("specs/ascorbic_acid.yaml")
    result = check_document(open("coa.txt").read(), spec)
    print(render(result))

The one rule worth knowing before using it: a result is only PASS when the
library can say why. Missing fields, low-confidence extractions and units it
cannot reconcile all come back as NEEDS_REVIEW, because a false pass sends bad
material to the floor and a false fail costs someone two minutes.
"""

from .check import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    CheckResult,
    Finding,
    Verdict,
    check_document,
    check_field,
)
from .extract import Extraction, extract_all, extract_field, text_from_pdf
from .report import as_record, render
from .spec import Limit, MaterialSpec, SpecError, load_spec, load_spec_text
from .units import (
    IncompatibleUnitsError,
    UnitError,
    UnknownUnitError,
    compatible,
    convert,
    known_units,
    to_canonical,
)

__version__ = "0.1.0"

__all__ = [
    "CheckResult",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "Extraction",
    "Finding",
    "IncompatibleUnitsError",
    "Limit",
    "MaterialSpec",
    "SpecError",
    "UnitError",
    "UnknownUnitError",
    "Verdict",
    "as_record",
    "check_document",
    "check_field",
    "compatible",
    "convert",
    "extract_all",
    "extract_field",
    "known_units",
    "load_spec",
    "load_spec_text",
    "render",
    "text_from_pdf",
    "to_canonical",
]
