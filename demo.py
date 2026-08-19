"""Run the three example certificates against the shipped spec.

    python demo.py

One passes, one fails on a real out-of-spec value, and one cannot be decided
without a person. The third is the interesting one.
"""

from pathlib import Path

from coacheck import as_record, check_document, load_spec, render

HERE = Path(__file__).parent
SPEC_PATH = HERE / "specs" / "ascorbic_acid.yaml"


def main() -> None:
    spec = load_spec(SPEC_PATH)
    print(f"Spec: {spec.material} ({len(spec.limits)} criteria)\n")

    for name in ("coa_clean.txt", "coa_out_of_spec.txt", "coa_needs_review.txt"):
        path = HERE / "examples" / name
        result = check_document(path.read_text(encoding="utf-8"), spec)
        print(render(result, document=name))
        print()

    print("-" * 72)
    print("Audit record for the failing lot, as it would be stored:\n")
    failing = check_document(
        (HERE / "examples" / "coa_out_of_spec.txt").read_text(encoding="utf-8"), spec
    )
    record = as_record(failing, document="coa_out_of_spec.txt", spec_source=str(SPEC_PATH.name))
    for finding in record["findings"]:
        if finding["verdict"] in ("FAIL", "NEEDS_REVIEW"):
            print(f"  {finding['field']}: {finding['verdict']}")
            print(f"    value      {finding['value']} {finding['unit'] or ''}")
            print(f"    limit      {finding['limit']}")
            print(f"    confidence {finding['confidence']}")
            print(f"    read from  {finding['source_text']}")


if __name__ == "__main__":
    main()
