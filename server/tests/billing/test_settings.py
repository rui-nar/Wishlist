"""The billing settings: what each state needs, by variable (premium plan D9, D16)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.settings import Settings

LOCAL = {
    "stripe_secret_key": "sk_test_placeholder",
    "stripe_webhook_secret": "whsec_placeholder",
    "stripe_price_id": "price_placeholder",
    "billing_price_amount": "10.00",
    "public_base_url": "https://shushgift.example.test",
}
PRODUCTION_ONLY = {
    "stripe_automatic_tax": True,
    "billing_terms_version": "2026-11",
    "billing_consent_text_en": "Placeholder consent",
    "billing_consent_text_fr": "Consentement fictif",
    "legal_terms_url": "https://shushgift.example.test/terms",
    "legal_privacy_url": "https://shushgift.example.test/privacy",
    "legal_withdrawal_url": "https://shushgift.example.test/withdrawal",
}
PRODUCTION = (
    LOCAL
    | PRODUCTION_ONLY
    | {"app_env": "production", "stripe_secret_key": "sk_live_placeholder"}
)


@pytest.fixture(autouse=True)
def nothing_from_the_environment(monkeypatch):
    """A developer's shell may hold these (the dev scripts load `.env`)."""
    for name in Settings.model_fields:
        if name != "database_url":
            monkeypatch.delenv(name.upper(), raising=False)


def settings(**values) -> Settings:
    return Settings(database_url="postgresql+psycopg://x:y@localhost/z", **values)


def test_everything_unset_is_no_gateway_not_selling_not_enforced():
    unset = settings()
    assert unset.missing_gateway_settings == [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    ]
    assert unset.missing_selling_settings == [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_ID",
        "BILLING_PRICE_AMOUNT",
        "PUBLIC_BASE_URL",
    ]
    assert not unset.billing_gateway_configured
    assert not unset.billing_selling
    assert not unset.billing_enforce_limits
    assert not unset.limits_enforced
    assert unset.billing_price is None


def test_the_defaults():
    defaults = settings()
    assert defaults.free_max_lists == 1
    assert defaults.free_max_gifts_per_list == 20
    assert defaults.billing_price_currency == "EUR"
    assert defaults.stripe_automatic_tax is False


@pytest.mark.parametrize("field", ["free_max_lists", "free_max_gifts_per_list"])
def test_a_limit_cannot_be_negative_and_can_be_zero(field):
    assert getattr(settings(**{field: 0}), field) == 0
    with pytest.raises(ValidationError):
        settings(**{field: -1})


def test_the_limits_read_their_variables(monkeypatch):
    monkeypatch.setenv("FREE_MAX_LISTS", "3")
    monkeypatch.setenv("FREE_MAX_GIFTS_PER_LIST", "50")
    assert settings().free_max_lists == 3
    assert settings().free_max_gifts_per_list == 50


def test_enforcement_without_selling_is_not_enforced():
    assert not settings(billing_enforce_limits=True).limits_enforced


def test_selling_without_enforcement_is_not_enforced():
    configured = settings(**LOCAL)
    assert configured.billing_selling
    assert not configured.limits_enforced


def test_the_billing_on_fixture_enforces_limits(billing_on):
    assert settings(**billing_on).limits_enforced


def test_the_two_secrets_alone_are_a_gateway_that_does_not_sell():
    gateway = settings(
        billing_enforce_limits=True,
        stripe_secret_key="sk_test_placeholder",
        stripe_webhook_secret="whsec_placeholder",
    )
    assert gateway.billing_gateway_configured
    assert gateway.missing_gateway_settings == []
    assert not gateway.billing_selling
    assert not gateway.limits_enforced
    assert gateway.missing_selling_settings == [
        "STRIPE_PRICE_ID",
        "BILLING_PRICE_AMOUNT",
        "PUBLIC_BASE_URL",
    ]


@pytest.mark.parametrize("secret", ["stripe_secret_key", "stripe_webhook_secret"])
def test_without_a_secret_there_is_no_gateway(secret):
    missing = settings(**LOCAL | {secret: " "})
    assert missing.missing_gateway_settings == [secret.upper()]
    assert not missing.billing_gateway_configured
    assert not missing.billing_selling


@pytest.mark.parametrize(
    "field",
    [
        "stripe_price_id",
        "billing_price_amount",
        "billing_price_currency",
        "public_base_url",
    ],
)
def test_a_selling_variable_cleared_keeps_the_gateway_and_withdraws_the_offer(field):
    cleared = settings(**LOCAL | {"billing_enforce_limits": True, field: ""})
    assert cleared.billing_gateway_configured
    assert not cleared.billing_selling
    assert not cleared.limits_enforced
    assert cleared.missing_selling_settings == [field.upper()]


@pytest.mark.parametrize("app_env", ["dev", "validation"])
@pytest.mark.parametrize("prefix", ["sk_live_", "rk_live_", " sk_live_"])
def test_a_live_key_outside_production_is_missing_and_no_gateway(app_env, prefix):
    live = settings(**LOCAL | {"app_env": app_env, "stripe_secret_key": prefix + "x"})
    assert live.missing_gateway_settings == ["STRIPE_SECRET_KEY"]
    assert not live.billing_gateway_configured
    assert live.missing_selling_settings == ["STRIPE_SECRET_KEY"]


@pytest.mark.parametrize("key", ["sk_test_x", "rk_test_x", "anything"])
def test_a_key_that_is_not_live_is_missing_in_production(key):
    wrong = settings(**PRODUCTION | {"stripe_secret_key": key})
    assert wrong.missing_gateway_settings == ["STRIPE_SECRET_KEY"]
    assert not wrong.billing_gateway_configured
    assert not wrong.billing_selling


@pytest.mark.parametrize("key", ["sk_live_x", "rk_live_x"])
def test_production_with_everything_set_sells(key):
    production = settings(**PRODUCTION | {"stripe_secret_key": key})
    assert production.missing_selling_settings == []
    assert production.billing_gateway_configured
    assert production.billing_selling


@pytest.mark.parametrize("field", list(PRODUCTION_ONLY))
def test_each_production_only_variable_is_reported_as_selling_only(field):
    cleared = {field: False if field == "stripe_automatic_tax" else ""}
    production = settings(**PRODUCTION | cleared)
    assert production.missing_gateway_settings == []
    assert production.billing_gateway_configured
    assert production.missing_selling_settings == [field.upper()]
    assert not production.billing_selling


def test_the_production_only_variables_are_not_needed_elsewhere():
    assert settings(**LOCAL | {"app_env": "validation"}).billing_selling


@pytest.mark.parametrize(
    "amount", ["abc", "NaN", "Infinity", "-5", "1e3", "9,99", "1.999", "1_000", "0"]
)
def test_an_invalid_amount_is_missing(amount):
    invalid = settings(**LOCAL | {"billing_price_amount": amount})
    assert invalid.billing_price is None
    assert invalid.missing_selling_settings == ["BILLING_PRICE_AMOUNT"]
    assert invalid.billing_gateway_configured


@pytest.mark.parametrize(
    "amount, price",
    [
        ("9.99", Decimal("9.99")),
        (" 12 ", Decimal("12")),
        ("10.5", Decimal("10.5")),
    ],
)
def test_a_valid_amount_is_the_price(amount, price):
    valid = settings(**LOCAL | {"billing_price_amount": amount})
    assert valid.billing_price == price
    assert valid.billing_selling
