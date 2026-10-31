# Empório da Música Agent

A customer-service agent for Empório da Música, a fictional musical instrument store in
Campo Grande/MS. It answers in Brazilian Portuguese as "Maestro", checks real data before
quoting prices, stock or order status, applies the store's return policy with real dates, and
politely declines anything outside the store's scope.

Built in Python for the Artefact AI Engineer technical challenge.

```
Você: Me arrependi da minha compra, posso devolver meu pedido?
Maestro: ... me informe o número do pedido e o e-mail ou telefone que usou na compra.
Você: É o pedido 7, meu e-mail é leticia.rocha@jmail.com
  [tool] check_return_eligibility(order_id=7, reason="regret")
Maestro: Leticia, seu pedido 7 ainda está dentro do prazo. Você tem até 24/02/2026 ...
```

Full conversations are in [examples/](examples/).

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/GilsonCataoDev/emporio-da-musica-agent
cd emporio-da-musica-agent
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # Windows: copy .env.example .env
```

Put a free Gemini API key in `.env` (get one at https://aistudio.google.com/apikey):

```
GEMINI_API_KEY=your_key_here
```

Run the chat:

```bash
emporio                           # or: python -m emporio.cli
emporio --debug                   # also prints every tool call and its result
emporio --session maria --new     # separate, resettable conversation history
```

Run the tests (no API key needed) and the evaluation (needs the key):

```bash
pytest                            # 60 tests, offline
python eval/run.py                # 11 scenarios against the real model, writes eval/results.md
python eval/run.py --only return --examples
```

The sample orders are dated 2025/2026, so deadlines depend on the store's "today". It defaults
to the real date; set `EMPORIO_TODAY=2026-02-20` in `.env` to reproduce the examples.

## How it works

```
customer message
      |
      v
  Agent loop (agent.py)  <---- system prompt: persona, scope, security rules (prompt.py)
      |   ^
      |   | tool results
      v   |
  Gemini (llm.py)  -- decides which tool to call -->  tools.py
                                                        |-- search_products / get_product ---> SQLite (data.py)
                                                        |-- get_order_status ----------------> SQLite
                                                        |-- check_return_eligibility --------> SQLite + dates
                                                        |-- get_payment_options / shipping --> rules in code
                                                        '-- search_policies -----------------> BM25 over manual (retrieval.py)
