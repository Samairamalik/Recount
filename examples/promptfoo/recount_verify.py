"""promptfoo `recount-verify` assertion shim: `type: python`, `value: file://recount_verify.py`.

The logic lives in the installed package; this file exists so promptfoo has a path to load.
"""

from recount.adapters.promptfoo import get_assert

__all__ = ["get_assert"]
