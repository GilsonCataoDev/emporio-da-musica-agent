# Catalog search with a budget

Scenario `catalog-budget`. Data question: must query the catalog, respect the price ceiling and show real prices.
Model: `gemini-3.5-flash-lite`. Store date used for deadlines: 2026-02-20.

**Customer:** Oi! Quais opções de violões disponíveis custando até R$1000?

> tool `search_products` {"category": "Violões", "limit": 5, "max_price": 1000}
>   result: {"total_encontrado": 12, "produtos": [{"product_id": 83, "nome": "Tagima Memphis AC-39 Nylon Natural", "categoria": "Violões", "situacao": "disponível no catálogo", "estoque": 15, "preco_original": 429.9, "promocao": null, "preco_atual": 429.9, "preco_pix": 408.41}, {"product_id": 85, "nome": "Rozini RC-104 Nylon Estudante", "categoria": "Violões", "situacao": "disponível no catálogo", "estoque": 

**Maestro:** Opa, beleza? Dá uma olhada nessas opções de violões até R$ 1.000 que temos disponíveis por aqui:

1. **Tagima Memphis AC-39 Nylon Natural** – R$ 429,90
2. **Rozini RC-104 Nylon Estudante** – R$ 459,90
3. **Shelby SN-100 Folk Aço Preto** – R$ 549,00
4. **Giannini GF-1R Aço Folk Sunburst** – R$ 579,90
5. **Yamaha C40 Nylon Natural** – R$ 599,90

Temos mais algumas opções no estoque também, caso queira ver outras marcas ou modelos. Curte mais cordas de nylon ou de aço?
