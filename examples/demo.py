"""The naive version, this version, and a full round trip. Nothing leaves the machine.

python examples/demo.py
"""

from __future__ import annotations

import re

from pii_mask import Style, is_cpf, mask, scan

DOCUMENT = (
    "Atendimento 48812: cliente Maria Silva, CPF 529.982.247-25, "
    "telefone (11) 98765-4321, e-mail maria.silva@empresa.com.br.\n"
    "A empresa dela e a 12.345.678/0001-95. O pedido 52998224726 "
    "no valor de R$ 1.234,56 foi pago no cartao 4111 1111 1111 1111.\n"
    "Confirmar tambem o fixo +55 11 3456-7890, o WhatsApp 11987654321 "
    "e o CPF 52998224725, que e o mesmo da Maria."
)

#: What almost every first attempt looks like.
NAIVE = re.compile(r"\d{11}")


def emit(line: str) -> None:
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "backslashreplace").decode("ascii"))


def section(title: str) -> None:
    emit("")
    emit(f"--- {title} " + "-" * max(0, 70 - len(title)))


def naive_demo() -> None:
    section("1. the regex everybody writes first")
    hits = NAIVE.findall(DOCUMENT)
    emit(f"  \\d{{11}} matched {len(hits)}: {hits}")
    for hit in hits:
        verdict = "a real CPF" if is_cpf(hit) else "NOT a CPF"
        emit(f"    {hit}  ->  {verdict}")
    emit("")
    emit("  Two of those three are not CPFs: one is an order number and one is")
    emit("  a mobile number, which with its area code is exactly eleven digits.")
    emit("  And the regex never sees 529.982.247-25 at all, because that string")
    emit("  contains no run of eleven digits.")


def scan_demo() -> None:
    section("2. the same document, with the check digits consulted")
    for found in scan(DOCUMENT):
        emit(f"  {found.kind:6} {found.value!r}")
    emit("")
    emit("  The order number, the amount and the CEP are left alone.")


def round_trip_demo() -> None:
    section("3. the round trip, including the part that goes wrong")
    masked, vault = mask(DOCUMENT)
    emit("  what would be sent to the provider:")
    for line in masked.splitlines():
        emit(f"    {line}")
    emit("")
    emit(f"  findings: {vault.kinds}")
    emit(f"  tokens:   {len(vault.tokens)} for {len(vault.findings)} findings")
    emit("  Maria's CPF appears twice, written two different ways, and both")
    emit("  share one token - so the model still sees one person rather than")
    emit("  two. That is why there are fewer tokens than findings.")
    emit(f"  leaked into the prompt: {vault.leaked(masked)}")

    cpf_token = vault.findings[0].replacement
    email_token = next(
        finding.replacement for finding in vault.findings if finding.kind == "email"
    )

    emit("")
    emit("  a reply that rewrote the sentence around the tokens:")
    good = (
        f"O cliente de CPF {cpf_token} esta com uma fatura em aberto. "
        f"Enviar a cobranca para {email_token}."
    )
    emit(f"    {good}")
    emit(f"    restored: {vault.unmask(good)}")

    emit("")
    emit("  a reply where the model paraphrased one token away:")
    bad = "O cliente esta com uma fatura em aberto. Enviar para o e-mail dele."
    emit(f"    {bad}")
    emit(f"    restored: {vault.unmask(bad)}")
    emit(f"    missing:  {len(vault.missing(bad))} of {len(vault.tokens)} tokens")
    emit("    Nothing about that reply looks wrong. It just says less than it")
    emit("    should, and missing() is what notices.")


def styles_demo() -> None:
    section("4. for a log line, where nothing has to come back")
    line = "cliente 529.982.247-25 / maria.silva@empresa.com.br / (11) 98765-4321"
    for style in (Style.LABEL, Style.PARTIAL):
        emit(f"  {style.value:8} {mask(line, style=style)[0]}")
    emit("")
    emit("  PARTIAL keeps enough for a person to recognise the record, and is")
    emit("  not anonymous: a partial value plus a name often identifies")
    emit("  somebody. LABEL is the one to use when in doubt.")


def main() -> None:
    naive_demo()
    scan_demo()
    round_trip_demo()
    styles_demo()


if __name__ == "__main__":
    main()
