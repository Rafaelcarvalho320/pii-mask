"""Substitution, the round trip, and the ways a round trip fails."""

from __future__ import annotations

import re

import pytest

from pii_mask import PREFIX, Style, Vault, mask, partial
from pii_mask.vault import canonical

CPF_A = "529.982.247-25"
CPF_A_PLAIN = "52998224725"
CPF_B = "111.444.777-35"
EMAIL = "maria@empresa.com.br"
PHONE = "(11) 98765-4321"


class TestMasking:
    def test_the_value_is_gone(self) -> None:
        masked, _ = mask(f"CPF {CPF_A}")
        assert CPF_A not in masked

    def test_the_surrounding_text_is_untouched(self) -> None:
        masked, _ = mask(f"Cliente Maria, CPF {CPF_A}, ativo.")
        assert masked.startswith("Cliente Maria, CPF ")
        assert masked.endswith(", ativo.")

    def test_the_token_is_one_opaque_word(self) -> None:
        # No punctuation, no translatable word, no number to renumber. A
        # placeholder like [CPF_1] comes back as [CPF 1] or [cpf_1] and is
        # then unrestorable, silently.
        _, vault = mask(f"CPF {CPF_A}")
        [token] = vault.tokens
        assert re.fullmatch(rf"{PREFIX}[0-9A-F]{{8}}", token)

    def test_nothing_to_find_returns_the_text_unchanged(self) -> None:
        text = "o cliente ligou ontem"
        masked, vault = mask(text)
        assert masked is text
        assert vault.findings == []

    def test_findings_record_where_the_value_was(self) -> None:
        text = f"CPF {CPF_A} fim"
        _, vault = mask(text)
        [finding] = vault.findings
        assert text[finding.start : finding.end] == CPF_A
        assert finding.kind == "cpf"

    def test_several_kinds_at_once(self) -> None:
        masked, vault = mask(f"{CPF_A} / {EMAIL} / {PHONE}")
        assert vault.kinds == {"cpf": 1, "email": 1, "phone": 1}
        for value in (CPF_A, EMAIL, PHONE):
            assert value not in masked


class TestStability:
    def test_the_same_value_twice_gets_the_same_token(self) -> None:
        # So the model can still see the two mentions are one person. A fresh
        # token per occurrence makes it answer as though they were two.
        masked, vault = mask(f"{CPF_A} e novamente {CPF_A}")
        assert len(vault.tokens) == 1
        assert len(vault.findings) == 2
        assert masked.count(next(iter(vault.tokens))) == 2

    def test_two_spellings_of_one_value_share_a_token(self) -> None:
        _, vault = mask(f"{CPF_A} e {CPF_A_PLAIN}")
        assert len(vault.tokens) == 1

    def test_two_spellings_of_one_phone_share_a_token(self) -> None:
        _, vault = mask(f"{PHONE} e +55 11 98765-4321")
        assert len(vault.tokens) == 1

    def test_an_email_is_matched_case_insensitively(self) -> None:
        _, vault = mask(f"{EMAIL} e MARIA@Empresa.com.br")
        assert len(vault.tokens) == 1

    def test_different_values_get_different_tokens(self) -> None:
        _, vault = mask(f"{CPF_A} e {CPF_B}")
        assert len(vault.tokens) == 2

    def test_two_vaults_give_the_same_value_different_tokens(self) -> None:
        # Deliberate: a token stable across requests would let anyone
        # comparing two masked documents learn they concern the same person.
        _, first = mask(f"CPF {CPF_A}")
        _, second = mask(f"CPF {CPF_A}")
        assert set(first.tokens) != set(second.tokens)

    def test_within_one_vault_masking_twice_is_stable(self) -> None:
        vault = Vault()
        first = vault.mask(f"CPF {CPF_A}")
        second = vault.mask(f"outro doc, CPF {CPF_A}")
        token = next(iter(vault.tokens))
        assert token in first
        assert token in second


class TestRoundTrip:
    def test_the_text_comes_back(self) -> None:
        text = f"Cliente Maria, CPF {CPF_A}, tel {PHONE}."
        masked, vault = mask(text)
        assert vault.unmask(masked) == text

    def test_a_rewritten_reply_still_restores(self) -> None:
        # What actually happens: the model returns its own sentence with the
        # token in it, in a different place.
        _, vault = mask(f"CPF {CPF_A}")
        token = next(iter(vault.tokens))
        reply = f"O documento {token} esta regular."
        assert vault.unmask(reply) == f"O documento {CPF_A} esta regular."

    def test_a_second_spelling_comes_back_as_the_first(self) -> None:
        # The stated cost of sharing one token between spellings, asserted so
        # it cannot change without somebody noticing.
        masked, vault = mask(f"{CPF_A} e {CPF_A_PLAIN}")
        assert vault.unmask(masked) == f"{CPF_A} e {CPF_A}"

    def test_a_token_this_vault_never_issued_is_left_alone(self) -> None:
        _, vault = mask(f"CPF {CPF_A}")
        assert vault.unmask("PIIDEADBEEF") == "PIIDEADBEEF"

    def test_unmasking_text_with_no_tokens_changes_nothing(self) -> None:
        _, vault = mask(f"CPF {CPF_A}")
        assert vault.unmask("nada aqui") == "nada aqui"

    def test_one_pass_not_a_replace_loop(self) -> None:
        # A loop of str.replace re-scans text it has already restored. Here
        # the restored value itself contains something token-shaped, which a
        # loop would then try to restore again.
        vault = Vault()
        masked = vault.mask("contato PIIAAAAAAAA@empresa.com.br")
        [token] = vault.tokens
        assert vault.unmask(masked) == "contato PIIAAAAAAAA@empresa.com.br"
        assert token != "PIIAAAAAAAA"


