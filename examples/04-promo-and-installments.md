# Active promotion and installments

Scenario `promo-and-installments`. Rules interplay: promotional price, no PIX discount on promotions, installment limits.
Model: `gemini-3.1-flash-lite`. Store date used for deadlines: 2026-02-20.

**Customer:** Quanto está o Taylor 110e?

> tool `get_product` {"name_or_id": "Taylor 110e"}
>   result: {"product_id": 94, "nome": "Taylor 110e Dreadnought Natural", "categoria": "Violões", "situacao": "disponível no catálogo", "estoque": 4, "preco_original": 5999.0, "promocao": "Desconto Exclusivo (8% de desconto)", "preco_atual": 5519.08, "preco_pix": null, "observacao_pix": "O desconto de 5% do PIX não se aplica a preços promocionais.", "encontrado": true, "descricao": "Violão dreadnought Taylor 

**Maestro:** O **Taylor 110e Dreadnought Natural** está com desconto! 

* **Preço original:** R$ 5.999,00
* **Desconto:** 8%
* **Preço atual:** R$ 5.519,08

Temos 4 unidades dele aqui na loja. Quer saber sobre as formas de pagamento ou o frete para a sua cidade?

**Customer:** E se eu quiser parcelar no cartão, em quantas vezes sem juros?

> tool `get_product` {"name_or_id": "Taylor 110e"}
>   result: {"product_id": 94, "nome": "Taylor 110e Dreadnought Natural", "categoria": "Violões", "situacao": "disponível no catálogo", "estoque": 4, "preco_original": 5999.0, "promocao": "Desconto Exclusivo (8% de desconto)", "preco_atual": 5519.08, "preco_pix": null, "observacao_pix": "O desconto de 5% do PIX não se aplica a preços promocionais.", "encontrado": true, "descricao": "Violão dreadnought Taylor 
> tool `get_payment_options` {"product_id": 94}
>   result: {"valor": 5519.08, "preco_promocional": true, "pix": {"valor": null, "regra": "O desconto de 5% do PIX não se aplica a preços promocionais; pagar no PIX custa o mesmo valor."}, "debito": "à vista, todas as bandeiras", "boleto": "à vista, compensação em até 3 dias úteis", "credito": {"parcelas_maximas": 12, "valor_da_parcela": 459.92, "juros": "sem juros"}, "combinar_formas_de_pagamento": true}

**Maestro:** Para o Taylor 110e, você pode parcelar em até **12 vezes de R$ 459,92 sem juros** no cartão de crédito.

Como ele já está com um preço promocional, o valor total para pagamento no PIX é o mesmo (R$ 5.519,08). 

Quer que eu verifique o prazo de entrega para o seu endereço? Se sim, é só me passar a sua cidade!
