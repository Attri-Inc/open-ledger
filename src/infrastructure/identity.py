"""ID generation and the system clock — infrastructure concerns kept out of the
pure domain so services can stay deterministic-friendly."""

import uuid
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
