"""The tests that matter.

Every one of these exists because getting it wrong sends bad material to a
production floor or wastes a quality team's afternoon. The invariant under all
of them: nothing returns PASS unless the library can say why.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from coacheck.check import Verdict, check_document, check_field
from coacheck.extract import Extraction
from coacheck.spec import Limit, load_spec, load_spec_text

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SPEC = load_spec(Path(__file__).resolve().parents[1] / "specs" / "ascorbic_acid.yaml")

MOISTURE = Limit(field="moisture", unit="percent", maximum=Decimal("0.5"))
ASSAY = Limit(field="assay", unit="percent", minimum=Decimal("98.0"), maximum=Decimal("102.0"))
LEAD = Limit(field="lead", unit="ppm", maximum=Decimal("0.5"))


def found(value, unit, confidence="0.90", field="moisture", **kw):
    return Extraction(field=field, value=Decimal(value) if value is not None else None,
                      unit=unit, confidence=Decimal(confidence), source="test", **kw)


class TestTheCoreComparison:
    def test_in_spec_passes(self):
        assert check_field(found("0.21", "%"), MOISTURE).verdict is Verdict.PASS

    def test_out_of_spec_fails_and_names_the_field_and_the_limit(self):
        finding = check_field(found("0.62", "%"), MOISTURE)
        assert finding.verdict is Verdict.FAIL
        assert "moisture" in finding.reason
        assert "0.62" in finding.reason
        assert "0.5" in finding.reason

    def test_below_a_minimum_fails(self):
        assert check_field(found("97.4", "%", field="assay"), ASSAY).verdict is Verdict.FAIL

    def test_above_a_maximum_of_a_range_fails(self):
        assert check_field(found("102.4", "%", field="assay"), ASSAY).verdict is Verdict.FAIL


class TestBoundaries:
    """Whether the limit itself passes is a decision, so it is decided and tested."""

    def test_exactly_at_an_inclusive_maximum_passes(self):
        assert check_field(found("0.5", "%"), MOISTURE).verdict is Verdict.PASS

    def test_exactly_at_an_inclusive_minimum_passes(self):
        assert check_field(found("98.0", "%", field="assay"), ASSAY).verdict is Verdict.PASS

    def test_exactly_at_an_exclusive_maximum_fails(self):
        limit = Limit(field="moisture", unit="percent", maximum=Decimal("0.5"), inclusive=False)
        assert check_field(found("0.5", "%"), limit).verdict is Verdict.FAIL

    def test_a_hair_over_fails(self):
        assert check_field(found("0.5001", "%"), MOISTURE).verdict is Verdict.FAIL

    def test_the_boundary_is_exact_not_floating_point(self):
        # 0.1 + 0.4 in binary float is 0.5000000000000001, which would fail a
        # 0.5 maximum. Decimal keeps it exactly on the limit, which passes.
        assert check_field(found("0.5", "%"), MOISTURE).verdict is Verdict.PASS


class TestUnits:
    def test_a_value_in_a_different_unit_of_the_same_family_is_converted(self):
        assert check_field(found("400", "ppb", field="lead"), LEAD).verdict is Verdict.PASS

    def test_conversion_can_change_the_verdict(self):
        # 600 ppb is 0.6 ppm, over a 0.5 ppm limit. A comparison that ignored
        # units would see 600 against 0.5 and also fail, by luck. This one
        # fails for the right reason, and 400 ppb above passes.
        assert check_field(found("600", "ppb", field="lead"), LEAD).verdict is Verdict.FAIL

    def test_incomparable_units_escalate_rather_than_fail_or_pass(self):
        finding = check_field(found("240", "cfu/g", field="lead"), LEAD)
        assert finding.verdict is Verdict.NEEDS_REVIEW
        assert "not compared" in finding.reason

    def test_an_unrecognised_unit_escalates(self):
        finding = check_field(found("3", "furlongs", field="lead"), LEAD)
        assert finding.verdict is Verdict.NEEDS_REVIEW


class TestEscalationNeverSilentPass:
    def test_a_missing_required_field_is_needs_review_never_pass(self):
        finding = check_field(None, MOISTURE)
        assert finding.verdict is Verdict.NEEDS_REVIEW
        assert finding.verdict is not Verdict.PASS
        assert "required" in finding.reason

    def test_a_missing_optional_field_is_skipped(self):
        optional = Limit(field="residual solvents", unit="ppm",
                         maximum=Decimal("50"), required=False)
        assert check_field(None, optional).verdict is Verdict.SKIPPED

    def test_low_confidence_escalates_even_when_the_value_would_pass(self):
        finding = check_field(found("0.21", "%", confidence="0.40"), MOISTURE)
        assert finding.verdict is Verdict.NEEDS_REVIEW
        assert "confidence" in finding.reason

    def test_a_missing_unit_escalates_rather_than_assuming_the_spec_unit(self):
        finding = check_field(found("0.21", None, confidence="0.90"), MOISTURE)
        assert finding.verdict is Verdict.NEEDS_REVIEW
        assert "no unit" in finding.reason

    def test_the_threshold_is_configurable(self):
        ex = found("0.21", "%", confidence="0.60")
        assert check_field(ex, MOISTURE).verdict is Verdict.NEEDS_REVIEW
        assert check_field(ex, MOISTURE, threshold=Decimal("0.5")).verdict is Verdict.PASS


class TestBelowDetectionResults:
    def test_a_bound_entirely_under_the_limit_passes(self):
        finding = check_field(found("0.05", "ppm", field="lead", qualifier="<"), LEAD)
        assert finding.verdict is Verdict.PASS

    def test_a_bound_that_does_not_settle_the_question_escalates(self):
        # "<1.0 ppm" against a 0.5 ppm limit: the real value could be anywhere
        # from zero to one. Reading that as a pass is the exact failure this
        # library exists to prevent.
        finding = check_field(found("1.0", "ppm", field="lead", qualifier="<"), LEAD)
        assert finding.verdict is Verdict.NEEDS_REVIEW
        assert "does not settle" in finding.reason

    def test_a_bound_entirely_below_a_minimum_fails(self):
        finding = check_field(found("50", "%", field="assay", qualifier="<"), ASSAY)
        assert finding.verdict is Verdict.FAIL

    def test_greater_than_a_minimum_passes(self):
        limit = Limit(field="assay", unit="percent", minimum=Decimal("98.0"))
        finding = check_field(found("99", "%", field="assay", qualifier=">"), limit)
        assert finding.verdict is Verdict.PASS

    def test_not_detected_satisfies_a_maximum(self):
        assert check_field(found(None, None, field="lead", not_detected=True),
                           LEAD).verdict is Verdict.PASS

    def test_not_detected_against_a_minimum_escalates(self):
        finding = check_field(found(None, None, field="assay", not_detected=True), ASSAY)
        assert finding.verdict is Verdict.NEEDS_REVIEW


class TestWholeDocuments:
    def test_a_clean_certificate_passes(self):
        result = check_document((EXAMPLES / "coa_clean.txt").read_text(), SPEC)
        assert result.verdict is Verdict.PASS, [str(f) for f in result.findings]
        assert result.passed

    def test_an_out_of_spec_certificate_fails_and_names_the_right_field(self):
        result = check_document((EXAMPLES / "coa_out_of_spec.txt").read_text(), SPEC)
        assert result.verdict is Verdict.FAIL
        failures = result.by_verdict(Verdict.FAIL)
        assert [f.field for f in failures] == ["moisture"]
        assert "0.62" in failures[0].reason

    def test_an_incomplete_certificate_escalates_and_does_not_fail(self):
        result = check_document((EXAMPLES / "coa_needs_review.txt").read_text(), SPEC)
        assert result.verdict is Verdict.NEEDS_REVIEW
        review = {f.field for f in result.by_verdict(Verdict.NEEDS_REVIEW)}
        assert "lead" in review      # required, absent from the document
        assert "arsenic" in review   # required, absent from the document
        assert "assay" in review     # present but with no unit

    def test_an_empty_document_never_passes(self):
        result = check_document("", SPEC)
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert not result.passed

    def test_junk_input_never_passes(self):
        result = check_document("\x00\x01 not a certificate at all", SPEC)
        assert result.verdict is not Verdict.PASS

    def test_one_needs_review_stops_the_whole_lot_passing(self):
        # An otherwise clean certificate with a single required test omitted.
        # Five passes do not add up to a pass when the sixth is unanswered.
        text = "\n".join(
            line for line in (EXAMPLES / "coa_clean.txt").read_text().splitlines()
            if not line.startswith("Lead")
        )
        result = check_document(text, SPEC)
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert [f.field for f in result.by_verdict(Verdict.NEEDS_REVIEW)] == ["lead"]

    @pytest.mark.parametrize("name", ["coa_clean.txt", "coa_out_of_spec.txt",
                                      "coa_needs_review.txt"])
    def test_every_finding_carries_a_reason_a_person_can_act_on(self, name):
        result = check_document((EXAMPLES / name).read_text(), SPEC)
        for finding in result.findings:
            assert finding.reason.strip()
            assert finding.field in finding.reason


class TestOptionalFieldsDoNotBlockAPass:
    def test_optional_absent_field_leaves_the_lot_passing(self):
        spec = load_spec_text(
            'material: X\nspecs:\n'
            '  - field: assay\n    unit: percent\n    min: "98"\n'
            '  - field: residual solvents\n    unit: ppm\n    max: "50"\n    required: false\n'
        )
        result = check_document("Assay   99.2 %", spec)
        assert result.verdict is Verdict.PASS
