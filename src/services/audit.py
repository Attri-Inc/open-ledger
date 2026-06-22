"""Audit-log read use case."""

from src.repositories.protocols import AuditReader


class AuditService:
    def __init__(self, audit: AuditReader):
        self._audit = audit

    async def list(
        self, action: str | None = None, actor: str | None = None, limit: int = 25, offset: int = 0
    ) -> dict:
        items, total = await self._audit.list(action, actor, limit, offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}
