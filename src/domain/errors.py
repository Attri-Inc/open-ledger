"""Typed domain errors.

Services raise these; the transport boundary (MCP tools) maps them to a stable
error envelope. A single hierarchy means every layer speaks the same language.
"""


class DomainError(Exception):
    """Base class for all expected, client-facing domain failures."""


class NotFoundError(DomainError):
    """A referenced entity does not exist (account, transaction, ...)."""


class ValidationError(DomainError):
    """Input violates a domain rule (unbalanced, non-positive amount, bad date)."""


class ConflictError(DomainError):
    """The operation conflicts with current state (duplicate code, already reversed)."""
