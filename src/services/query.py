"""Read-only raw-SQL escape hatch.

The repository runs on an engine-enforced read-only connection; this service adds
a fail-fast guard (must start SELECT/WITH; reject write keywords by whole word so
identifiers like `created_at` are not falsely rejected).
"""

import re

from src.domain.errors import ValidationError
from src.repositories.protocols import QueryRunner

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


class QueryService:
    def __init__(self, runner: QueryRunner):
        self._runner = runner

    async def run(self, sql: str) -> list[dict]:
        stripped = sql.strip()
        if not (stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH")):
            raise ValidationError("Only SELECT queries are allowed")
        forbidden = _FORBIDDEN_SQL.search(stripped)
        if forbidden:
            raise ValidationError(
                f"{forbidden.group(1).upper()} is not allowed — read-only queries only"
            )
        return await self._runner.select(sql)
