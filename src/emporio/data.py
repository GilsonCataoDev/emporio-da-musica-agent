"""Load the store CSVs into a SQLite database and clean them on the way in.

Cleaning decisions (also listed in the README):
- Prices and totals are stored as REAL in BRL, dates as ISO text.
- `specs` is kept as a JSON string so it can be searched and shown as-is.
- Empty tracking codes and notes become NULL.
- Product `status` is kept (active, discontinued, coming_soon). The tools decide what
  to show, the data layer does not throw anything away.
- Promotions are kept with their `is_active` flag. Only active ones change a price.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = ROOT / "emporio.db"

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    price_brl REAL NOT NULL,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(category_id),
    description TEXT,
    stock_quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    specs TEXT,
    created_at TEXT
);
CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    discount_percent REAL NOT NULL,
    description TEXT,
    is_active INTEGER NOT NULL
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    city TEXT
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_brl REAL NOT NULL,
    payment_method TEXT,
    tracking_code TEXT,
    estimated_delivery TEXT,
    notes TEXT
);
CREATE TABLE order_items (
    order_id INTEGER REFERENCES orders(order_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL
);
"""


def _rows(name: str) -> list[dict[str, str]]:
    with open(DATA_DIR / f"{name}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _none(value: str) -> str | None:
    value = (value or "").strip()
    return value or None


def build_database(db_path: Path = DB_PATH) -> Path:
    """(Re)create the SQLite database from the CSV files."""
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    con.executemany(
        "INSERT INTO categories VALUES (?, ?, ?)",
        [(int(r["category_id"]), r["name"].strip(), _none(r["description"])) for r in _rows("categories")],
    )
    products = []
    for r in _rows("products"):
        specs = _none(r["specs"])
        if specs:
            json.loads(specs)  # fail loudly if a row is malformed
        products.append(
            (
                int(r["product_id"]),
                float(r["price_brl"]),
                r["name"].strip(),
                int(r["category_id"]),
                _none(r["description"]),
                int(r["stock_quantity"]),
                r["status"].strip(),
                specs,
                _none(r["created_at"]),
            )
        )
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)", products)
    con.executemany(
        "INSERT INTO promotions VALUES (?,?,?,?,?)",
        [
            (int(r["promotion_id"]), int(r["product_id"]), float(r["discount_percent"]),
             _none(r["description"]), int(r["is_active"]))
            for r in _rows("promotions")
        ],
    )
    con.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?)",
        [
            (int(r["customer_id"]), r["name"].strip(), _none(r["phone"]),
             (_none(r["email"]) or "").lower() or None, _none(r["city"]))
            for r in _rows("customers")
        ],
    )
    con.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (int(r["order_id"]), int(r["customer_id"]), r["order_date"], r["status"].strip(),
             float(r["total_brl"]), _none(r["payment_method"]), _none(r["tracking_code"]),
             _none(r["estimated_delivery"]), _none(r["notes"]))
            for r in _rows("orders")
        ],
    )
    con.executemany(
        "INSERT INTO order_items VALUES (?,?,?)",
        [(int(r["order_id"]), int(r["product_id"]), int(r["quantity"])) for r in _rows("order_items")],
    )
    con.commit()
    con.close()
    return db_path


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the database, building it first if it does not exist yet."""
    if not db_path.exists():
        build_database(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


if __name__ == "__main__":
    path = build_database()
    con = sqlite3.connect(path)
    for table in ("categories", "products", "promotions", "customers", "orders", "order_items"):
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count} rows")
