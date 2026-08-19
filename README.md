# coacheck

Check supplier Certificates of Analysis against material specifications, and
escalate rather than guess.

[![CI](https://github.com/shivanireddyk/coacheck/actions/workflows/ci.yml/badge.svg)](https://github.com/shivanireddyk/coacheck/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

When a lot of raw material arrives, the supplier sends a Certificate of
Analysis saying what is in it. Someone in receiving compares it against the
spec before the material goes anywhere near production. Per lot, per supplier,
by hand.

This library does the comparison, and is careful about the cases where it
cannot.

## The rule the whole design follows

> A false PASS sends out-of-spec material to the production floor.
> A false FAIL costs someone two minutes.

Those costs are not symmetric. So nothing here returns `PASS` unless it can say
why. A missing required field, a low-confidence extraction, a unit it cannot
reconcile, and a below-detection result whose bound does not settle the
question all come back as `NEEDS_REVIEW`.

`NEEDS_REVIEW` is not the tool failing. It is the tool reading every
certificate so a person only has to read the ones that need judgement.

## Try it

```bash
git clone https://github.com/shivanireddyk/coacheck
cd coacheck
pip install -e ".[dev]"
python demo.py
pytest
```

```python
from coacheck import load_spec, check_document, render

spec = load_spec("specs/ascorbic_acid.yaml")
result = check_document(open("examples/coa_out_of_spec.txt").read(), spec)
print(render(result))
```

```
FAIL: Ascorbic Acid USP
=======================
FAIL - moisture 0.62 % exceeds maximum 0.5 percent
    found in "Loss on Drying 0.62 % NMT 0.5 %" (confidence 0.80)
PASS - assay 99.4 % within 98.0 to 102.0 percent
    found in "Assay 99.4 % 98.0 - 102.0 %" (confidence 0.90)
...
```

Not `{"pass": false}`. A receiving clerk can act on the first one without
reading any code.

## Specs are data, not code

```yaml
material: Ascorbic Acid USP
specs:
  - field: moisture
    unit: percent
    max: "0.5"
    aliases: ["loss on drying", "water content", "karl fischer"]

  - field: lead
    unit: ppm
    max: "0.5"
```

Changing a limit is a document edit that quality owns and reviews. It is not a
code change and it does not need a deploy. Every spec is validated on load: a
misspelled key, a missing unit, a minimum above its maximum, or a duplicate
field all fail immediately, because a spec that silently does not mean what its
author intended is worse than no spec at all.

## Four decisions worth explaining

**Units are a correctness problem, not a formatting one.** 0.5 ppm and 500 ppb
are the same quantity. A comparison that ignores units can pass bad material.
Values and limits are both reduced to a canonical unit before comparison, and
units from different families are never compared: a microbial count in cfu/g
checked against a heavy-metal limit in ppm raises rather than producing
arithmetic that succeeds and means nothing. Unknown units raise too.

**Decimal, never float.** A limit of 0.5 compared against a float-parsed
0.5000000001 fails for no reason, and the reverse case passes something it
should not. Floats are rejected at the boundary, in the API and in the spec
files, so a value on the limit is exactly on the limit.

**Below-detection results are bounds, not numbers.** A lead result of
`<0.05 ppm` against a 0.5 ppm maximum passes: wherever the true value sits, it
is under the limit. The same result against a 0.005 ppm maximum settles
nothing and escalates. And a `<` bound can never confirm a *minimum* is met,
so `<50 %` against a 98 to 102 % assay spec fails rather than passing because
50 happens to be below 102. That last case was a real bug, caught by a test.

**Every result explains itself.** Each finding names the field, the value, the
limit, and the line of the document it was read from, with a confidence.
`as_record()` returns the same thing as a JSON-serialisable audit record,
because in regulated manufacturing "the tool said it was fine" is not evidence.

## Deliberately out of scope

Knowing what to leave out is part of the design, so it is written down rather
than left as a gap:

- **Inbox monitoring.** This checks a document you hand it. Wiring it to a
  mailbox is a separate concern with its own idempotency and alerting
  questions.
- **OCR.** Native-text PDFs only. A scanned certificate raises instead of
  returning an empty result, because an empty result looks like a certificate
  with no findings.
- **LLM extraction.** The deterministic path is the whole v1. If a model is
  ever added it belongs behind the same rule as everything else: it may
  propose a value for a field the parser could not find, its output is
  validated against the expected type and unit, and anything it is unsure
  about is `NEEDS_REVIEW`. A model returning `99.2%` for a field expecting
  CFU/g is rejected, not trusted.
- **A database.** Results come back as records. Where they are stored is the
  caller's decision.

## Testing

105 tests, 94% line coverage, run on Python 3.10 through 3.12.

The ones that carry weight are the boundary cases: exactly on an inclusive
limit, exactly on an exclusive limit, a missing required field returning
`NEEDS_REVIEW` and never `PASS`, unit conversion changing a verdict, a
not-detected result printed next to its specification, and junk input never
passing.

```bash
pytest -q
pytest --cov=coacheck --cov-report=term-missing
```

## License

MIT. See [LICENSE](LICENSE).
