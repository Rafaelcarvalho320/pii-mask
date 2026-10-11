"""Finding the candidates, then deciding which ones survive.

Two problems that only show up on real text.

**Candidates overlap.** A CNPJ is fourteen digits; inside it there are runs of
eleven. A CPF pattern scanning the same text finds one of them, and now the
same characters are claimed by two detectors. Resolution is by length first
and detector order second, so ``12.345.678/0001-95`` is one CNPJ rather than a
CPF with litter around it.

**Loose patterns need tight validation.** Each pattern here deliberately
matches more than it should - that is what lets it find ``529.982.247-25``,
which contains no run of eleven digits - and then hands the candidate to a
check-digit function from :mod:`pii_mask.validators` that throws most of them
away.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from pii_mask.validators import is_cnpj, is_cpf, is_luhn, is_phone

#: A separator that may appear inside a formatted number.
_SEP = r"[.\-/\s]?"


def _grouped(*sizes: int) -> str:
    """A regex for digit groups joined by optional separators."""
    return _SEP.join(rf"\d{{{size}}}" for size in sizes)


@dataclass(frozen=True)
class Detector:
    """One kind of personal data: how to find it and how to confirm it."""

    #: Short, stable name. It goes into the token and into audit output, so it
    #: is part of the public surface.
    kind: str
    pattern: re.Pattern[str]
    #: Returns whether a candidate really is this kind of thing. The default
    #: accepts everything, for the kinds that have no check digit.
    validate: Callable[[str], bool] = lambda _: True

    def scan(self, text: str) -> Iterator[Candidate]:
        for match in self.pattern.finditer(text):
            value = match.group(0)
            if self.validate(value):
                yield Candidate(
                    kind=self.kind, value=value, start=match.start(), end=match.end()
                )


@dataclass(frozen=True)
class Candidate:
    kind: str
    value: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


CPF = Detector(
    kind="cpf",
    # Bounded by non-digits so a CPF is not read out of the middle of a
    # longer number, which is the same mistake as matching eleven digits
    # anywhere.
    pattern=re.compile(rf"(?<!\d){_grouped(3, 3, 3, 2)}(?!\d)"),
    validate=is_cpf,
)

CNPJ = Detector(
    kind="cnpj",
    pattern=re.compile(rf"(?<!\d){_grouped(2, 3, 3, 4, 2)}(?!\d)"),
    validate=is_cnpj,
)

PHONE = Detector(
    kind="phone",
    # The guards exclude a digit on either side and nothing else. An earlier
    # version also excluded a dot, to avoid matching inside a formatted
    # amount - and silently stopped recognising every phone number at the end
    # of a sentence, because the full stop was right there. Overlaps are
    # resolved by resolve(), which is the right place for it.
    pattern=re.compile(
        r"(?<!\d)(?:\+?55\s?)?(?:\(\d{2}\)|\d{2})\s?\d{4,5}[\-\s]?\d{4}(?!\d)"
    ),
    validate=is_phone,
)

CARD = Detector(
    kind="card",
    pattern=re.compile(r"(?<!\d)(?:\d{4}[\-\s]?){3}\d{1,7}(?!\d)"),
    validate=is_luhn,
)

EMAIL = Detector(
    kind="email",
    # Deliberately not RFC 5322. The full grammar accepts addresses nobody
    # sends and makes the pattern unreadable; this covers what appears in
    # text, and an address it misses is a miss, not a corruption.
    pattern=re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
)

CEP = Detector(
    kind="cep",
    pattern=re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)"),
)

#: Order matters: it breaks ties between candidates of the same length. The
#: longer, more structured kinds come first, so an eleven-digit run inside a
#: CNPJ loses to the CNPJ.
ALL: tuple[Detector, ...] = (CNPJ, CPF, CARD, PHONE, EMAIL, CEP)

#: What is masked when the caller does not say. CEP is left out on purpose: it
#: identifies a street, not a person, and masking it tends to destroy the very
#: address the model was asked to work with.
DEFAULT: tuple[Detector, ...] = (CNPJ, CPF, CARD, PHONE, EMAIL)

BY_NAME: dict[str, Detector] = {detector.kind: detector for detector in ALL}


def resolve(candidates: Sequence[Candidate], order: Sequence[str]) -> list[Candidate]:
    """Drop overlapping candidates, keeping the best one of each clash.

    Longest wins, and detector order breaks a tie. Without this, a document
    containing one CNPJ comes back with a CNPJ *and* a CPF overlapping it, and
    whichever is substituted second corrupts the text the first one produced.
    """
    rank = {kind: index for index, kind in enumerate(order)}
    ordered = sorted(
        candidates,
        key=lambda candidate: (-candidate.length, rank.get(candidate.kind, 99)),
    )

    kept: list[Candidate] = []
    for candidate in ordered:
        if any(
            candidate.start < other.end and other.start < candidate.end
            for other in kept
        ):
            continue
        kept.append(candidate)

    return sorted(kept, key=lambda candidate: candidate.start)


def scan(text: str, detectors: Sequence[Detector] = DEFAULT) -> list[Candidate]:
    """Every non-overlapping candidate in ``text``, in document order."""
    found = [candidate for detector in detectors for candidate in detector.scan(text)]
    return resolve(found, [detector.kind for detector in detectors])
