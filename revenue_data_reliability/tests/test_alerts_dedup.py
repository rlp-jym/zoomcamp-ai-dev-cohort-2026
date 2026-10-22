"""Tests for alert deduplication."""


def test_alert_dedup():
    from backend.db.connection import execute
    from backend.services import alerts

    anchor = "dedup-test-anchor"
    execute("DELETE FROM alerts WHERE anchor_id = %s", (anchor,))

    first = alerts.raise_alert("RECON_DRIFT", "run", anchor, "first")
    second = alerts.raise_alert("RECON_DRIFT", "run", anchor, "second")

    assert first["created"] is True
    assert second["created"] is False
    assert second["alert_id"] == first["alert_id"]

    execute("DELETE FROM alerts WHERE anchor_id = %s", (anchor,))