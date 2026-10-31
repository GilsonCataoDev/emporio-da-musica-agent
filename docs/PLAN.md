# Original plan (kept for reference; the README describes what was built)

Customer-service agent for Empório da Música (fictional musical instrument store, Campo Grande/MS).

## Approach: tool-calling agent with a small RAG layer for policies

Pure RAG is the wrong fit for most of the questions this agent gets. Prices, stock,
promotions and order status live in structured tables and need exact answers, so the
agent queries them through typed tools (function calling). The policy manual is short,
sectioned prose, so it goes through a lightweight retrieval step. The LLM decides which
tool to call, so the "data vs. policy" routing from the brief is the model's job and is
testable.

| Question type | Source | Mechanism |
|---|---|---|
| Price, stock, catalog search | `products`, `categories`, `promotions` | tool: `search_products`, `get_product` |
| Order status, tracking | `orders`, `order_items`, `customers` | tool: `get_order_status` (identity check first) |
| Returns, shipping, payment, hours | `políticas_da_loja.pdf` | tool: `search_policies` (section-level retrieval) |
| Off-topic | none | system prompt scope rules, polite refusal |

## Steps

1. **Data foundation.** Load the CSVs into SQLite, clean them (types, JSON `specs`,
   inactive products, expired promotions), and extract the policy PDF into
   section-level chunks.
2. **Tools.** Write the typed tools and unit-test them without any LLM.
3. **Agent loop.** Persona and scope in the system prompt, tool-calling loop,
   conversation history persisted per session.
4. **Evaluation.** Scripted scenarios (catalog, price, returns, order status, off-topic,
   prompt injection) with expected behaviour, plus 3 to 5 recorded conversations.
5. **Delivery.** README (setup, decisions, limitations, AI-assistant usage), final
   check from a clean clone, then submit the link.

## Assumptions

Documented here and repeated in the README as they are confirmed against the data.
