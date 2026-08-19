from decimal import Decimal

import pytest

from coacheck.units import (
    IncompatibleUnitsError,
    UnknownUnitError,
    canonicalise_unit,
    compatible,
    convert,
    family_of,
    known_units,
    to_canonical,
)


class TestSpelling:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("PPM", "ppm"), ("  ppm ", "ppm"), ("mg/kg", "mg/kg"),
            ("CFU/g", "cfu/g"), ("cfu / g", "cfu/g"),
            ("µg/g", "ug/g"), ("μg/g", "ug/g"), ("%", "%"),
        ],
    )
    def test_folds_the_spellings_certificates_actually_use(self, written, expected):
        assert canonicalise_unit(written) == expected

    def test_unknown_unit_raises_rather_than_defaulting(self):
        with pytest.raises(UnknownUnitError):
            family_of("grains per bushel")

    def test_non_string_unit_raises(self):
        with pytest.raises(UnknownUnitError):
            canonicalise_unit(5)


class TestConversion:
    def test_ppb_to_ppm(self):
        assert convert(Decimal("500"), "ppb", "ppm") == Decimal("0.5")

    def test_percent_to_ppm(self):
        assert convert(Decimal("0.05"), "percent", "ppm") == Decimal("500")

    def test_mg_per_kg_is_ppm(self):
        assert convert(Decimal("1"), "mg/kg", "ppm") == Decimal("1")

    def test_round_trip_is_exact(self):
        original = Decimal("0.437")
        there = convert(original, "percent", "ppb")
        back = convert(there, "ppb", "percent")
        assert back == original

    def test_cross_family_raises_instead_of_returning_a_plausible_number(self):
        with pytest.raises(IncompatibleUnitsError):
            convert(Decimal("240"), "cfu/g", "ppm")

    def test_cfu_per_gram_and_per_millilitre_are_different_families(self):
        assert not compatible("cfu/g", "cfu/ml")
        with pytest.raises(IncompatibleUnitsError):
            convert(Decimal("100"), "cfu/g", "cfu/ml")

    def test_same_family_is_compatible(self):
        assert compatible("ppm", "%")
        assert compatible("ug/kg", "ppb")


class TestDecimalDiscipline:
    def test_float_is_rejected_at_the_boundary(self):
        with pytest.raises(TypeError, match="not float"):
            to_canonical(0.5, "ppm")

    def test_string_and_int_are_accepted(self):
        assert to_canonical("0.5", "ppm") == Decimal("0.5")
        assert to_canonical(3, "ppm") == Decimal("3")

    def test_a_value_that_float_would_get_wrong(self):
        # 0.1 + 0.2 != 0.3 in binary floating point. A spec comparison that
        # goes through float can therefore fail a lot that is exactly on the
        # limit. Decimal makes this exact.
        total = to_canonical("0.1", "ppm") + to_canonical("0.2", "ppm")
        assert total == to_canonical("0.3", "ppm")


def test_known_units_is_non_empty_and_sorted():
    units = known_units()
    assert units
    assert list(units) == sorted(units)
    assert "ppm" in units
