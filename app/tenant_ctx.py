"""Tenant execution context: carries the owning Discord user_id through
background task layers (scheduler -> worker -> gather engine) that cannot
take it as an explicit parameter, so per-tenant files (gather_status.json)
and broadcasts stay scoped to the right user."""
import contextvars

current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rok_tenant_user_id", default=""
)
