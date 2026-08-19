"""Compare extracted values against a spec, and escalate rather than guess.

The design rule this whole module exists to enforce:

    A false PASS sends out-of-spec material to the production floor.
    A false FAIL costs someone two minutes.

Those costs are not symmetric, so nothing here returns PASS unless it can say
why. Anything unclear returns NEEDS_REVIEW: a missing required field, a
low-confidence extraction, a unit that cannot be compared, or a
below-detection result whose bound does not settle the question.

NEEDS_REVIEW is not a failure of the tool. It is the tool doing the one thing
a human reviewer cannot do at scale, which is reading every certificate, and
then handing back only the ones that genuinely need judgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .extract import Extraction, extract_all
from .spec import Limit, MaterialSpec
from .units import IncompatibleUnitsError, UnitError, compatible, to_canonical

DEFAULT_CONFIDENCE_THRESHOLD = Decimal("0.70")


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class Finding:
    """One field's outcome, carrying the reason with it.

    The reason is not decoration. A result of False tells a receiving clerk
    nothing they can act on. "Moisture 0.62 percent exceeds maximum 0.50
    percent" tells them what to do next.
    """

    field: str
    verdict: Verdict
    reason: str
    extraction: Extraction | None = None
    limit: Limit | None = None

    def __str__(self) -> str:
        line = f"{self.verdict.value} - {self.reason}"
        if self.extraction is not None:
            line += f"\n    found in {self.extraction.cite()}"
        return line


@dataclass(frozen=True)
class CheckResult:
    """The disposition of one certificate against one spec."""

    material: str
    verdict: Verdict
    findings: tuple[Finding, ...]

    def by_verdict(self, verdict: Verdict) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.verdict is verdict)

    @property
    def passed(self) -> bool:
        """True only on a clean pass. Deliberately strict."""
        return self.verdict is Verdict.PASS


def _within(value: Decimal, limit: Limit) -> tuple[bool, str]:
    """Compare a canonicalised value against a canonicalised limit."""
    lo = to_canonical(limit.minimum, limit.unit) if limit.minimum is not None else None
    hi = to_canonical(limit.maximum, limit.unit) if limit.maximum is not None else None

    if hi is not None:
        over = value > hi if limit.inclusive else value >= hi
        if over:
            word = "exceeds maximum" if limit.inclusive else "is at or above the exclusive maximum"
            return False, f"{word} {limit.maximum} {limit.unit}"
    if lo is not None:
        under = value < lo if limit.inclusive else value <= lo
        if under:
            word = "is below minimum" if limit.inclusive else "is at or below the exclusive minimum"
            return False, f"{word} {limit.minimum} {limit.unit}"
    return True, f"within {limit.describe()}"


def _check_bounded(ex: Extraction, limit: Limit, bound: Decimal) -> Finding:
    """Handle a '<' or '>' result, where the true value is unknown.

    A '<0.01 ppm' lead result against a 0.5 ppm maximum passes: whatever the
    real number is, it is under the limit. The same result against a 0.005 ppm
    maximum settles nothing, so it escalates rather than being read as a pass.
    """
    hi = to_canonical(limit.maximum, limit.unit) if limit.maximum is not None else None
    lo = to_canonical(limit.minimum, limit.unit) if limit.minimum is not None else None

    if ex.qualifier == "<":
        if lo is not None:
            # Two-sided, or minimum-only. A "<" bound can never confirm the
            # minimum is met, so the only decidable outcome is a definite fail.
            if bound <= lo:
                return Finding(limit.field, Verdict.FAIL,
                               f"{limit.field} reported as <{ex.value} {ex.unit}, entirely below "
                               f"minimum {limit.minimum} {limit.unit}", ex, limit)
        elif hi is not None and bound <= hi:
            return Finding(limit.field, Verdict.PASS,
                           f"{limit.field} reported as <{ex.value} {ex.unit}, entirely below "
                           f"maximum {limit.maximum} {limit.unit}", ex, limit)
    elif ex.qualifier == ">":
        if hi is not None:
            if bound >= hi:
                return Finding(limit.field, Verdict.FAIL,
                               f"{limit.field} reported as >{ex.value} {ex.unit}, entirely above "
                               f"maximum {limit.maximum} {limit.unit}", ex, limit)
        elif lo is not None and bound >= lo:
            return Finding(limit.field, Verdict.PASS,
                           f"{limit.field} reported as >{ex.value} {ex.unit}, entirely above "
                           f"minimum {limit.minimum} {limit.unit}", ex, limit)

    return Finding(limit.field, Verdict.NEEDS_REVIEW,
                   f"{limit.field} reported as {ex.qualifier}{ex.value} {ex.unit}, which does "
                   f"not settle whether it meets {limit.describe()}", ex, limit)


def check_field(
    ex: Extraction | None,
    limit: Limit,
    threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Finding:
    """Decide one field. Every path that is not certain returns NEEDS_REVIEW."""
    if ex is None:
        if limit.required:
            return Finding(limit.field, Verdict.NEEDS_REVIEW,
                           f"{limit.field} is required by the spec but no value was found "
                           f"in the document", None, limit)
        return Finding(limit.field, Verdict.SKIPPED,
                       f"{limit.field} is optional and was not reported", None, limit)

    if ex.confidence < threshold:
        return Finding(limit.field, Verdict.NEEDS_REVIEW,
                       f"{limit.field} was extracted with confidence {ex.confidence}, below "
                       f"the threshold of {threshold}", ex, limit)

    if ex.not_detected:
        if limit.maximum is not None and limit.minimum is None:
            return Finding(limit.field, Verdict.PASS,
                           f"{limit.field} not detected, which satisfies "
                           f"{limit.describe()}", ex, limit)
        return Finding(limit.field, Verdict.NEEDS_REVIEW,
                       f"{limit.field} not detected, but the spec sets a minimum "
                       f"({limit.describe()}), so this needs a human", ex, limit)

    if ex.unit is None or ex.value is None:
        return Finding(limit.field, Verdict.NEEDS_REVIEW,
                       f"{limit.field} has no unit in the document, so it cannot be "
                       f"compared against {limit.describe()} without assuming one", ex, limit)

    try:
        # Both sides are reduced to the same family's canonical unit before any
        # comparison. Checking the family explicitly matters: without it, a
        # microbial count in cfu/g would be compared against a heavy metal
        # limit in ppm and the arithmetic would succeed while meaning nothing.
        if not compatible(ex.unit, limit.unit):
            raise IncompatibleUnitsError(
                f"document reports {ex.unit} but the spec limit is in {limit.unit}; "
                f"these measure different things and were not compared"
            )
        value = to_canonical(ex.value, ex.unit)
        if ex.qualifier:
            return _check_bounded(ex, limit, value)
        ok, why = _within(value, limit)
    except UnitError as exc:
        return Finding(limit.field, Verdict.NEEDS_REVIEW,
                       f"{limit.field}: {exc}", ex, limit)

    verdict = Verdict.PASS if ok else Verdict.FAIL
    return Finding(limit.field, verdict,
                   f"{limit.field} {ex.value} {ex.unit} {why}", ex, limit)


def check_document(
    text: str,
    spec: MaterialSpec,
    threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD,
) -> CheckResult:
    """Check a certificate's text against a material spec."""
    extractions = extract_all(text, spec)
    findings = tuple(
        check_field(extractions.get(limit.field), limit, threshold) for limit in spec.limits
    )

    verdicts = {f.verdict for f in findings}
    if Verdict.FAIL in verdicts:
        overall = Verdict.FAIL
    elif Verdict.NEEDS_REVIEW in verdicts:
        overall = Verdict.NEEDS_REVIEW
    else:
        overall = Verdict.PASS

    return CheckResult(material=spec.material, verdict=overall, findings=findings)
