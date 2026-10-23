"""Unit tests for validation rule SQL definitions."""

import pytest

from backend.services.validations import get_rule

RULE_IDS = [
    "VAL_AR_INVOICE_1TO1",
    "VAL_DUPLICATE_INVOICE_LINE",
    "VAL_FK_BACKORDER_ORDER_LINE",
    "VAL_FK_CUSTOMER_EXISTS",
    "VAL_FK_ITEM_EXISTS",
    "VAL_FK_RETURN_SHIPMENT",
    "VAL_FRESHNESS_GL",
    "VAL_FX_RATE_EXISTS",
    "VAL_ORDER_LINE_UNIQUE",
    "VAL_RECON_BILLINGS_GL",
    "VAL_RESTATEMENT_DETECTED",
    "VAL_SEGMENT_DRIFT",
]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_rule_exists_and_has_sql(rule_id):
    rule = get_rule(rule_id)
    assert rule is not None
    assert rule.get("sql")
    assert "{scenario}" in rule["sql"] or "{bucket}" in rule["sql"]
