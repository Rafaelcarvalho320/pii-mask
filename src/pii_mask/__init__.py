"""pii-mask: take Brazilian personal data out of a prompt, and put it back.

    >>> from pii_mask import mask
    >>> masked, vault = mask("Cliente Maria, CPF 529.982.247-25")
    >>> masked.startswith("Cliente Maria, CPF PII")
    True
    >>> vault.kinds
    {'cpf': 1}
    >>> vault.unmask(masked) == "Cliente Maria, CPF 529.982.247-25"
    True

CPF, CNPJ, card, phone and email, each confirmed by its check digits rather
than by a regex alone. That distinction is the whole package: ``\\d{11}``
matches an order number, a timestamp and - because a Brazilian mobile with its
area code is exactly eleven digits - every phone number in the text, while
missing ``529.982.247-25`` entirely, which contains no run of eleven digits.

Zero dependencies. Nothing is sent anywhere; this runs before the text leaves.
"""

from __future__ import annotations

from pii_mask.detectors import (
    ALL,
    BY_NAME,
    CARD,
    CEP,
    CNPJ,
    CPF,
    DEFAULT,
    EMAIL,
    PHONE,
    Candidate,
    Detector,
    scan,
)
from pii_mask.validators import (
    VALID_DDD,
    digits_of,
    is_cnpj,
    is_cpf,
    is_luhn,
    is_phone,
)
from pii_mask.vault import (
    PREFIX,
    Finding,
    Style,
    Vault,
    mask,
    partial,
)

__version__ = "0.1.0"

__all__ = [
    "ALL",
    "BY_NAME",
    "CARD",
    "CEP",
    "CNPJ",
    "CPF",
    "DEFAULT",
    "EMAIL",
    "PHONE",
    "PREFIX",
    "VALID_DDD",
    "Candidate",
    "Detector",
    "Finding",
    "Style",
    "Vault",
    "__version__",
    "digits_of",
    "is_cnpj",
    "is_cpf",
    "is_luhn",
    "is_phone",
    "mask",
    "partial",
    "scan",
]
