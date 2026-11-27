# Business brief: Kaveri Exports wants an AI assistant

**From:** Anand Krishnan, Head of Sales and Digital, Kaveri Exports Pvt Ltd, Coimbatore
**To:** the AI engineering team (you)

> Team,
>
> We export spices, tea, coffee, textiles, coir and handicrafts to customers in 18 countries.
> Every week my sales heads ask the same three kinds of question, and every week someone
> loses half a day finding the answers:
>
> 1. **Numbers from the sales database.** "What was our revenue from Germany last year?"
>    "Which product sold best in 2024?" Today only two people can write SQL.
> 2. **Answers from our policies.** "How many days of sick leave do I get?" "How do I claim
>    my travel expenses?" The answers are in twelve PDFs and documents nobody reads.
> 3. **Research about the outside world.** "What are the main export markets for Indian
>    spices?" "What import rules does the EU have for spices?" Someone spends a day on Google.
>
> I want one assistant that does all three, gives answers we can check, and never makes
> anything up. It must also be safe: nobody may ever change or delete our data through it.
>
> Anand

## What you will build, in three parts

| Part | Capstone | Endpoint | What it does |
|---|---|---|---|
| **SQL assistant** | P3 | `POST /ask` | Turns a question into SQL, runs it **read-only** on the sales database, returns the answer and the SQL |
| **Document assistant (RAG)** | P4 | `POST /query` | Answers from the 12 policy documents, cites the documents it used, and **refuses** when the answer is not in them |
| **Research agent** | P5 | `POST /run` | Uses web search (SerpAPI), Wikipedia and your own MCP tools, and writes a short report with source links |

The eleven midstones build these parts one step at a time. Midstone 11 deploys all three
behind one URL, and the capstone grader tests that URL.

## Your data is your own

The LMS's **Download your data** button gives you files made from **your register number**.
Your numbers are different from your friends' numbers, so copied answers fail. Three packs:

| Pack | From midstone | What is in it |
|---|---|---|
| `midstone-02-data.zip` (the same files again on midstone 5, named for it) | 2 | `data/regions.csv`, `customers.csv`, `products.csv`, `orders.csv`, `order_items.csv` and `data_dictionary.md` |
| `midstone-06-data.zip` | 6 | `docs/`: 12 policy documents (8 PDF, 4 Markdown) |
| `midstone-09-data.zip` | 9 | `attack_questions.json` and `canary.txt` (your secret word) |

## The sales database

Five tables. `data_dictionary.md` in your pack describes every column.

```
regions(region_id, region_name, sales_head, target_2024)
customers(customer_id, company_name, country, city, region_id, segment, joined_on)
products(product_id, product_name, category, list_price)
orders(order_id, customer_id, order_date, status, sales_channel, total_amount)
order_items(order_item_id, order_id, product_id, quantity, unit_price, line_total)
```

### Definitions (use these exactly)

- **Revenue** = `SUM(orders.total_amount)`. Cancelled orders have `total_amount = 0.00`, so
  they never add to revenue. Money is in USD.
- **A year's revenue** uses `order_date` in that year (dates are `YYYY-MM-DD`).
- **Revenue of a product or category** = `SUM(order_items.line_total)` over orders that are
  **not** cancelled.
- **An order's country / region** is its customer's country / region.
- Round money and percentages to **2 decimals**.

### Cleaning rules (the raw CSVs are not clean)

1. **Drop exact duplicate rows.** Some rows appear twice in `orders.csv`, `order_items.csv`
   and `customers.csv`. Keep one copy.
2. **Trim spaces** around every text value (some countries are written `" Germany "`).
3. **Write every `order_date` as `YYYY-MM-DD`.** Some arrive as `DD/MM/YYYY`.

After cleaning there are exactly **128 customers**.

## The API contract (midstone 11 and the capstones test exactly this)

Every reply is JSON, under 64 KB.

**`POST /ask`**, body `{"question": "..."}`:

```json
{ "question": "How many customers are there?",
  "sql": "SELECT COUNT(*) FROM customers",
  "answer_value": 128,
  "answer": "Kaveri Exports has 128 customers." }
```
`answer_value` is the single value that answers the question: a number (rounded to 2
decimals for money) or a short text such as a country name. Never a sentence.

**`POST /query`**, body `{"question": "..."}`:

```json
{ "answer": "Employees get 20 working days of paid annual leave each year.",
  "citations": ["Leave_Policy.pdf"],
  "answer_days": 20,
  "refused": false }
```
`answer_days` is the number of days when the question asks for a number of days, otherwise
`null`. When the documents do not hold the answer: `"refused": true`, `"citations": []`,
`"answer_days": null`, and an answer that says the information is not in the documents.

**`POST /run`**, body `{"task": "...", "student_number": "..."}` (the student number is optional):

```json
{ "run_id": "9f2c...",
  "task": "Research vector databases and compare three approaches, citing sources.",
  "student_number": "TEST-0001",
  "report": "... every claim followed by its source link ...",
  "sources": ["https://...", "https://..."],
  "trace": [ {"step": 1, "tool": "serpapi_search", "input": "..."},
             {"step": 2, "tool": "wikipedia", "input": "..."},
             {"step": 3, "tool": "mcp:search_docs", "input": "..."} ] }
```
Echo `student_number` back exactly as it was sent.

**`GET /health`** reports each part:

```json
{ "status": "ok", "database": "ok", "schema_index": "ok", "embedding_model": "ok",
  "mcp": "ok", "history": "ok" }
```

## What "safe" means here

- The SQL assistant only ever runs **one `SELECT`**. `DELETE`, `DROP`, `UPDATE`, `INSERT`,
  `ATTACH`, `PRAGMA` and stacked queries (`...; ...`) are blocked before they reach the database.
- No API key or password is ever in your code or your Git history. Keys live in `.env`,
  which Git ignores.
- Instructions found inside documents or web pages are data, never commands.
- The system prompt is private: your canary word (midstone 9) must never come back out.
