"""Turn a result into something a person can act on, and an auditor can keep.

Two renderings, for two different readers.

`render` is for the person in receiving who has to decide what to do with a
pallet. It leads with the verdict, names the failing field, quotes the limit,
and shows the text the value was read from, so they can check the document
without reading any code.

`as_record` is for the audit trail. In a regulated manufacturing environment
"the tool said it was fine" is not evidence. The record captures what was
checked, against which spec, what was extracted, with what confidence, and
what was decided, so a decision can be reconstructed months later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .check import CheckResult, Verdict

_ORDER = {Verdict.FAIL: 0, Verdict.NEEDS_REVIEW: 1, Verdict.PASS: 2, Verdict.SKIPPED: 3}


def render(result: CheckResult, document: str = "") -> str:
    """A plain-text report, worst news first."""
    header = f"{result.verdict.value}: {result.material}"
    if document:
        header += f"  [{document}]"
    lines = [header, "=" * len(header)]

    for finding in sorted(result.findings, key=lambda f: (_ORDER[f.verdict], f.field)):
        lines.append(str(finding))

    counts = {
        v.value: len(result.by_verdict(v))
        for v in (Verdict.PASS, Verdict.FAIL, Verdict.NEEDS_REVIEW, Verdict.SKIPPED)
    }
    lines.append("")
    lines.append(
        "  ".join(f"{name}: {n}" for name, n in counts.items() if n)
    )

    if result.verdict is Verdict.NEEDS_REVIEW:
        lines.append(
            "This lot was not passed automatically. Nothing above is a defect "
            "finding; it means the document did not answer the question clearly "
            "enough to decide without a person."
        )
    return "\n".join(lines)


def as_record(result: CheckResult, document: str = "", spec_source: str = "") -> dict[str, Any]:
    """A serialisable record of the decision and everything behind it."""
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "document": document,
        "material": result.material,
        "spec_source": spec_source,
        "verdict": result.verdict.value,
        "findings": [
            {
                "field": f.field,
                "verdict": f.verdict.value,
                "reason": f.reason,
                "limit": f.limit.describe() if f.limit else None,
                "value": (
                    str(f.extraction.value)
                    if f.extraction and f.extraction.value is not None
                    else None
                ),
                "unit": f.extraction.unit if f.extraction else None,
                "qualifier": f.extraction.qualifier if f.extraction else None,
                "confidence": str(f.extraction.confidence) if f.extraction else None,
                "source_text": " ".join(f.extraction.source.split()) if f.extraction else None,
            }
            for f in result.findings
        ],
    }
