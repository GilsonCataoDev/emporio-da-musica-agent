"""Tools the agent can call.

Every tool returns plain JSON-serialisable data. Money rules, dates and eligibility are
computed here in code, so the model only has to explain the result.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Callable

from .data import connect
from .retrieval import PolicyIndex
from .text import digits, normalize, tokens

PIX_DISCOUNT = 0.05
FREE_SHIPPING_MIN = 500.0
LOCAL_SHIPPING_FEE = 35.0
RETURN_WINDOW_DAYS = 7          # policy 4.1 (regret) and 4.3 (preference)
DEFECT_WINDOW_DAYS = 30         # policy 4.2
LEGAL_WARRANTY_DAYS = 90        # policy 8.1
CATEGORY_NAMES = [
    "Guitarras", "Baixos", "Baterias e Percussão", "Teclados e Pianos", "Violões",
    "Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)",
    "Cordas Orquestrais", "Ukuleles",
]

_STATUS_LABEL = {
    "active": "disponível no catálogo",
    "discontinued": "descontinuado (não faz mais parte do catálogo)",
    "coming_soon": "em breve (ainda não está à venda)",
}


def today() -> date:
    """The store's "today". Configurable because the sample orders are from 2025/2026."""
    override = os.environ.get("EMPORIO_TODAY")
    return date.fromisoformat(override) if override else date.today()


@lru_cache(maxsize=1)
def _policy_index() -> PolicyIndex:
    return PolicyIndex()


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


# --------------------------------------------------------------------------- products

def _price_block(con, product_id: int, price: float) -> dict[str, Any]:
    promo = con.execute(
        "SELECT discount_percent, description FROM promotions "
        "WHERE product_id = ? AND is_active = 1 ORDER BY discount_percent DESC LIMIT 1",
        (product_id,),
    ).fetchone()
    if promo:
        current = _money(price * (1 - promo["discount_percent"] / 100))
        return {
            "preco_original": price,
            "promocao": f'{promo["description"]} ({promo["discount_percent"]:g}% de desconto)',
            "preco_atual": current,
            "preco_pix": None,  # policy 6.2: PIX discount does not stack with promotions
            "observacao_pix": "O desconto de 5% do PIX não se aplica a preços promocionais.",
        }
    return {
        "preco_original": price,
        "promocao": None,
        "preco_atual": price,
        "preco_pix": _money(price * (1 - PIX_DISCOUNT)),
    }


def _product_summary(con, row) -> dict[str, Any]:
    return {
        "product_id": row["product_id"],
        "nome": row["name"],
        "categoria": row["category"],
        "situacao": _STATUS_LABEL.get(row["status"], row["status"]),
        "estoque": row["stock_quantity"],
        **_price_block(con, row["product_id"], row["price_brl"]),
    }


_PRODUCT_SQL = (
    "SELECT p.*, c.name AS category FROM products p JOIN categories c USING (category_id)"
)


