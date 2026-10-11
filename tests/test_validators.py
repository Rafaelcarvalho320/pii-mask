"""Check digits, which are the difference between a detector and a regex."""

from __future__ import annotations

import pytest

from pii_mask import digits_of, is_cnpj, is_cpf, is_luhn, is_phone
from pii_mask.validators import VALID_DDD


class TestDigitsOf:
    def test_strips_formatting(self) -> None:
        assert digits_of("529.982.247-25") == "52998224725"

    def test_strips_letters_and_spaces(self) -> None:
        assert digits_of("CPF 529 982 247 25!") == "52998224725"

    def test_empty(self) -> None:
        assert digits_of("sem numero") == ""


class TestCPF:
    @pytest.mark.parametrize(
        "value",
        [
            "529.982.247-25",
            "52998224725",
            "529 982 247 25",
            "111.444.777-35",
        ],
    )
    def test_valid(self, value: str) -> None:
        assert is_cpf(value)

    @pytest.mark.parametrize(
        "value",
        [
            "529.982.247-26",  # last check digit wrong
            "529.982.247-15",  # first check digit wrong
            "52998224",  # too short
            "529982247250",  # too long
            "",
        ],
    )
    def test_invalid(self, value: str) -> None:
        assert not is_cpf(value)

    @pytest.mark.parametrize(
        "value",
        ["111.111.111-11", "000.000.000-00", "22222222222", "99999999999"],
    )
    def test_repeated_digits_are_rejected(self, value: str) -> None:
        # The arithmetic accepts them. They are the oldest placeholder in
        # Brazilian software, and treating a fixture as a finding is noise at
        # best and a masked test file at worst.
        assert not is_cpf(value)

    def test_a_mobile_number_is_not_a_cpf(self) -> None:
        # The reason this module exists: a Brazilian mobile with its area code
        # is exactly eleven digits, so \\d{11} reports every phone number in
        # the document as a CPF.
        assert not is_cpf("11987654321")

    def test_an_order_number_is_not_a_cpf(self) -> None:
        assert not is_cpf("52998224726")


class TestCNPJ:
    @pytest.mark.parametrize(
        "value",
        ["12.345.678/0001-95", "11.222.333/0001-81", "11222333000181"],
    )
    def test_valid(self, value: str) -> None:
        assert is_cnpj(value)

    @pytest.mark.parametrize(
        "value",
        ["12.345.678/0001-00", "12345678000100", "1234567800019", ""],
    )
    def test_invalid(self, value: str) -> None:
        assert not is_cnpj(value)

    def test_repeated_digits_are_rejected(self) -> None:
        assert not is_cnpj("11.111.111/1111-11")

    def test_a_cpf_is_not_a_cnpj(self) -> None:
        assert not is_cnpj("529.982.247-25")


class TestLuhn:
    @pytest.mark.parametrize(
        "value",
        [
            "4111 1111 1111 1111",
            "4111111111111111",
            "5500 0000 0000 0004",
            "3400 0000 0000 009",
        ],
    )
    def test_valid(self, value: str) -> None:
        assert is_luhn(value)

    @pytest.mark.parametrize("value", ["4111 1111 1111 1112", "1234567812345678"])
    def test_a_wrong_checksum_is_rejected(self, value: str) -> None:
        assert not is_luhn(value)

    def test_too_short_is_rejected_even_if_the_checksum_passes(self) -> None:
        # Luhn alone accepts four digits, and a detector that masks anything
        # passing a checksum eventually redacts an invoice total.
        assert is_luhn("79927398713") is False

    def test_too_long_is_rejected(self) -> None:
        assert not is_luhn("4" * 20)


class TestPhone:
    @pytest.mark.parametrize(
        "value",
        [
            "(11) 98765-4321",
            "11987654321",
            "+55 11 98765-4321",
            "5511987654321",
            "(11) 3456-7890",
            "1134567890",
        ],
    )
    def test_valid(self, value: str) -> None:
        assert is_phone(value)

    def test_an_invalid_area_code_is_rejected(self) -> None:
        # 20 is not a Brazilian area code. Accepting any two digits reads the
        # first half of an eleven-digit product code as a phone number.
        assert not is_phone("(20) 98765-4321")

    def test_eleven_digits_without_the_leading_nine_is_not_a_mobile(self) -> None:
        assert not is_phone("11887654321")

    def test_a_landline_cannot_start_with_a_service_digit(self) -> None:
        assert not is_phone("1104567890")

    def test_a_cpf_is_not_a_phone_number(self) -> None:
        assert not is_phone("52998224725")

    @pytest.mark.parametrize("value", ["123456789", "123456789012345", ""])
    def test_wrong_lengths(self, value: str) -> None:
        assert not is_phone(value)

    def test_the_area_code_table_is_not_a_range(self) -> None:
        # Documented as a table precisely because it has holes.
        assert 11 in VALID_DDD
        assert 20 not in VALID_DDD
        assert 23 not in VALID_DDD
        assert 99 in VALID_DDD
