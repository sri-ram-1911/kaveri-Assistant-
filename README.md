# Midstone 4: Reusable LLM Client

A small reusable client for OpenAI-compatible chat services. It supports streamed and
non-streamed completions, bounded 429 retries, persistent conversation messages, and
explicitly registered Python tools. The demonstration connects a `get_revenue` tool to
the Kaveri Exports SQLite sales database described in the Midstone business brief.

## Architecture

`src/llm_client.py` owns provider configuration, completion requests, streaming response
assembly, retry handling, JSONL logging, conversation history, and allow-listed tool
dispatch. `chat_demo.py` supplies the revenue query and runs three user turns with one
conversation ID (`c1`). Model-provided content is never evaluated as Python; only
functions supplied in the `functions` registry can run.

## Project structure

```text
src/
  __init__.py
  llm_client.py
tests/
  test_llm_client.py
chat_demo.py
llm_client.py       # compatibility imports for the original starter path
run_log.jsonl       # generated afresh by the demo
.env.example
.gitignore
requirements.txt
README.md
```

The repository also retains the supplied `business_brief.md` and `setup_free_llm.md`.
Keep your downloaded database and `.env` local; neither should be committed.

## Installation

Use Python 3.11 or newer:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Environment configuration

Copy `.env.example` to `.env`. Its defaults connect to a local Ollama service and require
no API secret. Do not put real provider keys in source control.

```dotenv
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:3b
DATABASE_URL=sqlite:///kaveri.db
LLM_TIMEOUT=300
```

The client connects to Ollama's OpenAI-compatible endpoint. Ensure Ollama is running and
the configured model is available (`ollama pull qwen2.5:3b`). To use another provider, set
its OpenAI-compatible base URL, API key, and model instead. `DATABASE_URL` defaults to a
`kaveri.db` file beside `chat_demo.py`.

### Build the Midstone 2 database

The repository consumes the actual Midstone 2 CSV pack. With the files in
`D:\Midstone 2\data\raw`, build the ignored local database with:

```powershell
python scripts/build_database.py
```

The loader follows `data_dictionary.md`, removes exact duplicate rows, trims whitespace,
normalizes ISO and `DD/MM/YYYY` dates, checks the 128 cleaned customer count, and creates
the five related tables with SQLAlchemy and foreign keys. It refuses to overwrite an
existing database. For a different input folder or output path, use `--csv-dir` and
`--database`.

## Run the demonstration

Place the Midstone 2 SQLite database at the configured path, configure `.env`, and run:

```powershell
python chat_demo.py
```

The demo asks exactly three questions in conversation `c1`; each final answer is streamed
to the terminal. Turn two calls `get_revenue(country, year)`. The tool runs one parameterized
SELECT joining `orders` to `customers`, filtering `customers.country` and the half-open
calendar-year range of `orders.order_date`, and summing `orders.total_amount`. Those table,
column, and revenue definitions come from the supplied Midstone business brief. Revenue is
formatted to two decimal places; a missing aggregate returns `0.00`. A missing or
incompatible database produces a clear database configuration error.

The demo truncates `run_log.jsonl` at startup and appends one JSON object per line. It logs
each user turn, each streamed final answer with measured latency and non-empty chunk count,
and tool request/result events with matching tool call IDs. Retry events are logged by the
client when a provider returns HTTP 429.

## Client behavior

### Streaming

`LLMClient.chat(..., stream=True, on_token=callback)` invokes the callback once for each
non-empty content delta as it arrives. It also joins those pieces into `Reply.content` and
counts them in `Reply.chunks`. Tool call IDs, names, and JSON argument fragments are
assembled by tool index before dispatch. Empty chunks are ignored safely.

### Rate limits

The official OpenAI SDK's internal retries are disabled so retry behavior is visible and
bounded. The client allows five total attempts by default and retries only
`openai.RateLimitError` (HTTP 429). It honors a numeric `Retry-After` header, otherwise it
waits 1, 2, 4, then 8 seconds. Each retry is written to the configured JSONL log and Python
logger. Other API errors pass through unchanged. The `sleep` and retry count are injectable
for deterministic unit tests.

### Conversation history

Create one `Conversation` per chat. `messages` returns its complete OpenAI-compatible
history. System, user, assistant, assistant tool-call, and tool-result messages are retained
across turns, including `tool_call_id` values.

### Tool calling

Supply tool declarations in OpenAI `tools` format and a Python function registry. The model
can request only a registered function; arguments are parsed with `json.loads`. Invalid JSON,
unknown tool names, and function exceptions become tool result messages for the model to
handle. The client never runs code generated by the model.

## Tests

Run the local mocked unit suite (no API key or network required):

```powershell
python -m pytest -v
```

Tests cover configuration validation, message history, streaming assembly and chunk counts,
retry timing and limits, `Retry-After`, error propagation, tool argument assembly, registered
tool execution, matching IDs, and invalid arguments.

## Example output

Exact wording and revenue depend on the configured model and your database:

```text
YOU: Hi, what can you do?
AI:  I can answer sales questions using our data and help with company information.
YOU: What was our revenue from Germany in 2024?
AI:  Germany's revenue in 2024 was $<database result>.
YOU: And how does that compare with what I asked first?
AI:  Your first question asked what I can help with; this question followed the revenue lookup.
```

The lines above illustrate the interaction only; they are not a claimed live run or sample
database output.

## GitHub submission

Commit the source, tests, documentation, and `.env.example`. Verify `.env` and local database
files are ignored, inspect the full diff and Git history for secrets, and include the generated
run log only if it contains no private data. Push the project branch and open a pull request
into `main`; merge after the repository's checks pass.
