# Discontinued product

Scenario `discontinued-product`. Special situation from the manual: say it is gone and suggest available alternatives.
Model: `gemini-3.5-flash-lite`. Store date used for deadlines: 2026-02-20.

**Customer:** Vocês têm o violão Shelby SN-7C de 7 cordas?

> tool `get_product` {"name_or_id": "Shelby SN-7C"}
>   result: {"product_id": 113, "nome": "Shelby SN-7C 7 Cordas Nylon Natural", "categoria": "Violões", "situacao": "descontinuado (não faz mais parte do catálogo)", "estoque": 0, "preco_original": 749.0, "promocao": null, "preco_atual": 749.0, "preco_pix": 711.55, "encontrado": true, "descricao": "Violão 7 cordas clássico com acabamento natural e braço em cedro. Boa opção para estudantes de choro que buscam q

**Maestro:** O violão Shelby SN-7C de 7 cordas está descontinuado e não faz mais parte do nosso catálogo. 

Mas se você curte tocar um choro ou precisa de um violão de nylon, temos algumas alternativas bem legais disponíveis por aqui:

- **Yamaha C40 Nylon Natural**: R$ 599,90 (ou R$ 569,91 no PIX)
- **Giannini GN-15 Nylon Cedr Natural**: R$ 689,00 (ou R$ 654,55 no PIX)
- **Yamaha C70 Nylon Natural**: R$ 849,00 (ou R$ 806,55 no PIX)

Quer dar uma olhada em algum desses?
