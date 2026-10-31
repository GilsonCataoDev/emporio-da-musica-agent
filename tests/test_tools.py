import pytest

from emporio import tools


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from emporio import data

    path = data.build_database(tmp_path / "t.db")
    monkeypatch.setattr(data, "DB_PATH", path)
    monkeypatch.setattr(tools, "connect", lambda: data.connect(path))
    monkeypatch.setenv("EMPORIO_TODAY", "2026-03-20")


# ------------------------------------------------------------------ products

def test_search_respects_price_ceiling_and_category():
    result = tools.search_products(category="Violões", max_price=1000)
    assert result["produtos"], "expected some guitars under R$1000"
    assert all(p["preco_atual"] <= 1000 for p in result["produtos"])
    assert all(p["categoria"] == "Violões" for p in result["produtos"])
    prices = [p["preco_atual"] for p in result["produtos"]]
    assert prices == sorted(prices)


def test_search_never_returns_unavailable_products():
    result = tools.search_products(limit=20)
    assert all(p["estoque"] > 0 and p["situacao"].startswith("disponível") for p in result["produtos"])


def test_gd20_from_the_brief_is_sellable():
    info = tools.get_product("Takamine GD20")
    assert info["encontrado"] is True
    assert info["disponivel_para_compra"] is True
    assert info["preco_original"] == 2199.0


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Shelby SN-7C", "descontinuado"),       # discontinued, no stock
        ("Ibanez Bass 2X", "descontinuado"),     # discontinued but still has units in stock
        ("Kala KA-ABP-CTG", "em breve"),         # coming soon
        ("Giannini GF-3D", "sem estoque"),       # active but out of stock
    ],
)
def test_unavailable_products_are_reported_with_alternatives(name, expected):
    info = tools.get_product(name)
    assert info["encontrado"] is True
    assert info["disponivel_para_compra"] is False
    assert expected in info["situacao"]
    assert info["alternativas"]
    assert all(a["categoria"] == info["categoria"] for a in info["alternativas"])
    assert all(a["estoque"] > 0 and a["product_id"] != info["product_id"] for a in info["alternativas"])


def test_search_hides_discontinued_even_with_stock():
    ids = {p["product_id"] for p in tools.search_products(limit=20)["produtos"]}
    assert 113 not in ids  # discontinued, no stock
    assert 136 not in ids  # discontinued, still has units
    assert 130 not in ids  # coming soon
    assert 96 not in ids   # active but out of stock


def test_unknown_product():
    assert tools.get_product("Fender Stratocaster Dourada")["encontrado"] is False


def test_pix_discount_does_not_stack_with_active_promotion():
    con = tools.connect()
    promo = con.execute(
        "SELECT p.name, p.price_brl, pr.discount_percent FROM promotions pr "
        "JOIN products p USING (product_id) WHERE pr.is_active = 1 AND p.status='active' LIMIT 1"
    ).fetchone()
    info = tools.get_product(promo["name"])
    assert info["preco_pix"] is None
    assert info["preco_atual"] == pytest.approx(promo["price_brl"] * (1 - promo["discount_percent"] / 100), abs=0.01)
    assert info["preco_original"] == promo["price_brl"]


def test_expired_promotion_is_ignored():
    con = tools.connect()
    row = con.execute(
        "SELECT p.name, p.price_brl FROM promotions pr JOIN products p USING (product_id) "
        "WHERE pr.is_active = 0 AND p.status='active' AND p.product_id NOT IN "
        "(SELECT product_id FROM promotions WHERE is_active = 1) LIMIT 1"
    ).fetchone()
    info = tools.get_product(row["name"])
    assert info["promocao"] is None
    assert info["preco_atual"] == row["price_brl"]
    assert info["preco_pix"] == pytest.approx(row["price_brl"] * 0.95, abs=0.01)


# -------------------------------------------------------------------- orders

def _order(status):
    con = tools.connect()
    return con.execute(
        "SELECT o.order_id, c.email, c.phone FROM orders o JOIN customers c USING (customer_id) "
        "WHERE o.status = ? LIMIT 1", (status,)
    ).fetchone()


def test_order_requires_matching_identity():
    o = _order("shipped")
    assert tools.get_order_status(o["order_id"], o["email"])["encontrado"] is True
    assert tools.get_order_status(o["order_id"], o["phone"])["encontrado"] is True
    assert tools.get_order_status(o["order_id"], "outra@pessoa.com")["encontrado"] is False
    assert tools.get_order_status(o["order_id"], "")["encontrado"] is False


