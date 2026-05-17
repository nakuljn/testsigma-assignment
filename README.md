# Agentic E-Commerce Operations Manager

A LangGraph-orchestrated multi-agent system that runs a nightly operations cycle for
an e-commerce store: restocking, pricing, customer insight surfacing, and marketing
campaigns — all coordinated through a shared typed state and a conflict-resolving
Orchestrator.

## Quick start

```bash
# 1. Clone and set up
git clone <repo-url> && cd agentic-ecom-ops
make setup

# 2. Add your API key
cp .env.example .env
# Edit .env and set OPENAI_API_KEY (or ANTHROPIC_API_KEY + MODEL_PROVIDER=anthropic)

# 3. Run the daily cycle (6-SKU demo seed; fast: ~20–60 sec)
make demo FAST=1

# 4. Launch the Streamlit interviewer dashboard
make dashboard
```

## Interviewer demo (Streamlit UI)

```bash
make dashboard
# → http://localhost:8501
```

Three pages:

| Page | What to show |
|------|----------------|
| **Run** | Pick **Demo (6 SKUs)** or **Full (15 SKUs)**. Live agent cards + logs. **Fast mode** = batched LLM, no web search. Uncheck Fast for live DuckDuckGo competitor search (max 3 SKUs). |
| **Store data** | Edit seed JSON — saves to `data/seed/`. Demo seed: SKU-001 low stock + quality issues, SKU-003 critical restock, SKU-006 declining sales. |
| **Results** | KPIs, conflict ledger, per-agent tabs, downloadable Markdown report in `output/`. |

Suggested 2-minute walkthrough:

1. **Store data** — show SKU-001 low stock / defect reviews (marketing suppression).
2. **Run** — Demo dataset, Fast mode on → run; then uncheck Fast and re-run to show live web search.
3. **Results** — open Conflict ledger, then Full Report tab.

### Seed data profiles

| Profile | Location | SKUs |
|---------|----------|------|
| **Demo** (default) | `data/seed/` + `data/seed/demo/` | 6 — tuned for conflicts, fast LLM runs |
| **Full** | `data/seed/full/` | 15 — original assignment catalog |

Switch in the dashboard **Run** page, or CLI: `python run.py --full-seed`.

### CLI (no UI)

```bash
make demo FAST=1              # 6 SKUs, batched LLM, no web search
python run.py --fast --print-report
python run.py --print-report  # live APIs: web search + per-SKU LLM (~1–3 min on demo)
python run.py --full-seed --fast   # 15-SKU catalog (slower)
```

## Architecture

```
                      ┌─────────────────────────┐
                      │  Seed / Load OpsState   │
                      │  catalog · inventory    │
                      │  sales_history · reviews│
                      └────────────┬────────────┘
                                   │ (parallel)
             ┌─────────────────────┴─────────────────────┐
             ▼                                             ▼
   ┌──────────────────┐                       ┌──────────────────────┐
   │  InventoryAgent  │                       │ CustomerInsightAgent │
   │  days-of-cover   │                       │ return-rate + reviews│
   │  → RestockDec[]  │                       │ → ProductIssue[]     │
   └────────┬─────────┘                       └──────────┬───────────┘
            └──────────────────┬──────────────────────────┘
                               ▼
                    ┌──────────────────┐
                    │  PricingAgent    │
                    │  web_search +    │
                    │  demand signal   │
                    │  → PriceDec[]    │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  MarketingAgent  │
                    │  low-sellers +   │
                    │  overstock       │
                    │  → CampaignDraft[]│
                    └────────┬─────────┘
                             ▼
          ┌──────────────────────────────────────┐
          │             Orchestrator             │
          │  1. Detect conflicts (deterministic) │
          │  2. Resolve via fixed precedence     │
          │  3. Commit to MockStore              │
          │  4. Emit daily ops report            │
          └──────────────────────────────────────┘
```

## The design in one paragraph

One shared, typed `OpsState` object flows through a LangGraph state graph. Each agent
**reads** the parts of state it needs, **produces typed decision objects** (never mutating
committed state directly), and the **Orchestrator** is the sole writer that reconciles
conflicting decisions and commits the final state. The single most important design
artefact is the `OpsState` schema and decision contract in `src/ecom_ops/core/state.py` — it is what
makes this an *agentic system* rather than five disconnected LLM calls.

## Conflict resolution (scope-fixed)

| Conflict | Winner | Rule |
|---|---|---|
| `promote_vs_broken` | Suppress campaign | Customer safety beats revenue |
| `price_up_vs_discount` | Pricing wins | Demand truth beats stale plans |
| `restock_vs_clearance` | Clearance wins | Don't restock what you're winding down |

The **winning action** is chosen deterministically. The LLM writes only the
human-readable narrative in the conflict ledger.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MODEL_PROVIDER` | `openai` | `openai` or `anthropic` |
| `OPENAI_API_KEY` | — | Required if provider is openai |
| `ANTHROPIC_API_KEY` | — | Required if provider is anthropic |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `ANTHROPIC_MODEL` | `claude-3-5-haiku-20241022` | Anthropic model name |
| `SEARCH_PROVIDER` | `duckduckgo` | `tavily` or `duckduckgo` |
| `TAVILY_API_KEY` | — | Required only if `SEARCH_PROVIDER=tavily` |
| `MIN_MARGIN_PCT` | `0.20` | Price floor = cost × (1 + this) |
| `DAYS_COVER_CRITICAL` | `3` | Flag SKUs with cover below this |
| `DAYS_COVER_LOW` | `7` | Flag SKUs with cover below this |
| `SKIP_WEB_SEARCH` | `0` | Set `1` or use `--fast` to skip competitor search |
| `BATCH_LLM` | `0` | Set `1` with fast mode: one LLM call per agent (~5 total) |

## Repository layout

```
testsigma-assignment/
├── src/ecom_ops/             # installable package
│   ├── agents/               # inventory, insight, pricing, marketing, orchestrator
│   ├── core/                 # state, llm, tools, run_observer, batch_llm
│   ├── graph/ops_graph.py    # LangGraph wiring
│   ├── data/                 # MockStore + seed_io
│   └── dashboard/            # Streamlit multipage app
├── data/seed/                # active seed (demo 6 SKUs by default)
│   ├── demo/                 # canonical demo profile
│   └── full/                 # 15-SKU full profile
├── output/                   # Generated daily_ops_YYYY-MM-DD.md
├── tests/
├── run.py                    # CLI entrypoint
└── Makefile
```

## Running tests (no API key needed)

All tests mock LLM responses and run offline:

```bash
make test
# or
.venv/bin/python -m pytest tests/ -v
```

## Switching providers

```bash
# OpenAI (default)
MODEL_PROVIDER=openai OPENAI_API_KEY=sk-... python run.py

# Anthropic
MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... python run.py

# Via CLI flag
python run.py --provider anthropic
```

## Graceful degradation

If the web search (competitor price lookup) fails at runtime, `PricingAgent`
falls back to demand-only pricing and notes this explicitly in the `rationale` field.
The pipeline never breaks on a flaky network call — verified in `tests/test_graph_endtoend.py`.
