# Setting up free AI services

Everything in these midstones runs on free services. You never need a credit card.

Your code reads three settings from `.env`, so you can switch provider without changing code:

```
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...
```

All the providers below speak the **OpenAI-compatible** API, so the `openai` Python package
talks to each of them. Only these three values change.

## Option 1: OpenRouter (recommended to start)

1. Sign up at <https://openrouter.ai> and open **Keys**, then **Create key**.
2. In `.env`:
   ```
   LLM_BASE_URL=https://openrouter.ai/api/v1
   LLM_API_KEY=sk-or-v1-...
   LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
   ```
3. Models whose name ends in `:free` cost nothing. Other good free choices:
   `qwen/qwen-2.5-72b-instruct:free` and `google/gemma-3-27b-it:free`. Check the list at
   <https://openrouter.ai/models?max_price=0>; free models change from time to time.

**Limits:** about **20 requests a minute and 50 a day** on free models. Going over gives
**HTTP 429**, which is why midstone 4 makes you retry with backoff. For the evaluation runs
in midstones 8 and 10 (more than 100 calls), use Ollama.

## Option 2: Ollama (runs on your own laptop, no limits)

1. Install it from <https://ollama.com/download>, or on Windows with
   `winget install Ollama.Ollama`.
2. Pull a model that can call tools: `ollama pull qwen2.5:7b` (about 5 GB; needs 8 GB RAM).
   On a smaller laptop use `qwen2.5:3b`.
3. In `.env`:
   ```
   LLM_BASE_URL=http://localhost:11434/v1
   LLM_API_KEY=ollama
   LLM_MODEL=qwen2.5:7b
   ```

It is slower on a laptop without a GPU (5 to 20 seconds an answer), but it has no daily limit.

## Option 3: Groq or Gemini (also free)

| Provider | `LLM_BASE_URL` | Key starts with | Example model |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | `gsk_` | `llama-3.3-70b-versatile` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `AIza` | `gemini-2.0-flash` |

## The other free services

| Service | What for | Where to get it | `.env` |
|---|---|---|---|
| HuggingFace embeddings | Turning text into vectors (midstone 6) | Nothing to sign up for: `sentence-transformers/all-MiniLM-L6-v2` downloads once and runs locally | none |
| SerpAPI | Google search for the agent (midstone 7) | <https://serpapi.com>, free plan with 100 searches a month | `SERPAPI_API_KEY=` |
| Langfuse | Tracing and evaluation (midstone 8) | <https://cloud.langfuse.com>, free Hobby plan | `LANGFUSE_PUBLIC_KEY=`, `LANGFUSE_SECRET_KEY=`, `LANGFUSE_HOST=` |
| Hugging Face Spaces | Deploying the app (midstone 11) | <https://huggingface.co/spaces>, free CPU Space | set as Space **secrets**, never in the repo |

## Keep keys out of Git

- Put every key in `.env`. Your `.gitignore` must list `.env` **before your first commit**.
- Commit `.env.example` instead: the same names with empty values.
- If a key ever reaches GitHub, even in an old commit, **revoke it** on the provider's site
  and make a new one. Deleting the file does not remove it from the history. The LMS scans
  the whole history.
