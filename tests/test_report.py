import json
from pathlib import Path

from coacheck.check import Verdict, check_document
from coacheck.extract import ALIAS_CONFIDENCE
from coacheck.report import as_record, render
from coacheck.spec import load_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SPEC = load_spec(Path(__file__).resolve().parents[1] / "specs" / "ascorbic_acid.yaml")


def _result(name):
    return check_document((EXAMPLES / name).read_text(), SPEC)


class TestRender:
    def test_leads_with_the_verdict(self):
        text = render(_result("coa_out_of_spec.txt"), document="lot-0532.pdf")
        assert text.startswith("FAIL: Ascorbic Acid USP")
        assert "lot-0532.pdf" in text

    def test_failures_are_listed_before_passes(self):
        text = render(_result("coa_out_of_spec.txt"))
        assert text.index("FAIL - moisture") < text.index("PASS - assay")

    def test_a_failure_line_names_the_value_the_limit_and_the_source(self):
        text = render(_result("coa_out_of_spec.txt"))
        assert "0.62" in text
        assert "0.5" in text
        assert "Loss on Drying" in text

    def test_needs_review_explains_that_it_is_not_a_defect_finding(self):
        text = render(_result("coa_needs_review.txt"))
        assert "not passed automatically" in text
        assert "needs" in text.lower()

    def test_a_clean_pass_says_so_without_noise(self):
        text = render(_result("coa_clean.txt"))
        assert text.startswith("PASS:")
        assert "FAIL" not in text


class TestAuditRecord:
    def test_is_json_serialisable(self):
        record = as_record(_result("coa_out_of_spec.txt"), document="lot-0532.pdf",
                           spec_source="specs/ascorbic_acid.yaml")
        json.dumps(record)  # raises if anything is a Decimal or a dataclass

    def test_captures_what_is_needed_to_reconstruct_the_decision(self):
        record = as_record(_result("coa_out_of_spec.txt"), document="lot-0532.pdf",
                           spec_source="specs/ascorbic_acid.yaml")
        assert record["verdict"] == "FAIL"
        assert record["spec_source"] == "specs/ascorbic_acid.yaml"
        assert record["checked_at"]

        moisture = next(f for f in record["findings"] if f["field"] == "moisture")
        assert moisture["value"] == "0.62"
        assert moisture["unit"] == "%"
        assert moisture["limit"] == "<= 0.5 percent"
        assert "Loss on Drying" in moisture["source_text"]
        # Matched through an alias rather than the spec's own field name, so
        # the confidence recorded is the alias confidence, not the top one.
        assert moisture["confidence"] == str(ALIAS_CONFIDENCE)

    def test_records_every_field_including_the_ones_that_passed(self):
        record = as_record(_result("coa_clean.txt"))
        assert len(record["findings"]) == len(SPEC.limits)
        assert {f["verdict"] for f in record["findings"]} <= {
            v.value for v in Verdict
        }

    def test_an_absent_field_records_a_null_value_not_a_zero(self):
        record = as_record(_result("coa_needs_review.txt"))
        lead = next(f for f in record["findings"] if f["field"] == "lead")
        assert lead["value"] is None
        assert lead["verdict"] == "NEEDS_REVIEW"
