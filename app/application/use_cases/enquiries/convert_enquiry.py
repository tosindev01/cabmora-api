from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.enquiry import EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.user import User, UserRole
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.repositories.user_repository import UserRepository
from app.application.use_cases.invites.provision_account import (
    ProvisionAccount,
)
from app.application.use_cases.projects.create_project import CreateProject


@dataclass
class ConversionResult:
    project: Project
    #: None when the enquiry's address belongs to an account that is not a
    #: customer — the project is still created, unassigned.
    customer: User | None
    #: Present only when an account was created here; None if one already
    #: existed for this address.
    invite_url: str | None
    #: Something the admin needs to act on. Not an error: the work was created.
    warning: str | None = None


class ConvertEnquiry:
    """Turn a won lead into a project, with an account for the client.

    `first_name` and `last_name` are arguments rather than split from the
    enquiry's single `name` field. Splitting on the first space silently
    mangles "Mary Jane Watson" and "van der Berg", and this writes a real
    person's name into their account — the admin confirms it instead.
    """

    def __init__(
        self,
        enquiries: EnquiryRepository,
        users: UserRepository,
        create_customer: ProvisionAccount,
        create_project: CreateProject,
    ) -> None:
        self._enquiries = enquiries
        self._users = users
        self._create_customer = create_customer
        self._create_project = create_project

    async def execute(
        self,
        enquiry_id: UUID,
        actor: User,
        first_name: str,
        last_name: str,
        title: str,
        event_type: str | None = None,
        event_date: datetime | None = None,
        deadline: datetime | None = None,
    ) -> ConversionResult:
        enquiry = await self._enquiries.get_by_id(enquiry_id)
        if enquiry is None:
            raise EntityNotFoundError("Enquiry not found")
        if enquiry.status is EnquiryStatus.WON:
            raise ValidationError("This enquiry has already been converted.")

        # Reuse the account if we already know who this is. A returning
        # client, or a second enquiry from the same person, must not become a
        # duplicate.
        #
        # Whoever the enquiry was *stamped* with comes first, and the email
        # address only second. A client signed in as sam@gmail.com who typed
        # sam@work.com into the booking form is the same person, and the
        # address alone would hand them a second account and a second invite.
        # Falls through to the address when the stamp points at an account
        # that has since been deleted.
        existing: User | None = None
        if enquiry.customer_id is not None:
            existing = await self._users.get_by_id(enquiry.customer_id)
        if existing is None:
            existing = await self._users.get_by_email(enquiry.email.lower())
        customer: User | None = None
        invite_url: str | None = None
        warning: str | None = None

        if existing is None:
            provisioned = await self._create_customer.execute(
                email=enquiry.email,
                first_name=first_name,
                last_name=last_name,
                # Carried across, so the client the project points at is
                # somebody you can actually ring.
                phone=enquiry.phone,
                whatsapp=enquiry.whatsapp,
            )
            customer, invite_url = provisioned.user, provisioned.invite_url
        elif existing.role is UserRole.CUSTOMER:
            customer = existing
        else:
            # The address belongs to an admin or a creator. Attaching the
            # project to them would put a client's work in a staff portal and
            # break the rule that customers own projects — but refusing outright
            # would block real work over an email collision. So the project is
            # created unassigned and the admin is told to attach a client.
            warning = (
                f"{enquiry.email} belongs to a {existing.role.value} account, so the "
                "project was created without a client. Assign one from the project "
                "settings."
            )

        project = await self._create_project.execute(
            actor_id=actor.id,
            title=title,
            # BOOKED, not the DRAFT a project normally starts in. A draft is a
            # project being written and is invisible to the client by design —
            # but a converted enquiry is work that has been discussed, quoted
            # and won, and the client who just agreed to it should find it
            # waiting rather than nothing at all. Leaving it draft made
            # "move the stage" a step somebody had to remember in order for
            # the customer to see their own project.
            stage=ProjectStage.BOOKED,
            customer_id=customer.id if customer else None,
            event_type=event_type or enquiry.event_type,
            # Confirmed at conversion, falling back to whatever the lead
            # already holds. Both travel with it, so the dates agreed on the
            # call are not re-typed — and mistyped — a week later, and a
            # project that reaches the client without an event date is one
            # nobody can schedule around.
            event_date=_as_date(event_date or enquiry.event_date),
            deadline=_as_date(deadline or enquiry.deadline),
            description=enquiry.message,
        )

        enquiry.status = EnquiryStatus.WON
        enquiry.customer_id = customer.id if customer else None
        enquiry.converted_project_id = project.id
        await self._enquiries.update(
            enquiry,
            EnquiryEvent(
                enquiry_id=enquiry.id,
                kind=EnquiryEventKind.WON,
                actor_id=actor.id,
                payload={
                    "project_id": str(project.id),
                    **({"warning": warning} if warning else {}),
                },
            ),
        )
        return ConversionResult(
            project=project, customer=customer, invite_url=invite_url, warning=warning
        )


def _as_date(value: "datetime | None") -> "date | None":
    """A project holds a date; an enquiry and a form both hand over an instant."""
    return value.date() if value else None
