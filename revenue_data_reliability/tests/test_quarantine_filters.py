"""Quarantine identifier extraction and published-query filter tests."""

from backend.services import publications, quarantines


def test_extract_record_id_supports_all_identifier_keys():
    assert quarantines.extract_record_id({"invoice_line_id": "11"}) == 11
    assert quarantines.extract_record_id({"invoice_id": 22}) == 22
    assert quarantines.extract_record_id({"customer_id": 33}) == 33
    assert quarantines.extract_record_id({"item_id": 44}) == 44
    assert quarantines.extract_record_id({"record_key": 55}) == 55
    assert quarantines.extract_record_id({"invoice_id": "n/a"}) is None


def test_quarantined_keys_builds_typed_sets(monkeypatch):
    rows = [
        {
            "record_keys": [
                {
                    "invoice_line_id": 1,
                    "invoice_id": 2,
                    "customer_id": 3,
                    "item_id": 4,
                },
                {"record_key": 5},
                {"invoice_id": 6, "customer_id": 7, "item_id": 8},
            ]
        }
    ]
    monkeypatch.setattr(quarantines, "fetch_all", lambda sql, params=None: rows)

    keys = quarantines.quarantined_keys(9)

    assert keys["invoice_line_ids"] == [1, 5]
    assert keys["invoice_ids"] == [2, 6]
    assert keys["customer_ids"] == [3, 7]
    assert keys["item_ids"] == [4, 8]


def test_published_query_applies_all_quarantine_keys(monkeypatch):
    keys = {
        "invoice_line_ids": [11],
        "invoice_ids": [22],
        "customer_ids": [33],
        "item_ids": [44],
    }
    monkeypatch.setattr(
        publications,
        "get_published_run",
        lambda dataset_name: {"id": 7},
    )
    monkeypatch.setattr(
        publications.quarantines_svc,
        "quarantined_keys",
        lambda run_id: keys,
    )
    monkeypatch.setattr(
        "backend.storage.s3_client.dataset_s3_prefix",
        lambda dataset_name: f"scenarios/{dataset_name}/",
    )

    query = publications.get_published_data_query("seed_101")
    sql = query["sql"]

    assert "il.invoice_line_id NOT IN (11)" in sql
    assert "il.invoice_id NOT IN (22)" in sql
    assert "il.item_id NOT IN (44)" in sql
    assert "WHERE customer_id IN (33)" in sql
    assert query["quarantine_keys"] == keys
