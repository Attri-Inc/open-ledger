"""Pure domain constants — no I/O, no dependencies."""

# Each account type's normal (positive) side. Adding a type is data, not a branch.
NORMAL_SIDE: dict[str, str] = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "income": "credit",
}

ACCOUNT_TYPES: frozenset[str] = frozenset(NORMAL_SIDE)
DIRECTIONS: frozenset[str] = frozenset({"debit", "credit"})
