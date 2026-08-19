from decimal import Decimal
from pathlib import Path

import pytest

from coacheck.spec import SpecError, load_spec, load_spec_text

GOOD = """
material: Ascorbic Acid USP
supplier: Any
specs:
  - field: assay
    unit: percent
    min: "98.0"
    max: "102.0"
  - field: moisture
    unit: percent
    max: "0.5"
    aliases: ["loss on drying"]
"""


class TestLoading:
    def test_loads_a_valid_spec(self):
        spec = load_spec_text(GOOD)
        assert spec.material == "Ascorbic Acid USP"
        assert len(spec.limits) == 2
        assert spec.limits[0].minimum == Decimal("98.0")

    def test_limits_are_decimals_not_floats(self):
        spec = load_spec_text(GOOD)
        assert isinstance(spec.limits[1].maximum, Decimal)

    def test_alias_lookup_is_case_insensitive(self):
        spec = load_spec_text(GOOD)
        assert spec.limit_for("LOSS ON DRYING").field == "moisture"
        assert spec.limit_for("Assay").field == "assay"
        assert spec.limit_for("nothing at all") is None

    def test_required_fields_defaults_to_all(self):
        assert set(load_spec_text(GOOD).required_fields()) == {"assay", "moisture"}

    def test_the_shipped_spec_file_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "specs" / "ascorbic_acid.yaml"
        spec = load_spec(path)
        assert spec.limit_for("total plate count") is not None

    def test_missing_file_raises_spec_error_not_oserror(self):
        with pytest.raises(SpecError, match="cannot read"):
            load_spec("/nonexistent/path/to/spec.yaml")


class TestValidationRejectsBadSpecs:
    """A spec that does not mean what its author thought is worse than none."""

    def test_float_limit_is_rejected(self):
        with pytest.raises(SpecError, match="not floats"):
            load_spec_text("material: X\nspecs:\n  - field: a\n    unit: ppm\n    max: 0.5\n")

    def test_missing_unit_is_rejected(self):
        with pytest.raises(SpecError, match="'unit' is required"):
            load_spec_text('material: X\nspecs:\n  - field: a\n    max: "1"\n')

    def test_unknown_unit_is_rejected(self):
        with pytest.raises(SpecError, match="unrecognised unit"):
            load_spec_text('material: X\nspecs:\n  - field: a\n    unit: furlongs\n    max: "1"\n')

    def test_min_above_max_is_rejected(self):
        with pytest.raises(SpecError, match="above max"):
            load_spec_text(
                'material: X\nspecs:\n  - field: a\n    unit: ppm\n    min: "9"\n    max: "1"\n'
            )

    def test_limit_with_neither_min_nor_max_is_rejected(self):
        with pytest.raises(SpecError, match="at least one"):
            load_spec_text("material: X\nspecs:\n  - field: a\n    unit: ppm\n")

    def test_misspelled_key_is_rejected_rather_than_ignored(self):
        with pytest.raises(SpecError, match="unknown key"):
            load_spec_text(
                'material: X\nspecs:\n  - field: a\n    unit: ppm\n    maximum: "1"\n'
            )

    def test_duplicate_field_is_rejected(self):
        with pytest.raises(SpecError, match="duplicate"):
            load_spec_text(
                'material: X\nspecs:\n'
                '  - field: lead\n    unit: ppm\n    max: "1"\n'
                '  - field: lead\n    unit: ppm\n    max: "2"\n'
            )

    def test_alias_colliding_with_another_field_is_rejected(self):
        with pytest.raises(SpecError, match="duplicate"):
            load_spec_text(
                'material: X\nspecs:\n'
                '  - field: moisture\n    unit: percent\n    max: "1"\n'
                '  - field: water\n    unit: percent\n    max: "2"\n    aliases: ["Moisture"]\n'
            )

    def test_missing_material_is_rejected(self):
        with pytest.raises(SpecError, match="'material' is required"):
            load_spec_text('specs:\n  - field: a\n    unit: ppm\n    max: "1"\n')

    def test_empty_specs_list_is_rejected(self):
        with pytest.raises(SpecError, match="'specs' is required"):
            load_spec_text("material: X\nspecs: []\n")

    def test_malformed_yaml_is_rejected(self):
        with pytest.raises(SpecError, match="not valid YAML"):
            load_spec_text("material: [unclosed\n")

    def test_non_mapping_top_level_is_rejected(self):
        with pytest.raises(SpecError, match="mapping at the top level"):
            load_spec_text("- just\n- a\n- list\n")


class TestDescribe:
    def test_range(self):
        assert load_spec_text(GOOD).limits[0].describe() == "98.0 to 102.0 percent"

    def test_maximum_only(self):
        assert load_spec_text(GOOD).limits[1].describe() == "<= 0.5 percent"

    def test_exclusive_maximum_reads_differently(self):
        spec = load_spec_text(
            'material: X\nspecs:\n  - field: a\n    unit: ppm\n    max: "1"\n    inclusive: false\n'
        )
        assert spec.limits[0].describe() == "< 1 ppm"
