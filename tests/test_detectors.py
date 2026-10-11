"""Finding candidates in prose, and resolving the ones that overlap."""

from __future__ import annotations

import pytest

from pii_mask import ALL, CEP, DEFAULT, scan
from pii_mask.detectors import Candidate, resolve


def kinds(text: str, detectors: object = DEFAULT) -> list[str]:
    return [found.kind for found in scan(text, detectors)]  # type: ignore[arg-type]


def values(text: str, detectors: object = DEFAULT) -> list[str]:
    return [found.value for found in scan(text, detectors)]  # type: ignore[arg-type]


class TestFormattedNumbers:
    def test_a_formatted_cpf_is_found(self) -> None:
        # The case a \\d{11} regex misses entirely: there is no run of eleven
        # digits in this string.
        assert values("CPF 529.982.247-25 ok") == ["529.982.247-25"]

    def test_an_unformatted_cpf_is_found(self) -> None:
        assert values("CPF 52998224725 ok") == ["52998224725"]

    def test_a_space_separated_cpf_is_found(self) -> None:
        assert values("CPF 529 982 247 25 ok") == ["529 982 247 25"]

    def test_a_formatted_cnpj_is_found(self) -> None:
        assert values("CNPJ 12.345.678/0001-95.") == ["12.345.678/0001-95"]

    def test_an_email_is_found(self) -> None:
        assert values("escreva para maria.silva+nf@empresa.com.br hoje") == [
            "maria.silva+nf@empresa.com.br"
        ]

    def test_a_card_is_found(self) -> None:
        assert values("cartao 4111 1111 1111 1111 ok") == ["4111 1111 1111 1111"]


class TestPhones:
    @pytest.mark.parametrize(
        "text",
        [
            "ligue (11) 98765-4321",
            "ligue 11987654321",
            "ligue +55 11 98765-4321",
            "ligue (11) 3456-7890",
        ],
    )
    def test_found(self, text: str) -> None:
        assert kinds(text) == ["phone"]

    def test_at_the_end_of_a_sentence(self) -> None:
        # The regression that matters: an earlier version excluded a dot on
        # either side, to avoid matching inside a formatted amount, and
        # silently stopped recognising every phone number followed by a full
        # stop - which is most of them.
        assert kinds("ligue (11) 98765-4321.") == ["phone"]

    def test_inside_parentheses_at_the_end(self) -> None:
        assert kinds("contato (ligue (11) 98765-4321).") == ["phone"]

    def test_an_invalid_area_code_is_not_found(self) -> None:
        assert kinds("codigo (20) 98765-4321") == []


class TestFalsePositives:
    def test_an_order_number_of_eleven_digits_is_not_a_cpf(self) -> None:
        assert kinds("pedido 52998224726") == []

    def test_a_formatted_amount_is_not_anything(self) -> None:
        assert kinds("valor R$ 1.234.567,89") == []

    def test_a_timestamp_is_not_a_cpf(self) -> None:
        assert kinds("ts 1700000000000") == []

    def test_a_placeholder_cpf_is_not_a_finding(self) -> None:
        assert kinds("CPF 111.111.111-11") == []

    def test_a_product_code_is_not_a_card(self) -> None:
        assert kinds("sku 1234 5678 9012 3456") == []

    def test_prose_with_no_data(self) -> None:
        assert kinds("o cliente ligou ontem para reclamar do prazo") == []

    def test_an_empty_string(self) -> None:
        assert kinds("") == []


class TestOverlaps:
    def test_a_cnpj_is_not_also_read_as_a_cpf(self) -> None:
        # A CNPJ is fourteen digits and contains runs of eleven. Without
        # resolution the same characters are claimed twice, and whichever
        # substitution happens second corrupts the first one's output.
        assert kinds("CNPJ 12.345.678/0001-95") == ["cnpj"]

    def test_a_card_is_not_read_as_a_phone(self) -> None:
        assert kinds("cartao 4111 1111 1111 1111") == ["card"]

    def test_longest_wins(self) -> None:
        first = Candidate(kind="cpf", value="x" * 11, start=0, end=11)
        second = Candidate(kind="cnpj", value="x" * 18, start=0, end=18)
        assert resolve([first, second], ["cnpj", "cpf"]) == [second]

    def test_detector_order_breaks_a_tie(self) -> None:
        first = Candidate(kind="cpf", value="x" * 11, start=0, end=11)
        second = Candidate(kind="phone", value="y" * 11, start=0, end=11)
        assert resolve([first, second], ["cpf", "phone"]) == [first]
        assert resolve([first, second], ["phone", "cpf"]) == [second]

    def test_candidates_that_do_not_overlap_are_both_kept(self) -> None:
        first = Candidate(kind="cpf", value="a", start=0, end=5)
        second = Candidate(kind="cpf", value="b", start=5, end=10)
        assert len(resolve([first, second], ["cpf"])) == 2

    def test_results_come_back_in_document_order(self) -> None:
        text = "email a@b.com, CPF 529.982.247-25, tel (11) 98765-4321"
        assert kinds(text) == ["email", "cpf", "phone"]


class TestDetectorSelection:
    def test_cep_is_not_in_the_default_set(self) -> None:
        # It identifies a street, not a person, and masking it tends to
        # destroy the address the model was asked to work with.
        assert kinds("CEP 01001-000") == []

    def test_but_it_can_be_asked_for(self) -> None:
        assert kinds("CEP 01001-000", [CEP]) == ["cep"]

    def test_a_single_detector_can_be_used_alone(self) -> None:
        from pii_mask import CPF

        text = "CPF 529.982.247-25, tel (11) 98765-4321"
        assert kinds(text, [CPF]) == ["cpf"]

    def test_all_includes_cep(self) -> None:
        assert "cep" in {detector.kind for detector in ALL}

    def test_every_detector_has_a_distinct_kind(self) -> None:
        names = [detector.kind for detector in ALL]
        assert len(names) == len(set(names))


class TestRealDocument:
    TEXT = (
        "Cliente Maria Silva, CPF 529.982.247-25, telefone (11) 98765-4321.\n"
        "Empresa 12.345.678/0001-95, contato maria.silva+nf@empresa.com.br.\n"
        "Pedido 52998224726 no valor de R$ 1.234,56, cartao 4111 1111 1111 1111.\n"
        "CEP 01001-000, fixo +55 11 3456-7890."
    )

    def test_everything_is_found_once(self) -> None:
        assert kinds(self.TEXT) == [
            "cpf",
            "phone",
            "cnpj",
            "email",
            "card",
            "phone",
        ]

    def test_the_order_number_and_the_amount_are_left_alone(self) -> None:
        found = " ".join(values(self.TEXT))
        assert "52998224726" not in found
        assert "1.234,56" not in found
