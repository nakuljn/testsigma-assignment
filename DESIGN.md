# Design Rationale — Agentic E-Commerce Operations Manager

## 1. Why LangGraph?

The central design challenge is coordination: five distinct agents need to share
context, and one of them (the Orchestrator) needs to see *all* prior decisions before
it acts. LangGraph's `StateGraph` with a shared `TypedDict` state is the cleanest
solution because:

- **State is first-class.** Every node receives and returns a partial state update.
  There is no implicit message passing or hidden side-effects — the graph is the
  single source of truth for what has happened.
- **Topology is explicit.** The parallel fan-out (InventoryAgent and
  CustomerInsightAgent running simultaneously) and the serial funnel into the
  Orchestrator are expressed as graph edges, not buried in application logic.
- **Testability.** Because state is typed and nodes are plain functions, each agent
  can be unit-tested in isolation by constructing a minimal `OpsState` and calling
  the node function directly — no graph execution needed.

### Alternatives considered

| Option | Why not chosen |
|---|---|
| **Plain LangChain chain** | Sequential by default; expressing parallelism and shared-state coordination requires hacking around the abstraction. |
| **Separate LLM calls with no framework** | Simplest, but loses structured state flow. Hard to express the "Orchestrator sees everything" requirement cleanly. |
| **CrewAI** | Role-based agent framework. Good for conversational multi-agent, but the strongly-typed state contract would be harder to enforce — CrewAI passes strings between agents by default. |
| **Google Agent Development Kit (ADK)** | See Section 4 below. |

---

## 2. The OpsState contract — the most important design decision

The entire system's integrity rests on `core/state.py`. Key choices:

**Pydantic decision models, not raw dicts.** Each agent produces typed objects
(`RestockDecision`, `PriceDecision`, `ProductIssue`, `CampaignDraft`). This means:
- Every decision *must* carry a `rationale` field (enforced by Pydantic, not docs).
- Invalid enum values (e.g., `urgency="extreme"`) fail fast at the point of creation,
  not silently downstream.
- The Orchestrator can iterate over typed lists with IDE autocomplete and type checking.

**Strict write ownership.** Agents append to their own decision list only.
`committed_changes` and `conflicts` are written exclusively by the Orchestrator.
This is not enforced by the Python type system (TypedDict is structural), but it is
enforced by the test suite (`test_state_contract.py`) and by code review convention.
In production you would enforce it with a `frozenset` of allowed-write keys per node,
which LangGraph supports.

**Separation of decisions from commits.** Agents produce *proposals*, not facts.
The Orchestrator is the single writer of committed state. This mirrors production
patterns where multiple microservices produce events and a single reconciliation
service decides what to persist. It also makes conflict detection tractable: the
Orchestrator can compare all proposals before committing any of them.

---

## 3. Deterministic logic + LLM reasoning — a deliberate split

Every agent follows the same pattern:

```
deterministic core → identifies WHAT needs attention
         ↓
LLM → decides HOW to reason about it and writes the rationale
```

For example:
- **InventoryAgent**: `days_of_cover = stock / avg_daily_sales` is arithmetic.
  The LLM's job is to classify urgency given the velocity trend and write a
  human-readable rationale.
- **PricingAgent**: the price floor (`cost × 1.20`) is enforced in code, not by the
  LLM. The LLM synthesises competitor data into a defensible price *within* that floor.
- **MarketingAgent**: the suppression rule (never promote a high-severity SKU) is a
  hard `if` statement, not a prompt instruction. The LLM only writes copy for
  non-suppressed SKUs.
- **Orchestrator**: conflict detection is a deterministic pass over typed lists.
  The LLM writes only the narrative sentence in the conflict ledger.

**Why this matters:** LLMs are non-deterministic. If the *trigger* logic (what to act
on) lives in the LLM, tests become assertions about text generation, which is fragile
and non-reproducible. By keeping triggers deterministic, every agent is fully
unit-testable without any API calls.

---

## 4. Why not Google Agent Development Kit (ADK)?

Google ADK is a capable framework designed around Google Cloud's agent infrastructure.
The reasons it was set aside for this submission:

| Factor | Decision |
|---|---|
| **Provider lock-in** | ADK is tightly coupled to Google Cloud and Gemini models. This submission requires demonstrable provider-agnosticism (OpenAI ↔ Anthropic swap). |
| **State model** | ADK uses a session-and-event model optimised for conversational agents. The ops use-case needs a strongly-typed shared state object — which maps more naturally to LangGraph's `TypedDict`. |
| **Testability** | ADK agents are harder to unit-test in isolation because they carry implicit session context. LangGraph nodes are plain functions over a dict. |
| **Breadth vs depth** | For a graded submission, showing one framework deeply (LangGraph + LangChain tools) is more defensible than showing two frameworks shallowly. |

ADK would be the right choice if: the deployment target is Google Cloud Run, the agents
need persistent cross-session memory, or the primary model is Gemini.

---

## 5. What is mocked and why

| Component | Real or mocked | Rationale |
|---|---|---|
| LLM calls | **Real** (requires API key) | The reasoning quality is the point of the submission. |
| Web search | **Real** (DuckDuckGo, no key needed; Tavily optional) | Competitor prices have a real external source. |
| Store inventory / catalog / sales | **Mocked** (seed JSON) | There is no public e-commerce store to query. Seed data is crafted to exercise all code paths including all 3 conflict classes. |
| Report file I/O | **Real** | Reports land in `reports/` on every run. |

---

## 6. Conflict resolution design (why fixed precedence, not LLM arbitration)

Three approaches were considered for the Orchestrator's resolution step:

1. **LLM arbitration**: send all conflicting decisions to an LLM and let it decide.
   *Problem*: non-deterministic, non-explainable, non-testable. Every run could produce
   a different winner for the same conflict.

2. **Multi-round negotiation**: agents renegotiate until convergence.
   *Problem*: over-engineered for this use case. Adds latency, complexity, and
   potential infinite loops.

3. **Fixed precedence rules** (chosen): a small, written-down policy table with three
   rules. The LLM only writes the narrative explanation after the winner is chosen
   deterministically.

This choice prioritises explainability and testability. The conflict ledger in the
daily report is only credible if a reviewer can independently verify why each conflict
was resolved the way it was — which requires the resolution logic to be deterministic
and documented.

---

## 7. Graceful degradation

The `web_search` function in `core/tools.py` implements a three-tier fallback:

```
Tavily (optional, premium) → DuckDuckGo (free, no key) → empty list (never raises)
```

`PricingAgent` catches `web_search` returning an empty list and falls back to
demand-only pricing, marking the rationale accordingly. The graph never fails due
to a flaky network call. This is tested explicitly in `test_graph_endtoend.py::test_no_crash_with_network_failure`.

---

## 8. Decision log

| Decision | Rationale | Alternatives considered |
|---|---|---|
| LangGraph + LangChain tools | Coherence over framework breadth on a graded submission | Plain LangChain; Google ADK; CrewAI |
| Provider abstraction via env var | Demo talking point; zero code change to switch models | Hard-code one provider |
| Fixed conflict precedence | Deterministic, testable, explainable | LLM arbitration; multi-round negotiation |
| DuckDuckGo as default search | No API key required for basic demo | Tavily (better results but needs key) |
| Seed data with 15 SKUs | Enough variety to trigger all 3 conflict classes reliably | Smaller / larger catalog |
| Streamlit dashboard | Visual payoff; minimal code; integrates with Python natively | FastAPI + React (over-engineered for a demo) |
