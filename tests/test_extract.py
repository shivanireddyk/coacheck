from decimal import Decimal

import pytest

from coacheck.extract import (
    AMBIGUOUS_CONFIDENCE,
    HIGH_CONFIDENCE,
    NO_UNIT_CONFIDENCE,
    extract_all,
    extract_field,
)
from coacheck.spec import Limit, load_spec_text

MOISTURE = Limit(field="moisture", unit="percent", maximum=Decimal("0.5"),
                 aliases=("loss on drying", "water content"))
LEAD = Limit(field="lead", unit="ppm", maximum=Decimal("0.5"))
ARSENIC = Limit(field="arsenic", unit="ppm", maximum=Decimal("0.2"))


class TestFindingValues:
    def test_reads_a_plain_result(self):
        ex = extract_field("Moisture   0.21 %", MOISTURE)
        assert ex.value == Decimal("0.21")
        assert ex.unit == "%"
        assert ex.confidence == HIGH_CONFIDENCE

    def test_matching_by_alias_lowers_confidence_but_still_extracts(self):
        ex = extract_field("Loss on Drying   0.21 %", MOISTURE)
        assert ex.field == "moisture"
        assert ex.value == Decimal("0.21")
        assert ex.confidence < HIGH_CONFIDENCE

    def test_absent_field_returns_none_rather_than_a_default(self):
        assert extract_field("Assay 99.2 %", MOISTURE) is None

    def test_label_must_match_on_a_word_boundary(self):
        # "Leadership" is not a lead result.
        assert extract_field("Leadership review 3.2 ppm", LEAD) is None

    def test_thousands_separator(self):
        limit = Limit(field="total plate count", unit="cfu/g", maximum=Decimal("10000"))
        ex = extract_field("Total Plate Count   1,240 cfu/g", limit)
        assert ex.value == Decimal("1240")

    def test_records_the_source_line_so_a_person_can_check_it(self):
        ex = extract_field("Lead        0.08 ppm    NMT 0.5 ppm", LEAD)
        assert "0.08" in ex.source
        assert "0.08" in ex.cite()


class TestHonestyAboutUncertainty:
    def test_missing_unit_drops_confidence_instead_of_assuming_the_spec_unit(self):
        ex = extract_field("Assay: 99.1", Limit(field="assay", unit="percent",
                                                minimum=Decimal("98")))
        assert ex.unit is None
        assert ex.confidence == NO_UNIT_CONFIDENCE

    def test_a_second_unexplained_number_is_treated_as_ambiguous(self):
        # Two complete results on one line with nothing marking either as the
        # specification. Picking the leftmost and moving on would be a guess.
        ex = extract_field("Lead   0.08 ppm   0.11 ppm", LEAD)
        assert ex.confidence == AMBIGUOUS_CONFIDENCE

    def test_a_printed_specification_is_not_treated_as_ambiguous(self):
        # Real certificates print the result and the acceptance criterion on
        # the same line. Flagging that as ambiguous would flag every good doc.
        ex = extract_field("Lead        0.08 ppm    NMT 0.5 ppm", LEAD)
        assert ex.value == Decimal("0.08")
        assert ex.confidence == HIGH_CONFIDENCE

    def test_a_printed_range_is_not_treated_as_ambiguous(self):
        limit = Limit(field="assay", unit="percent", minimum=Decimal("98"),
                      maximum=Decimal("102"))
        ex = extract_field("Assay      99.2 %      98.0 - 102.0 %", limit)
        assert ex.value == Decimal("99.2")
        assert ex.confidence == HIGH_CONFIDENCE


class TestQualifiedAndNonNumericResults:
    @pytest.mark.parametrize("written", ["<0.05 ppm", "< 0.05 ppm", "≤0.05 ppm",
                                         "less than 0.05 ppm"])
    def test_below_detection_is_carried_as_a_bound_not_a_number(self, written):
        ex = extract_field(f"Lead   {written}", LEAD)
        assert ex.qualifier == "<"
        assert ex.value == Decimal("0.05")

    def test_greater_than(self):
        limit = Limit(field="assay", unit="percent", minimum=Decimal("98"))
        ex = extract_field("Assay   >99.5 %", limit)
        assert ex.qualifier == ">"

    @pytest.mark.parametrize("written", ["Not detected", "None detected", "ND"])
    def test_not_detected_is_recognised(self, written):
        ex = extract_field(f"Arsenic   {written}", ARSENIC)
        assert ex.not_detected is True
        assert ex.value is None

    def test_not_detected_beats_a_number_printed_after_it(self):
        # "Arsenic  Not detected  NMT 0.2 ppm" must not be read as 0.2 ppm.
        ex = extract_field("Arsenic     Not detected     NMT 0.2 ppm", ARSENIC)
        assert ex.not_detected is True
        assert ex.value is None


class TestExtractAll:
    def test_extracts_every_field_the_spec_asks_about(self):
        spec = load_spec_text(
            'material: X\nspecs:\n'
            '  - field: assay\n    unit: percent\n    min: "98"\n'
            '  - field: lead\n    unit: ppm\n    max: "0.5"\n'
            '  - field: cadmium\n    unit: ppm\n    max: "0.1"\n'
        )
        found = extract_all("Assay 99.2 %\nLead 0.08 ppm\n", spec)
        assert set(found) == {"assay", "lead"}
        assert "cadmium" not in found  # absent, not defaulted