class TestMissing:
    def test_a_token_the_model_dropped_is_reported(self) -> None:
        # The check worth running before sending a reply on: nothing about
        # the reply looks wrong, it just quietly says less than it should.
        _, vault = mask(f"{CPF_A} e {EMAIL}")
        token = vault.findings[0].replacement
        assert vault.missing(f"apenas {token}") == [vault.findings[1].replacement]

    def test_nothing_missing_when_every_token_came_back(self) -> None:
        masked, vault = mask(f"{CPF_A} e {EMAIL}")
        assert vault.missing(masked) == []

    def test_a_reformatted_token_counts_as_missing(self) -> None:
        masked, vault = mask(f"CPF {CPF_A}")
        [token] = vault.tokens
        mangled = masked.replace(token, token.lower())
        assert vault.missing(mangled) == [token]


class TestLeaked:
    def test_a_masked_document_leaks_nothing(self) -> None:
        masked, vault = mask(f"CPF {CPF_A}, tel {PHONE}, {EMAIL}")
        assert vault.leaked(masked) == []

    def test_a_value_left_in_the_text_is_reported(self) -> None:
        _, vault = mask(f"CPF {CPF_A}")
        [leak] = vault.leaked(f"ops, {CPF_A} escapou")
        assert leak.value == CPF_A


class TestStyles:
    def test_label(self) -> None:
        masked, _ = mask(f"CPF {CPF_A}", style=Style.LABEL)
        assert masked == "CPF [cpf]"

    def test_label_is_not_reversible(self) -> None:
        masked, vault = mask(f"CPF {CPF_A}", style=Style.LABEL)
        assert vault.unmask(masked) == masked

    def test_partial_keeps_the_tail(self) -> None:
        masked, _ = mask(f"CPF {CPF_A}", style=Style.PARTIAL)
        assert masked == "CPF ***.***.*47-25"

    def test_partial_keeps_the_separators(self) -> None:
        assert partial("529.982.247-25") == "***.***.*47-25"

    def test_partial_on_an_email_keeps_the_domain(self) -> None:
        # Keeping the last four characters of an email leaves
        # *****@*******.*om.br, which identifies nobody and helps nobody.
        assert partial(EMAIL, kind="email") == "m****@empresa.com.br"

    def test_partial_with_keep_zero_masks_everything(self) -> None:
        assert partial(CPF_A, keep=0) == "***.***.***-**"

    def test_partial_through_mask_is_email_aware(self) -> None:
        masked, _ = mask(EMAIL, style=Style.PARTIAL)
        assert masked == "m****@empresa.com.br"


class TestCanonical:
    def test_formatting_does_not_change_a_number(self) -> None:
        assert canonical("cpf", CPF_A) == canonical("cpf", CPF_A_PLAIN)

    def test_the_country_code_does_not_change_a_phone(self) -> None:
        assert canonical("phone", PHONE) == canonical("phone", "+55 11 98765-4321")

    def test_case_does_not_change_an_email(self) -> None:
        assert canonical("email", EMAIL) == canonical("email", EMAIL.upper())

    def test_the_kind_is_part_of_the_key(self) -> None:
        # So a CPF and a phone number that happen to share digits do not
        # share a token.
        assert canonical("cpf", "12345678901") != canonical("phone", "12345678901")


class TestVaultState:
    def test_the_key_is_not_in_the_repr(self) -> None:
        # It would otherwise end up in a log line through an f-string.
        assert "_key" not in repr(Vault())

    def test_kinds_counts_findings_not_tokens(self) -> None:
        _, vault = mask(f"{CPF_A} e {CPF_A}")
        assert vault.kinds == {"cpf": 2}
        assert len(vault.tokens) == 1

    def test_findings_accumulate_across_calls(self) -> None:
        vault = Vault()
        vault.mask(f"CPF {CPF_A}")
        vault.mask(f"CPF {CPF_B}")
        assert len(vault.findings) == 2

    def test_a_vault_can_be_given_detectors(self) -> None:
        from pii_mask import CPF as CPF_DETECTOR

        vault = Vault(detectors=[CPF_DETECTOR])
        masked = vault.mask(f"{CPF_A} e {EMAIL}")
        assert EMAIL in masked

    def test_findings_are_frozen(self) -> None:
        import dataclasses

        _, vault = mask(f"CPF {CPF_A}")
        with pytest.raises(dataclasses.FrozenInstanceError):
            vault.findings[0].value = "x"  # type: ignore[misc]