def search_products(
    query: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Search the sellable catalog (active products with stock). Price filters use the current price."""
    con = connect()
    rows = con.execute(f"{_PRODUCT_SQL} WHERE p.status = 'active' AND p.stock_quantity > 0").fetchall()
    wanted = tokens(query or "")
    cat = normalize(category) if category else None
    results = []
    for row in rows:
        if cat and normalize(row["category"]) != cat:
            continue
        haystack = normalize(f'{row["name"]} {row["description"] or ""} {row["specs"] or ""} {row["category"]}')
        if any(t not in haystack for t in wanted):
            continue
        item = _product_summary(con, row)
        if min_price is not None and item["preco_atual"] < min_price:
            continue
        if max_price is not None and item["preco_atual"] > max_price:
            continue
        results.append(item)
    results.sort(key=lambda r: r["preco_atual"])
    limit = max(1, min(int(limit), 20))
    return {"total_encontrado": len(results), "produtos": results[:limit]}


def get_product(name_or_id: str) -> dict[str, Any]:
    """Look up one product by id or name, including discontinued ones, with alternatives if unavailable."""
    con = connect()
    row = None
    if str(name_or_id).strip().isdigit():
        row = con.execute(f"{_PRODUCT_SQL} WHERE p.product_id = ?", (int(name_or_id),)).fetchone()
    if row is None:
        wanted = tokens(str(name_or_id))
        if not wanted:
            return {"erro": "Informe o nome ou o código do produto."}
        best, best_hits = [], 0
        for r in con.execute(f"{_PRODUCT_SQL}").fetchall():
            name = normalize(r["name"])
            hits = sum(1 for t in wanted if t in name)
            if hits == len(wanted) and hits >= best_hits:
                best = best + [r] if hits == best_hits else [r]
                best_hits = hits
        if not best:
            return {"encontrado": False, "mensagem": "Nenhum produto com esse nome no catálogo."}
        if len(best) > 1:
            return {
                "encontrado": False,
                "mensagem": "Mais de um produto corresponde. Peça ao cliente para especificar.",
                "opcoes": [r["name"] for r in best[:8]],
            }
        row = best[0]

    info = _product_summary(con, row)
    info["encontrado"] = True
    info["descricao"] = row["description"]
    info["especificacoes"] = json.loads(row["specs"]) if row["specs"] else {}
    sellable = row["status"] == "active" and row["stock_quantity"] > 0
    info["disponivel_para_compra"] = sellable
    if not sellable:
        if row["status"] == "active":
            info["situacao"] = "temporariamente sem estoque"
        candidates = con.execute(
            f"{_PRODUCT_SQL} WHERE p.category_id = ? AND p.status = 'active' "
            "AND p.stock_quantity > 0 AND p.product_id != ?",
            (row["category_id"], row["product_id"]),
        ).fetchall()
        wanted = json.loads(row["specs"]) if row["specs"] else {}

        def distance(candidate) -> tuple:
            """Same kind of instrument first (strings, electronics), then closest price."""
            specs = json.loads(candidate["specs"]) if candidate["specs"] else {}
            mismatches = sum(1 for key in ("strings", "electronics") if wanted.get(key) != specs.get(key))
            return (mismatches, abs(candidate["price_brl"] - row["price_brl"]))

        alternatives = sorted(candidates, key=distance)[:3]
        info["alternativas"] = [_product_summary(con, a) for a in alternatives]
    return info


# ----------------------------------------------------------------------------- orders

def _find_customer_order(con, order_id: int, identifier: str):
    """Return (order, customer) only if the identifier matches the order's owner."""
    row = con.execute(
        "SELECT o.*, c.name AS customer_name, c.email, c.phone FROM orders o "
        "JOIN customers c USING (customer_id) WHERE o.order_id = ?",
        (order_id,),
    ).fetchone()
    ident = (identifier or "").strip().lower()
    if row is None or not ident:
        return None
    same_email = "@" in ident and ident == (row["email"] or "")
    id_digits = digits(ident)
    phone_digits = digits(row["phone"])
    same_phone = len(id_digits) >= 8 and phone_digits.endswith(id_digits[-9:])
    return row if (same_email or same_phone) else None


_NOT_FOUND = {
    "encontrado": False,
    "mensagem": (
        "Não encontrei esse pedido com os dados informados. Confira o número do pedido e "
        "o e-mail ou telefone do cadastro. Por segurança, não informo mais detalhes."
    ),
}

_ORDER_STATUS_LABEL = {
    "pending": "pendente (aguardando confirmação do pagamento)",
    "confirmed": "confirmado (em preparação, ainda não despachado)",
    "shipped": "enviado (a caminho)",
    "delivered": "entregue",
    "cancelled": "cancelado",
}


def get_order_status(order_id: int, email_or_phone: str) -> dict[str, Any]:
    """Order status and tracking. Requires the e-mail or phone registered on the order."""
    con = connect()
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return dict(_NOT_FOUND)
    order = _find_customer_order(con, oid, email_or_phone)
    if order is None:
        return dict(_NOT_FOUND)
    items = con.execute(
        "SELECT p.name, oi.quantity FROM order_items oi JOIN products p USING (product_id) "
        "WHERE oi.order_id = ?",
        (oid,),
    ).fetchall()
    return {
        "encontrado": True,
        "pedido": oid,
        "cliente": order["customer_name"],
        "data_do_pedido": order["order_date"],
        "status": _ORDER_STATUS_LABEL.get(order["status"], order["status"]),
        "itens": [{"produto": i["name"], "quantidade": i["quantity"]} for i in items],
        "total": order["total_brl"],
        "forma_de_pagamento": order["payment_method"],
        "codigo_de_rastreio": order["tracking_code"],
        "previsao_de_entrega": order["estimated_delivery"],
        "observacoes": order["notes"],
    }


def check_return_eligibility(order_id: int, email_or_phone: str, reason: str) -> dict[str, Any]:
    """Apply the return/exchange policy to an order. reason: regret, defect or preference."""
    reason = normalize(reason or "")
    kind = {
        "regret": "regret", "arrependimento": "regret",
        "defect": "defect", "defeito": "defect",
        "preference": "preference", "preferencia": "preference",
    }.get(reason)
    if kind is None:
        return {"erro": "Motivo inválido. Use: regret (arrependimento), defect (defeito) ou preference (preferência)."}

    con = connect()
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return dict(_NOT_FOUND)
    order = _find_customer_order(con, oid, email_or_phone)
    if order is None:
        return dict(_NOT_FOUND)

    status = order["status"]
    base = {"encontrado": True, "pedido": oid, "motivo": kind, "hoje": today().isoformat()}
    if status == "cancelled":
        return {**base, "elegivel": False, "explicacao": "O pedido foi cancelado, então não há o que devolver."}
    if status in ("pending", "confirmed", "shipped"):
        return {
            **base,
            "elegivel": None,
            "explicacao": (
                "O pedido ainda não foi entregue, então os prazos de devolução ainda não começaram. "
                "O prazo conta a partir do recebimento. Se o cliente quiser desistir antes disso, "
                "encaminhar para a equipe."
            ),
        }

    # delivered: the data only has the estimated delivery date, so it stands in for the receipt date.
    received = datetime.strptime(order["estimated_delivery"] or order["order_date"], "%Y-%m-%d").date()
    purchased = datetime.strptime(order["order_date"], "%Y-%m-%d").date()
    now = today()
    base["data_de_recebimento_considerada"] = received.isoformat()
    base["observacao"] = "Data de recebimento estimada a partir da previsão de entrega do pedido."

    if kind in ("regret", "preference"):
        limit = received + timedelta(days=RETURN_WINDOW_DAYS)
        ok = now <= limit
        rule = "4.1 Direito de Arrependimento" if kind == "regret" else "4.3 Trocas por Preferência"
        base.update(regra=rule, prazo_final=limit.isoformat(), elegivel=ok)
        base["explicacao"] = (
            f"Dentro do prazo de {RETURN_WINDOW_DAYS} dias corridos após o recebimento."
            if ok else
            f"O prazo de {RETURN_WINDOW_DAYS} dias corridos após o recebimento terminou em {limit.isoformat()}."
        )
        if ok:
            base["condicoes"] = (
                "Produto na embalagem original, sem sinais de uso, com acessórios e manuais. "
                + ("Reembolso na mesma forma de pagamento em até 10 dias úteis e frete de devolução por conta da loja."
                   if kind == "regret" else
                   "Troca sujeita à disponibilidade do produto desejado; diferença de valor cobrada ou reembolsada.")
            )
        elif kind == "regret":
            base["proximo_passo"] = "Se o produto tiver defeito de fabricação, outras regras podem se aplicar."
    else:
        limit = purchased + timedelta(days=DEFECT_WINDOW_DAYS)
        warranty_end = received + timedelta(days=LEGAL_WARRANTY_DAYS)
        in_exchange = now <= limit
        base.update(regra="4.2 Trocas por Defeito", prazo_final=limit.isoformat(), elegivel=in_exchange)
        if in_exchange:
            base["explicacao"] = f"Defeito de fabricação: troca em até {DEFECT_WINDOW_DAYS} dias corridos após a compra."
        else:
            base["explicacao"] = (
                f"O prazo de troca de {DEFECT_WINDOW_DAYS} dias após a compra terminou em {limit.isoformat()}."
            )
            if now <= warranty_end:
                base["proximo_passo"] = (
                    f"Ainda há garantia legal de {LEGAL_WARRANTY_DAYS} dias após o recebimento (até "
                    f"{warranty_end.isoformat()}, política 8.1). Encaminhar para a equipe avaliar."
                )
            else:
                base["proximo_passo"] = (
                    "Acionar a garantia do fabricante (política 8.2); a loja pode intermediar se o cliente pedir."
                )
        base["observacao_politica"] = "Danos por mau uso, queda, umidade ou modificações não são cobertos."
    return base


# ----------------------------------------------------------------------------- policies

def search_policies(query: str, top_k: int = 3) -> dict[str, Any]:
    """Retrieve the most relevant sections of the store policy manual."""
    hits = _policy_index().search(query, top_k=max(1, min(int(top_k), 5)))
    if not hits:
        return {"encontrado": False, "mensagem": "Nada no manual de políticas trata desse assunto."}
    return {
        "encontrado": True,
        "secoes": [{"secao": f"{c.number} {c.title}", "texto": c.text} for c, _ in hits],
    }


# ----------------------------------------------------------------------- payment & shipping

def get_payment_options(amount: float | None = None, product_id: int | None = None) -> dict[str, Any]:
    """Payment methods and installment limits (policy section 3).

    Pass `product_id` to price a single product: the current price is used and the PIX discount
    is withheld when the product has an active promotion (policy 6.2). `amount` alone is treated
    as a regular-priced total.
    """
    promotional = False
    if product_id is not None:
        con = connect()
        row = con.execute("SELECT product_id, price_brl, name FROM products WHERE product_id = ?", (int(product_id),)).fetchone()
        if row is None:
            return {"erro": f"Produto {product_id} não encontrado."}
        price = _price_block(con, row["product_id"], row["price_brl"])
        promotional = price["promocao"] is not None
        amount = price["preco_atual"]
    if amount is None:
        return {"erro": "Informe o valor da compra (amount) ou o código do produto (product_id)."}
    amount = float(amount)
    if amount <= 0:
        return {"erro": "O valor deve ser maior que zero."}

    best = 1
    for n in range(2, 13):
        parcel = amount / n
        min_parcel = 0.0 if n <= 3 else 80.0 if n <= 6 else 100.0
        if n <= 3 and parcel < 50.0:
            break
        if parcel >= min_parcel:
            best = n

    pix = (
        {"valor": None, "regra": "O desconto de 5% do PIX não se aplica a preços promocionais; pagar no PIX custa o mesmo valor."}
        if promotional
        else {"valor": _money(amount * (1 - PIX_DISCOUNT)), "regra": "5% de desconto sobre o preço de tabela"}
    )
    return {
        "valor": _money(amount),
        "preco_promocional": promotional,
        "pix": pix,
        "debito": "à vista, todas as bandeiras",
        "boleto": "à vista, compensação em até 3 dias úteis",
        "credito": {"parcelas_maximas": best, "valor_da_parcela": _money(amount / best), "juros": "sem juros"},
        "combinar_formas_de_pagamento": amount > 2000,
    }


def get_shipping_info(city: str, order_total: float) -> dict[str, Any]:
    """Shipping cost and lead time (policy section 5)."""
    total = float(order_total)
    if normalize(city or "").strip() == "campo grande":
        fee = 0.0 if total > FREE_SHIPPING_MIN else LOCAL_SHIPPING_FEE
        return {
            "regiao": "Campo Grande (entrega própria por motoboy)",
            "frete": fee,
            "frete_gratis": fee == 0.0,
            "prazo": "1 a 3 dias úteis",
            "observacao": "Frete grátis acima de R$ 500,00; abaixo disso, taxa fixa de R$ 35,00.",
        }
    return {
        "regiao": f"{city} (fora de Campo Grande)",
        "frete": None,
        "modalidades": [
            {"nome": "PAC (Correios)", "prazo": "5 a 12 dias úteis"},
            {"nome": "SEDEX (Correios)", "prazo": "2 a 5 dias úteis"},
            {"nome": "Jadlog (.package)", "prazo": "3 a 8 dias úteis"},
        ],
        "observacao": (
            "O valor do frete é calculado pelo CEP, peso e dimensões no fechamento do pedido. "
            "Instrumentos grandes podem ter cotação individual. Todos os envios têm seguro e rastreamento. "
            "O manual não lista quais cidades fazem parte da região metropolitana além de Campo Grande."
        ),
    }


# ------------------------------------------------------------------------------ registry

def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


TOOL_SCHEMAS = [
    _schema(
        "search_products",
        "Busca instrumentos disponíveis para compra (ativos e com estoque). Use para perguntas como "
        "'violões até R$1000'. Os filtros de preço usam o preço atual (com promoção).",
        {
            "query": {"type": "string", "description": "Marca, modelo ou característica (ex.: 'yamaha', 'nylon')."},
            "category": {"type": "string", "enum": CATEGORY_NAMES},
            "min_price": {"type": "number"},
            "max_price": {"type": "number"},
            "limit": {"type": "integer", "description": "Máximo de resultados (padrão 8)."},
        },
        [],
    ),
    _schema(
        "get_product",
        "Consulta um produto específico pelo nome ou código: preço, promoção, estoque e situação. "
        "Também encontra produtos descontinuados e, se indisponível, sugere alternativas.",
        {"name_or_id": {"type": "string"}},
        ["name_or_id"],
    ),
    _schema(
        "get_order_status",
        "Status e rastreio de um pedido. Exige o número do pedido E o e-mail ou telefone cadastrado.",
        {"order_id": {"type": "integer"}, "email_or_phone": {"type": "string"}},
        ["order_id", "email_or_phone"],
    ),
    _schema(
        "check_return_eligibility",
        "Aplica a política de troca/devolução a um pedido, calculando prazos. Exige número do pedido e "
        "e-mail ou telefone cadastrado.",
        {
            "order_id": {"type": "integer"},
            "email_or_phone": {"type": "string"},
            "reason": {"type": "string", "enum": ["regret", "defect", "preference"],
                       "description": "regret = arrependimento, defect = defeito, preference = preferência."},
        },
        ["order_id", "email_or_phone", "reason"],
    ),
    _schema(
        "search_policies",
        "Busca no manual de políticas da loja (horários, endereço, pagamento, troca, frete, garantia, "
        "promoções, privacidade, atendimento).",
        {"query": {"type": "string"}, "top_k": {"type": "integer"}},
        ["query"],
    ),
    _schema(
        "get_payment_options",
        "Formas de pagamento, valor no PIX e número máximo de parcelas. Para um produto específico, "
        "SEMPRE passe product_id (assim o PIX respeita as promoções). Use amount apenas para um total "
        "de várias peças ou valor avulso.",
        {
            "product_id": {"type": "integer", "description": "Código retornado por get_product ou search_products; nunca invente."},
            "amount": {"type": "number"},
        },
        [],
    ),
    _schema(
        "get_shipping_info",
        "Frete e prazo de entrega para uma cidade e um valor de pedido.",
        {"city": {"type": "string"}, "order_total": {"type": "number"}},
        ["city", "order_total"],
    ),
]

_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "search_products": search_products,
    "get_product": get_product,
    "get_order_status": get_order_status,
    "check_return_eligibility": check_return_eligibility,
    "search_policies": search_policies,
    "get_payment_options": get_payment_options,
    "get_shipping_info": get_shipping_info,
}


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Run a tool by name. Errors come back as data so the model can recover from them."""
    func = _FUNCTIONS.get(name)
    if func is None:
        return {"erro": f"Ferramenta desconhecida: {name}"}
    try:
        return func(**(arguments or {}))
    except TypeError as exc:
        return {"erro": f"Argumentos inválidos para {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
        return {"erro": f"Falha ao executar {name}: {exc}"}