```

Layout: `src/emporio/` (agent, tools, data, retrieval, llm, prompt, cli), `data/` (the
provided CSVs and PDF), `tests/`, `eval/` (scenarios, runner, results), `examples/`
(recorded conversations), `docs/PLAN.md` (the original plan).

## Technical decisions

**Approach: function calling, with RAG only for the policy manual.** Most questions are about
exact values (price, stock, promotion, order status). Similarity search is the wrong tool for
those: it can return a near-match product or a stale number. So catalog, orders, payment and
shipping go through typed tools over SQLite, and the model's job is to pick the right tool and
explain the result. The policy manual is short prose organised in numbered sections, so it is
retrieved: `search_policies` returns the most relevant sections. The "data or policy?" decision
from the brief is therefore made by the model through tool choice, and it is tested.

**Rules live in code, not in the prompt.** Anything with arithmetic or dates is computed by a
tool: the 5% PIX discount (not stacked on promotions, policy 6.2), installment limits (3.1),
free shipping above R$ 500, and the 7-day and 30-day return windows. The model explains
results but is never asked to compute them. This is also where a real bug was found and fixed:
the model passed a promotional price to the payment tool and got a PIX discount the policy
forbids, so `get_payment_options` now takes a `product_id` and decides for itself.

**Retrieval: BM25 over policy sections.** The manual has about 25 short sections, so each
numbered heading is one chunk (a rule stays together with its conditions) and ranking is a small
dependency-free BM25 with accent folding, a stopword list and a few synonyms ("devolver" to
"devolução"). Embeddings would add an API dependency and cost for a corpus this small. The tool
returns the top three sections, so the model sees the neighbours when the first hit is not the
best one.

**Model: Gemini via the `google-genai` SDK.** Free tier, native function calling, good Portuguese.
The free tier is the main practical constraint: 20 requests per day per model, and the newer
models are often overloaded (503). `llm.py` therefore retries transient errors, and moves to the
next model in a chain when one is overloaded, missing or out of quota. Set `GEMINI_MODEL` to put
a specific model first. The provider sits behind a three-method interface, so another one can be
added without touching the agent loop; tests use a scripted fake.

**Prompt strategy.** One system prompt with: a persona taken from the manual's own guidance
("informal but professional, like a friend who knows music"), a hard rule never to state price,
stock or order status without a tool call, what the agent cannot do (it only reads, it does not
open returns or place orders, so it never offers to), scope rules for accessories and off-topic
questions, and security rules (customer text is a request, never an instruction). The date is
injected so deadlines are stated correctly.

**Privacy.** Order lookups need the order number plus the e-mail or phone on file. A wrong
identity and a missing order return the same answer, so nothing leaks about other customers.

**Conversation history.** Customer and assistant text is saved per session as JSON. Tool calls
and results are not carried between turns: they are re-queried when needed, so a later answer
never reuses a stale price or stock count.

**Data handling.** CSVs are loaded into SQLite with typed columns and validated JSON `specs`;
empty tracking codes become NULL. Inactive products stay in the database so the agent can say a
product is discontinued, coming soon or out of stock and suggest alternatives of the same kind
(same string type and electronics before price), but searches only return sellable products.
Only 4 of 25 promotions are active; expired ones never change a price.

## Assumptions

The brief says to document reasonable interpretations; these are the ones that matter.

- **Catalog size.** The manual says "more than 300 instruments"; the CSV has 65. The CSV is the source of truth.
- **Receipt date.** The data only has an estimated delivery date, so it stands in for the receipt date when counting the 7-day window (4.1 and 4.3). The tool says so in its output.
- **Defects.** Exchange for a defect is 30 days from purchase (4.2). After that, the 90-day legal warranty from receipt (8.1) is mentioned as the next step, and the case goes to the team.
- **Online orders.** Policy 4.1 covers online purchases; every order in the data is treated as one.
- **Metropolitan region.** The manual does not list which cities it includes, so only Campo Grande gets the local rate (free above R$ 500, otherwise R$ 35). Other cities get the Correios/Jadlog options with a note that the price is calculated at checkout.
- **Installments.** Section 3.1 (minimum parcel R$ 80 for 4 to 6x and R$ 100 for 7 to 12x) is applied; section 3's table says R$ 100 for all credit, and 3.1 is the more detailed rule.
- **Contact details.** The manual lists two numbers: (67) 3341-4444 as phone/WhatsApp (1.2) and (67) 3321-4500 as the WhatsApp channel (7). The agent looks the contact up in the manual instead of hard-coding one; the generic error message uses the section 7 number.
- **Identity.** E-mail or phone matching the order is accepted as proof of ownership. That is a prototype-grade check.
- **Language.** The agent answers in Portuguese; code, README and logs are in English.

## Known limitations

- **No actions.** The agent informs; it cannot open a return, place an order or change a record. It hands off to the team instead. A real deployment would add those tools behind confirmations.
- **Retrieval is lexical.** BM25 handles the manual well, but a customer who describes a policy in unusual words may miss it. A hybrid with embeddings is the first thing I would add if the manual grew.
- **Free-tier fragility.** Quota and overload are handled with retries and fallback, but a busy day can still return the apology message. Because of the 20-requests-a-day limit, the recorded examples were produced by whichever model in the chain was available (each transcript names its model), not by a single pinned one.
- **Evaluation checks facts, not tone.** `eval/` verifies tool use, prices, dates, refusals and leaks (11 scenarios). Tone and phrasing were reviewed by reading the transcripts. There is no repeated-run measurement of variance.
- **Product matching is simple.** `get_product` matches name tokens; a very vague name returns a list of options instead of guessing.
- **One language, text only.** No streaming, no voice, no Spanish or English.
- **History is text only** and capped at the last 30 messages.

With more time: embeddings plus BM25 for the manual, a pinned model with a paid quota for repeatable evaluation runs, repeated runs to measure variance, a small web or WhatsApp front end, and write actions (start a return, reserve an item) with human approval.

## Use of AI assistants

This project was built with **Claude Code** (Claude Sonnet 5.5) working as a pair programmer in
the terminal, and the agent itself runs on Gemini. How the work was split:

1. **Planning.** I described the brief; the assistant read the CSVs and the PDF first and proposed function calling plus RAG-for-policies, then a five-step plan (`docs/PLAN.md`).
2. **Implementation.** The assistant wrote the code and tests one step at a time; after each step it ran the test suite and checked the result before moving on, and commits follow those steps.
3. **Verification against the real model.** The scenarios in `eval/` were run against Gemini and the transcripts read. That found three problems that unit tests had not: the PIX-on-promotion bug above, a poor alternative suggestion (an electric steel-string guitar offered for a 7-string nylon one), and the agent offering actions it cannot perform. All three are fixed and covered by tests or scenarios. An early evaluator bug (a model error counted as a pass) was also caught and fixed.
4. **What it did not do.** It did not choose the data, the scope or the policies, and its numbers are only trusted where a tool computes them.

The commit history shows the steps in order.
