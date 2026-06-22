"""Money formatting — the single source of truth for rendering amounts.

Amounts are stored and computed as integer minor units (cents). This module
formats them for display using integer arithmetic only (divmod), so there is
no float rounding anywhere in the project. Every layer (db, seed, reports)
must format through `format_minor` so rounding is identical everywhere.
"""


def format_minor(amount_minor: int) -> str:
    """Render integer minor units (cents) as a currency string, e.g. -12345 -> "-$123.45".

    Uses divmod on integers — never float division — so the result is exact
    and consistent regardless of magnitude.
    """
    sign = "-" if amount_minor < 0 else ""
    dollars, cents = divmod(abs(int(amount_minor)), 100)
    return f"{sign}${dollars:,}.{cents:02d}"
