"""Substituting the findings, and putting them back.

The hard part is not the masking. It is that the text comes back **rewritten**:
a model reorders it, quotes part of it, translates the labels around it. A
placeholder has to survive that round trip, and the ones people reach for do
not.

``[CPF_1]`` does not survive. It is prose: it contains punctuation a model will
reformat, a word it may translate, and a number it may renumber. ``[CPF 1]``,
``[cpf_1]`` and ``(CPF_1)`` all come back unrestorable, and a failed
restoration is silent - the reply simply still contains a placeholder, which
reads as a formatting glitch rather than as lost data.

So a token here is one opaque alphanumeric word with no punctuation and no
meaning to translate: ``PIIC4A7F21B``. It is **stable within a vault**, so the
same CPF appearing twice gets the same token and the model can still see the
two mentions are the same person - a fresh token per occurrence quietly
destroys that, and the model starts answering as though they were two people.

And :meth:`Vault.unmask` reports what did not come back, because the
alternative is finding out in a customer's inbox.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from pii_mask.detectors import DEFAULT, Candidate, Detector, scan
from pii_mask.validators import digits_of

#: Prefix every token shares. Letters only, so the token is one word to a
#: tokeniser and to a model.
PREFIX = "PII"

#: Hex characters of the digest in a token. Eight is 4 billion values, which
#: makes a collision inside one document a non-event; collisions are detected
#: anyway rather than assumed away.
DIGEST_LENGTH = 8

_TOKEN = re.compile(rf"{PREFIX}[0-9A-F]{{{DIGEST_LENGTH}}}")

#: Kinds whose identity is their digits, not their punctuation.
NUMERIC_KINDS = frozenset({"cpf", "cnpj", "card", "phone", "cep"})


def canonical(kind: str, value: str) -> str:
    """The form two spellings of the same value share.

    ``529.982.247-25`` and ``52998224725`` are one person, and tokenising the
    literal text gives them two different tokens - at which point the model is
    looking at what it reasonably reads as two different people, and will
    answer accordingly. So the token is derived from this, not from the text.

    The cost is stated plainly in :meth:`Vault.unmask`: a value written two
    ways comes back written the way it was written first.
    """
    if kind in NUMERIC_KINDS:
        digits = digits_of(value)
        if kind == "phone" and digits.startswith("55") and len(digits) in (12, 13):
            # +55 11 98765-4321 and (11) 98765-4321 are the same line.
            digits = digits[2:]
        return f"{kind}:{digits}"
    if kind == "email":
        # The local part is case-sensitive in the standard and
        # case-insensitive at every provider anybody uses.
        return f"email:{value.casefold()}"
    return f"{kind}:{value}"


class Style(Enum):
    """How a finding is replaced."""

    #: ``PIIC4A7F21B`` - reversible, and the only style :meth:`Vault.unmask`
    #: can undo.
    TOKEN = "token"
    #: ``[cpf]`` - not reversible. For a log line, where the goal is that the
    #: value never existed rather than that it comes back.
    LABEL = "label"
    #: ``***.***.247-25`` - keeps the last four characters, so a human can
    #: still recognise which record is being discussed. Not reversible, and
    #: not safe to treat as anonymous: a partial value plus a name is often
    #: enough to identify somebody.
    PARTIAL = "partial"


@dataclass(frozen=True)
class Finding:
    """One piece of personal data that was found, and what replaced it."""

    kind: str
    value: str
    start: int
    end: int
    replacement: str


@dataclass
class Vault:
    """Holds the mapping for one round trip. Not for reuse across requests.

    The key is random per vault, so two vaults give the same value different
    tokens. That is deliberate: a token stable across requests would let
    anyone comparing two masked documents learn that they concern the same
    person, which is the exact inference masking is supposed to prevent.
    """

    detectors: Sequence[Detector] = DEFAULT
    style: Style = Style.TOKEN
    #: token -> the value it restores to, which is the first spelling of it
    #: that this vault saw.
    tokens: dict[str, str] = field(default_factory=dict)
    #: Everything found, in document order, across every call to
    #: :meth:`mask` this vault has served.
    findings: list[Finding] = field(default_factory=list)
    _key: bytes = field(default_factory=lambda: secrets.token_bytes(16), repr=False)
    #: token -> the canonical key it was derived from, so a real collision can
    #: be told apart from the same value written differently.
    _keys: dict[str, str] = field(default_factory=dict, repr=False)

    # -- masking ----------------------------------------------------------

    def mask(self, text: str) -> str:
        """Replace every finding in ``text`` and remember how to undo it."""
        found = scan(text, self.detectors)
        if not found:
            return text

        pieces: list[str] = []
        cursor = 0
        for candidate in found:
            replacement = self._replacement(candidate)
            pieces.append(text[cursor : candidate.start])
            pieces.append(replacement)
            cursor = candidate.end
            self.findings.append(
                Finding(
                    kind=candidate.kind,
                    value=candidate.value,
                    start=candidate.start,
                    end=candidate.end,
                    replacement=replacement,
                )
            )
        pieces.append(text[cursor:])
        return "".join(pieces)

    def _replacement(self, candidate: Candidate) -> str:
        if self.style is Style.LABEL:
            return f"[{candidate.kind}]"
        if self.style is Style.PARTIAL:
            return partial(candidate.value, kind=candidate.kind)
        return self._token_for(candidate.kind, candidate.value)

    def _token_for(self, kind: str, value: str) -> str:
        key = canonical(kind, value)
        digest = hashlib.sha256(self._key + key.encode("utf-8")).hexdigest()
        token = f"{PREFIX}{digest[:DIGEST_LENGTH].upper()}"

        existing = self._keys.get(token)
        if existing is not None and existing != key:
            # Vanishingly unlikely, and handled rather than asserted away:
            # two values sharing a token would restore to each other, which is
            # a data leak dressed up as a coincidence.
            for salt in range(1, 1000):
                extra = hashlib.sha256(
                    self._key + key.encode("utf-8") + str(salt).encode()
                ).hexdigest()
                token = f"{PREFIX}{extra[:DIGEST_LENGTH].upper()}"
                if self._keys.get(token) in (None, key):
                    break
            else:  # pragma: no cover - needs 1000 collisions on one key
                raise RuntimeError("could not find a free token")

        self._keys[token] = key
        # setdefault, not assignment: the first spelling wins, so restoring is
        # stable no matter which occurrence is being replaced.
        self.tokens.setdefault(token, value)
        return token

    # -- unmasking --------------------------------------------------------

    def unmask(self, text: str) -> str:
        """Put the original values back wherever a token survived.

        One pass with a single regex, not a loop of ``str.replace``. A loop
        re-scans text it has already restored, so a value that happens to
        contain a token - or two tokens where one is a prefix of the other -
        produces a result that depends on dictionary order.

        A value the document wrote two ways comes back written the way it was
        written first, because both spellings share one token. See
        :func:`canonical` for why that trade is worth making.
        """

        def restore(match: re.Match[str]) -> str:
            return self.tokens.get(match.group(0), match.group(0))

        return _TOKEN.sub(restore, text)

    def missing(self, text: str) -> list[str]:
        """Tokens this vault issued that are **not** in ``text``.

        The check worth running on a model's reply before sending it on. A
        token the model dropped or rewrote means a value did not come back,
        and nothing about the reply looks wrong - it just quietly says less
        than it should, or still has a placeholder in it.
        """
        return [token for token in self.tokens if token not in text]

    def leaked(self, text: str) -> list[Finding]:
        """Original values from this vault that appear verbatim in ``text``.

        For asserting the obvious thing in a test: that what was sent to the
        provider does not contain what was masked.
        """
        return [
            finding
            for finding in self.findings
            if finding.value and finding.value in text
        ]

    # -- inspection -------------------------------------------------------

    @property
    def kinds(self) -> dict[str, int]:
        """How many of each kind were found, for a log line or an audit."""
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
        return counts


#: How many trailing characters :class:`Style.PARTIAL` keeps.
PARTIAL_KEEP = 4


def partial(value: str, keep: int = PARTIAL_KEEP, *, kind: str | None = None) -> str:
    """Mask everything but the last ``keep`` characters, preserving separators.

    Separators are kept because the shape is what makes the remainder
    recognisable to a person reading a support ticket, and because turning
    ``529.982.247-25`` into fourteen asterisks loses the fact that it was a
    CPF at all.

    An email is masked differently, and has to be: keeping its last four
    characters leaves ``*****@*******.*om.br``, which identifies nobody and
    helps nobody either. The local part is masked and the domain kept, which
    is the form every bank and airline uses because it is the one a person can
    actually recognise.
    """
    if kind == "email" and "@" in value:
        local, _, domain = value.partition("@")
        head = local[0] if local else ""
        return f"{head}{'*' * max(len(local) - 1, 1)}@{domain}"

    if keep <= 0:
        return re.sub(r"\w", "*", value)

    kept = 0
    out: list[str] = []
    for char in reversed(value):
        if not char.isalnum():
            out.append(char)
            continue
        if kept < keep:
            out.append(char)
            kept += 1
        else:
            out.append("*")
    return "".join(reversed(out))


def mask(
    text: str,
    *,
    detectors: Sequence[Detector] = DEFAULT,
    style: Style = Style.TOKEN,
) -> tuple[str, Vault]:
    """Mask ``text`` and return it with the vault that can undo it.

    masked, vault = mask(prompt)
    reply = call_the_model(masked)
    answer = vault.unmask(reply)
    """
    vault = Vault(detectors=detectors, style=style)
    return vault.mask(text), vault
