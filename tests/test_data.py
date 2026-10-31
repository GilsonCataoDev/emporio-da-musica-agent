from emporio.data import build_database
from emporio.policies import load_chunks

import sqlite3


def test_database_row_counts(tmp_path):
    db = build_database(tmp_path / "test.db")
    con = sqlite3.connect(db)
    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("categories", "products", "promotions", "customers", "orders", "order_items")
    }
    assert counts == {
        "categories": 9, "products": 65, "promotions": 25,
        "customers": 50, "orders": 20, "order_items": 22,
    }


def test_empty_tracking_codes_are_null(tmp_path):
    con = sqlite3.connect(build_database(tmp_path / "test.db"))
    assert con.execute("SELECT COUNT(*) FROM orders WHERE tracking_code = ''").fetchone()[0] == 0


def test_policy_sections_are_split_by_heading():
    chunks = {c.number: c for c in load_chunks()}
    assert {"2", "3", "4.1", "4.2", "5.1", "6.2", "8.1"} <= set(chunks)
    assert "7 (sete) dias" in chunks["4.1"].text
    assert "não são cumulativas" in chunks["6.2"].text


def test_numbered_list_items_are_not_headings():
    numbers = [c.number for c in load_chunks()]
    assert numbers.count("5") <= 1
    assert "Fechamento" in next(c for c in load_chunks() if c.number == "7.2").text
