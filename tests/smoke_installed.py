"""Check the installed package, not the working copy.

Run as a script rather than collected by pytest::

    python tests/smoke_installed.py

Two claims the ordinary suite cannot make, because it imports from ``src``
with the dev extras present:

* **Zero dependencies.** The package says so in its metadata, and a stray
  import is the easiest way for that to quietly stop being true. It matters
  more here than elsewhere: this is the code that runs on personal data
  before it leaves the network, so what it loads is a security question and
  not only a packaging one.
* **It works as installed.** A missing entry in ``packages`` publishes a wheel
  that imports and then raises ``ModuleNotFoundError`` on first real use.

The exit code is what CI reads, so every check is an assertion.
"""

from __future__ import annotations

import sys


def main() -> int:
    import pii_mask

    allowed = {"pii_mask"}
    third_party = {
        name.split(".")[0]
        for name, module in sys.modules.items()
        if not name.startswith("_")
        and getattr(module, "__file__", None)
        and "site-packages" in str(module.__file__)
    }
    unexpected = third_party - allowed
    assert not unexpected, f"pii_mask pulled in {sorted(unexpected)}"

    cpf = "529.982.247-25"
    text = f"Cliente Maria, CPF {cpf}, pedido 52998224726, tel 11987654321"

    masked, vault = pii_mask.mask(text)
    assert cpf not in masked, masked
    # The order number is not personal data and must survive untouched.
    assert "52998224726" in masked, masked
    # The mobile is eleven digits and must be found as a phone, not a CPF.
    assert vault.kinds == {"cpf": 1, "phone": 1}, vault.kinds
    assert vault.leaked(masked) == [], vault.leaked(masked)
    assert vault.unmask(masked) == text

    # A reply that kept only one token reports the rest as missing.
    first = vault.findings[0].replacement
    assert len(vault.missing(f"apenas {first}")) == 1

    print(f"ok: pii-mask {pii_mask.__version__} installed, no third-party imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
