"""Deterministic verification (deterministic zone: no LLM client may be imported here)."""

from recount.verify.engine import Computed, VerifyError, execute, verify
from recount.verify.verdict import Verdict

__all__ = ["Computed", "Verdict", "VerifyError", "execute", "verify"]
