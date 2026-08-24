"""Audit writer for catalog state changes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from retrieval_hub.models.audit import AuditRecord

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from retrieval_hub.models.identity import Identity


def write_audit_record(
    session: Session,
    *,
    action: str,
    source_id: str | None = None,
    actor: str | Identity | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditRecord:
    """Append an audit record to the catalog audit log.

    Does NOT commit -- the caller's transaction handles that.
    """
    # Resolve actor to identity fields
    if actor is None:
        identity_sub = "unknown"
        identity_kind = "service"
    elif isinstance(actor, str):
        identity_sub = actor
        identity_kind = "service"
    else:
        # Identity dataclass
        identity_sub = actor.sub
        identity_kind = actor.kind
        if request_id is None:
            request_id = actor.request_id

    record = AuditRecord(
        identity_sub=identity_sub,
        identity_kind=identity_kind,
        action=action,
        source_id=source_id,
        details=details,
        request_id=request_id,
    )
    session.add(record)
    return record