def test_wrong_identity_and_missing_order_give_the_same_answer():
    o = _order("shipped")
    assert tools.get_order_status(o["order_id"], "x@y.com") == tools.get_order_status(9999, "x@y.com")


def test_phone_match_ignores_formatting():
    o = _order("delivered")
    digits_only = "".join(ch for ch in o["phone"] if ch.isdigit())
    assert tools.get_order_status(o["order_id"], digits_only)["encontrado"] is True


def test_short_digit_string_does_not_match_a_phone():
    o = _order("delivered")
    assert tools.get_order_status(o["order_id"], "99")["encontrado"] is False


def test_return_regret_outside_window():
    o = _order("delivered")
    res = tools.check_return_eligibility(o["order_id"], o["email"], "regret")
    assert res["elegivel"] is False  # all delivered sample orders are older than 7 days
    assert res["regra"].startswith("4.1")


def test_return_regret_inside_window(monkeypatch):
    o = _order("delivered")
    est = tools.connect().execute("SELECT estimated_delivery FROM orders WHERE order_id=?", (o["order_id"],)).fetchone()[0]
    monkeypatch.setenv("EMPORIO_TODAY", est)
    assert tools.check_return_eligibility(o["order_id"], o["email"], "regret")["elegivel"] is True


def test_defect_after_30_days_points_to_legal_warranty(monkeypatch):
    o = _order("delivered")
    row = tools.connect().execute("SELECT order_date, estimated_delivery FROM orders WHERE order_id=?", (o["order_id"],)).fetchone()
    from datetime import date, timedelta
    monkeypatch.setenv("EMPORIO_TODAY", (date.fromisoformat(row["order_date"]) + timedelta(days=40)).isoformat())
    res = tools.check_return_eligibility(o["order_id"], o["email"], "defect")
    assert res["elegivel"] is False
    assert "garantia" in res["proximo_passo"].lower()


def test_return_on_undelivered_and_cancelled_orders():
    pend = _order("pending")
    assert tools.check_return_eligibility(pend["order_id"], pend["email"], "regret")["elegivel"] is None
    canc = _order("cancelled")
    assert tools.check_return_eligibility(canc["order_id"], canc["email"], "regret")["elegivel"] is False


def test_return_invalid_reason():
    o = _order("delivered")
    assert "erro" in tools.check_return_eligibility(o["order_id"], o["email"], "porque sim")


# ------------------------------------------------------------ policies, payment

def test_policy_retrieval_routes_common_questions():
    top = lambda q: tools.search_policies(q)["secoes"][0]["secao"]
    assert top("Me arrependi da compra, posso devolver?").startswith("4.1")
    assert top("Qual o horário de funcionamento?").startswith("2")
    sections = [x["secao"] for x in tools.search_policies("vocês vendem cordas e palhetas?")["secoes"]]
    assert any(x.startswith("7.1") for x in sections)  # scope rule: accessories are not sold
    pix = [x["secao"] for x in tools.search_policies("aceita pix? tem desconto?")["secoes"]]
    assert any(x.startswith("3 ") for x in pix)
    assert top("quanto tempo de garantia?").startswith("8")


def test_policy_retrieval_for_unrelated_query():
    assert tools.search_policies("receita de bolo de cenoura")["encontrado"] is False


@pytest.mark.parametrize(
    "amount, expected",
    [(40, 1), (120, 2), (150, 3), (480, 6), (600, 6), (1200, 12), (999, 9), (100, 2)],
)
def test_max_installments(amount, expected):
    assert tools.get_payment_options(amount)["credito"]["parcelas_maximas"] == expected


def test_payment_pix_value():
    assert tools.get_payment_options(1000)["pix"]["valor"] == 950.0


def test_shipping_local_and_remote():
    assert tools.get_shipping_info("Campo Grande", 500)["frete"] == 35.0   # "acima de" 500
    assert tools.get_shipping_info("campo grande", 500.01)["frete"] == 0.0
    assert tools.get_shipping_info("São Paulo", 900)["frete"] is None


def test_call_tool_handles_bad_input():
    assert "erro" in tools.call_tool("nao_existe", {})
    assert "erro" in tools.call_tool("get_product", {"errado": 1})
    assert tools.call_tool("get_product", {"name_or_id": "81"})["encontrado"] is True
