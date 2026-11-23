"""Who may act on an invoice.

Row-level ownership rather than a role check alone, per CLAUDE.md §4's
recommendation for the four-principal tenancy question while volumes are small:
an admin sees everything, a creator sees only invoices on projects assigned to
them, a customer only their own.
"""

from uuid import UUID

from app.core.exceptions import PermissionDeniedError
from app.domain.entities.invoice import Invoice
from app.domain.entities.project import Project
from app.domain.entities.user import Permission, User, UserRole


def assert_may_bill_project(actor: User, project: Project) -> None:
    if actor.role is UserRole.ADMIN:
        return
    if actor.role is UserRole.CREATOR and project.creator_id == actor.id:
        return
    # A coordinator who has been let into Payments. Checked here as well as at
    # the door, because a guard that admits somebody to an endpoint has said
    # nothing about which rows they may touch — and a grant that opened the
    # screen but refused every action on it would be a worse lie than no
    # grant at all.
    if actor.can(Permission.PAYMENTS):
        return
    raise PermissionDeniedError("You cannot raise an invoice on this project.")


def assert_may_manage(actor: User, invoice: Invoice, project: Project | None) -> None:
    if actor.role is UserRole.ADMIN:
        return
    if (
        actor.role is UserRole.CREATOR
        and project is not None
        and project.creator_id == actor.id
    ):
        return
    if actor.can(Permission.PAYMENTS):
        return
    raise PermissionDeniedError("You cannot manage this invoice.")


def assert_may_confirm_money(actor: User, action: str) -> None:
    """Declaring that money moved is not the job of whoever raised the bill.

    A creator invoicing against their own bank account must not also be the
    one who says it was paid — that separation is the whole control, and it
    is why this is deliberately not `assert_may_manage`.

    A coordinator granted Payments may do it: they are not the party being
    paid, so admitting them keeps the separation intact while meaning the
    grant is worth having.
    """
    if actor.role is UserRole.ADMIN:
        return
    if actor.role is UserRole.COORDINATOR and actor.can(Permission.PAYMENTS):
        return
    raise PermissionDeniedError(f"Only an administrator can {action}.")


def visible_customer_id(actor: User) -> UUID | None:
    return actor.id if actor.role is UserRole.CUSTOMER else None
