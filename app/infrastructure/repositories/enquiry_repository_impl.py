from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, nullslast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.consultation import Consultation
from app.domain.entities.enquiry import OPEN_STATUSES, Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.infrastructure.models.enquiry import (
    ConsultationModel,
    EnquiryEventModel,
    EnquiryModel,
)


#: Derived from the domain's own set rather than retyped here — a status
#: added to `OPEN_STATUSES` has to appear in this query without anybody
#: remembering that this file exists.
_OPEN = [status.value for status in OPEN_STATUSES]


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything is stored UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class SqlAlchemyEnquiryRepository(EnquiryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _filters(
        status: EnquiryStatus | None, assigned_to: UUID | None, search: str | None
    ) -> list:
        """Shared by list_all and count_all so a page and its total cannot
        describe different result sets."""
        clauses = []
        if status is not None:
            clauses.append(EnquiryModel.status == status.value)
        if assigned_to is not None:
            clauses.append(EnquiryModel.assigned_to == str(assigned_to))
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            clauses.append(
                or_(
                    func.lower(EnquiryModel.name).like(term),
                    func.lower(EnquiryModel.email).like(term),
                    func.lower(EnquiryModel.event_type).like(term),
                )
            )
        return clauses

    async def add(self, enquiry: Enquiry, event: EnquiryEvent) -> Enquiry:
        model = EnquiryModel.from_entity(enquiry)
        self._session.add(model)
        self._session.add(EnquiryEventModel.from_entity(event))
        # One commit: an enquiry with no RECEIVED event is a hole in the trail.
        await self._session.commit()
        return model.to_entity()

    async def get_by_id(self, enquiry_id: UUID) -> Enquiry | None:
        model = await self._session.get(EnquiryModel, str(enquiry_id))
        return model.to_entity() if model else None

    async def update(self, enquiry: Enquiry, event: EnquiryEvent | None = None) -> Enquiry:
        model = await self._session.get(EnquiryModel, str(enquiry.id))
        if model is None:
            raise EntityNotFoundError("Enquiry not found")

        model.status = enquiry.status.value
        model.assigned_to = str(enquiry.assigned_to) if enquiry.assigned_to else None
        model.customer_id = str(enquiry.customer_id) if enquiry.customer_id else None
        model.converted_project_id = (
            str(enquiry.converted_project_id) if enquiry.converted_project_id else None
        )
        model.budget_min_minor = enquiry.budget_min_minor
        model.budget_max_minor = enquiry.budget_max_minor

        # The submitted details, editable since 2026-10-01. Listed here one by
        # one rather than copied wholesale: this method used to skip them on
        # purpose, and a blanket copy would have silently started writing
        # whatever a future field turns out to be.
        model.first_name = enquiry.first_name
        model.last_name = enquiry.last_name
        model.phone = enquiry.phone
        model.whatsapp = enquiry.whatsapp
        model.event_type = enquiry.event_type
        model.message = enquiry.message
        model.event_date = enquiry.event_date
        model.deadline = enquiry.deadline
        # `email` is absent on purpose. It identifies the lead — every message
        # already sent went to it, and conversion matches an account on it.

        if event is not None:
            self._session.add(EnquiryEventModel.from_entity(event))
        await self._session.commit()
        return model.to_entity()

    async def list_all(
        self,
        limit: int = 30,
        offset: int = 0,
        status: EnquiryStatus | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
    ) -> list[Enquiry]:
        stmt = (
            select(EnquiryModel)
            .where(*self._filters(status, assigned_to, search))
            .order_by(EnquiryModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [m.to_entity() for m in result.scalars().all()]

    async def list_open_by_event_date(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[Enquiry]:
        stmt = (
            select(EnquiryModel)
            .where(EnquiryModel.status.in_(_OPEN))
            # `nullslast` explicitly. Postgres sorts NULLs last on ASC and
            # SQLite sorts them first, so leaving it to the default would put
            # every undated enquiry at the top of the urgency table on the
            # developer's machine and the bottom in production — the same code
            # reading as two different features.
            # The second term is a tiebreak, so a page boundary cannot drop or
            # repeat a row. Two weddings on the same Saturday are common, and
            # without it their relative order is whatever the planner feels
            # like — which can differ between two requests for the same page.
            .order_by(
                nullslast(EnquiryModel.event_date.asc()),
                EnquiryModel.created_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [m.to_entity() for m in result.scalars().all()]

    async def count_open(self) -> int:
        stmt = (
            select(func.count())
            .select_from(EnquiryModel)
            .where(EnquiryModel.status.in_(_OPEN))
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def count_all(
        self,
        status: EnquiryStatus | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(EnquiryModel)
            .where(*self._filters(status, assigned_to, search))
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def list_events(self, enquiry_id: UUID) -> list[EnquiryEvent]:
        stmt = (
            select(EnquiryEventModel)
            .where(EnquiryEventModel.enquiry_id == str(enquiry_id))
            # Oldest first: this renders as a timeline, which reads forwards.
            .order_by(EnquiryEventModel.occurred_at.asc())
        )
        result = await self._session.execute(stmt)
        return [m.to_entity() for m in result.scalars().all()]

    async def add_event(self, event: EnquiryEvent) -> EnquiryEvent:
        model = EnquiryEventModel.from_entity(event)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def add_consultation(self, consultation: Consultation) -> Consultation:
        model = ConsultationModel.from_entity(consultation)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def list_consultations(self, enquiry_id: UUID) -> list[Consultation]:
        stmt = (
            select(ConsultationModel)
            .where(ConsultationModel.enquiry_id == str(enquiry_id))
            .order_by(ConsultationModel.scheduled_at.asc())
        )
        result = await self._session.execute(stmt)
        return [m.to_entity() for m in result.scalars().all()]

    async def list_consultations_between(
        self, start: datetime, end: datetime
    ) -> list[Consultation]:
        # Overlap, not containment: a call that starts before the window and
        # runs into it still occupies time the admin is looking at. Filtering on
        # `scheduled_at BETWEEN start AND end` would hide it and then offer a
        # slot that is already taken.
        models = (
            await self._session.execute(
                select(ConsultationModel)
                .where(
                    ConsultationModel.cancelled_at.is_(None),
                    ConsultationModel.scheduled_at < end,
                )
                .order_by(ConsultationModel.scheduled_at.asc())
            )
        ).scalars().all()

        # The tail of the filter happens here rather than in SQL: a call's end is
        # `scheduled_at + duration_minutes`, and expressing that as an interval
        # portably across SQLite and Postgres costs more than it saves at these
        # volumes. The entity already owns the arithmetic.
        return [c for c in (m.to_entity() for m in models) if c.ends_at > _aware(start)]

    async def get_consultation(self, consultation_id: UUID) -> Consultation | None:
        model = await self._session.get(ConsultationModel, str(consultation_id))
        return model.to_entity() if model else None

    async def list_consultations_awaiting_reminder(
        self, now: datetime, lead_minutes: int
    ) -> list[Consultation]:
        models = (
            await self._session.execute(
                select(ConsultationModel)
                .where(
                    ConsultationModel.cancelled_at.is_(None),
                    ConsultationModel.reminder_sent_at.is_(None),
                    ConsultationModel.scheduled_at
                    <= now + timedelta(minutes=lead_minutes),
                )
                .order_by(ConsultationModel.scheduled_at.asc())
            )
        ).scalars().all()
        # The lower bound is applied here so the entity owns the rule and the
        # job cannot disagree with it about what "due" means.
        return [
            c
            for c in (m.to_entity() for m in models)
            if c.needs_reminder_at(_aware(now), lead_minutes)
        ]

    async def update_consultation(self, consultation: Consultation) -> Consultation:
        model = await self._session.get(ConsultationModel, str(consultation.id))
        if model is None:
            raise EntityNotFoundError("Consultation not found")
        model.scheduled_at = consultation.scheduled_at
        model.duration_minutes = consultation.duration_minutes
        model.status = consultation.status.value
        model.meeting_url = consultation.meeting_url
        model.provider = consultation.provider.value
        model.cancelled_at = consultation.cancelled_at
        await self._session.commit()
        return model.to_entity()

    async def mark_reminder_sent(self, consultation_id: UUID, at: datetime) -> None:
        model = await self._session.get(ConsultationModel, str(consultation_id))
        if model is None:
            raise EntityNotFoundError("Consultation not found")
        model.reminder_sent_at = at
        await self._session.commit()
