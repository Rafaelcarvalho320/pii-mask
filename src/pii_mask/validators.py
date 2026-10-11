"""Check digits, which are what turn a regex into a detector.

This module is the answer to the mistake the whole package exists to avoid.
``\\d{11}`` is not a CPF detector. It matches an order number, a timestamp, a
product code - and, worst of all, **a Brazilian mobile number with its area
code is exactly eleven digits**, so a naive detector reports every phone number
in the text as a CPF.

It also misses the way a CPF is actually written. ``529.982.247-25`` contains
no run of eleven digits at all.

So the shape is found loosely and then *verified*: the digits are pulled out
and the check digits recomputed. A number that fails is not personal data, and
a number that passes almost certainly is.
"""

from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D")


def digits_of(value: str) -> str:
    """Just the digits of ``value``, in order."""
    return _NON_DIGITS.sub("", value)


def _check_digit(digits: str, weights: range | list[int]) -> int:
    # strict=True on purpose: every caller passes exactly as many weights
    # as digits, and a mismatch is a bug in this file rather than bad input.
    total = sum(
        int(digit) * weight
        for digit, weight in zip(digits, weights, strict=True)
    )
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_cpf(value: str) -> bool:
    """Whether ``value`` is a CPF with valid check digits.

    All-identical digits are rejected even though they satisfy the arithmetic:
    ``111.111.111-11`` computes correctly and is not a real CPF. It is the
    oldest placeholder in Brazilian software, so accepting it means masking
    test data and, worse, treating a fixture as a finding.
    """
    digits = digits_of(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False

    first = _check_digit(digits[:9], range(10, 1, -1))
    if first != int(digits[9]):
        return False
    second = _check_digit(digits[:10], range(11, 1, -1))
    return second == int(digits[10])


#: The weights for a CNPJ, which are not a simple descending range: they run
#: down to 2 and then restart at 9. Writing them out is clearer than the
#: arithmetic that generates them, and harder to get subtly wrong.
_CNPJ_FIRST = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_SECOND = [6, *_CNPJ_FIRST]


def is_cnpj(value: str) -> bool:
    """Whether ``value`` is a CNPJ with valid check digits."""
    digits = digits_of(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False

    first = _check_digit(digits[:12], _CNPJ_FIRST)
    if first != int(digits[12]):
        return False
    second = _check_digit(digits[:13], _CNPJ_SECOND)
    return second == int(digits[13])


def is_luhn(value: str) -> bool:
    """Whether ``value`` passes the Luhn checksum, as a card number must.

    Length is checked too: Luhn alone accepts a four-digit number, and a
    detector that masks any eight digits passing a checksum will eventually
    redact an invoice total.
    """
    digits = digits_of(value)
    if not 13 <= len(digits) <= 19:
        return False

    total = 0
    for position, digit in enumerate(reversed(digits)):
        number = int(digit)
        if position % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


#: Valid Brazilian area codes. Not a range: 10 to 19 exist but 20, 23, 25,
#: 26, 29, 36, 39, 40, 50, 52, 56, 57, 58, 59, 60, 70, 72, 76, 78, 80 and 90
#: do not, and a detector that accepts any two digits will read the first half
#: of an eleven-digit product code as a phone number.
VALID_DDD = frozenset(
    {
        11, 12, 13, 14, 15, 16, 17, 18, 19,
        21, 22, 24, 27, 28,
        31, 32, 33, 34, 35, 37, 38,
        41, 42, 43, 44, 45, 46, 47, 48, 49,
        51, 53, 54, 55,
        61, 62, 63, 64, 65, 66, 67, 68, 69,
        71, 73, 74, 75, 77, 79,
        81, 82, 83, 84, 85, 86, 87, 88, 89,
        91, 92, 93, 94, 95, 96, 97, 98, 99,
    }
)


def is_phone(value: str) -> bool:
    """Whether ``value`` is a plausible Brazilian phone number.

    Ten or eleven digits after an optional ``55`` country code, a real area
    code, and - for the eleven-digit form - a leading ``9`` on the subscriber
    number, which is what distinguishes a mobile from eleven digits of
    something else.
    """
    digits = digits_of(value)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) not in (10, 11):
        return False
    if int(digits[:2]) not in VALID_DDD:
        return False
    if len(digits) == 11:
        return digits[2] == "9"
    # A landline's subscriber number starts at 2; 0 and 1 are service codes.
    return digits[2] in "2345"
