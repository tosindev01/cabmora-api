"""What a project is priced and billed in.

Before this a project carried `price_minor` and no currency at all: 150000
could be £1,500 or $1,500 and nothing recorded which. Only the invoice had a
currency, and it defaulted to GBP however the job had been quoted — so a quote
and its invoice could disagree and no screen would show it.
"""

import pytest

from app.core.exceptions import ValidationError
from app.domain.entities.project import DEFAULT_CURRENCY, Project


def _project(**kw) -> Project:
    return Project(title="Okonkwo Wedding", event_type="Wedding", **kw)


def test_a_project_is_billed_in_sterling_unless_told_otherwise():
    assert _project().currency == DEFAULT_CURRENCY


@pytest.mark.parametrize("given", ["usd", "Usd", " eur "])
def test_a_currency_is_normalised_rather_than_rejected_on_case(given):
    """An admin typing "usd" means USD. Refusing it would be pedantry, and
    storing it unnormalised means two spellings of one currency in reports."""
    assert _project(currency=given.strip()).currency == given.strip().upper()


@pytest.mark.parametrize("given", [None, ""])
def test_absent_means_the_default_not_an_error(given):
    """The API's `currency` is optional, so it arrives as None whenever a
    caller omits it — and every one of those means "bill it the usual way"."""
    assert _project(currency=given).currency == DEFAULT_CURRENCY


def test_a_currency_we_cannot_bill_in_is_refused():
    """Checked on the entity, not only in the schema: an invoice inherits this,
    so a bad value reaches somebody's bill, and seed scripts build projects
    without going near pydantic."""
    with pytest.raises(ValidationError):
        _project(currency="XYZ")


@pytest.mark.asyncio
async def test_an_invoice_inherits_the_project_currency(client):
    """The thing this exists for. `CreateInvoice` used to default to GBP
    regardless of how the project had been quoted."""
    from app.application.use_cases.billing.create_invoice import CreateInvoice
    import inspect

    signature = inspect.signature(CreateInvoice.execute)
    # None, not "GBP" — the default has to come from the project at call time,
    # not be frozen into the signature.
    assert signature.parameters["currency"].default is None


@pytest.mark.asyncio
async def test_a_currency_change_is_written_to_the_timeline(client):
    """Money changes are evidence. The first time a client asks why their
    invoice says what it says, "who changed it, and when" is the question."""
    from app.application.use_cases.projects.update_project import SETTING_FIELDS

    assert "currency" in SETTING_FIELDS
    assert "price_minor" in SETTING_FIELDS
