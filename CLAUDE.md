# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Read first**:
> 1. [`arch.md`](arch.md) — the architectural blueprint (Chinese). The whole system answers to this doc.
> 2. [`Design.md`](Design.md) — UI design system tokens (Anthropic cream/coral/dark navy). Every CSS/HTML change must honor these.
> 3. [`memo/00-overview.md`](memo/00-overview.md) — what was built and the technology choices.
> 4. [`memo/02-skeletal-build-order.md`](memo/02-skeletal-build-order.md) — the layered build order (schemas → llm → validators → store → agents → orchestrator → web). New code lives in the layer that matches.

## Project at a glance

- **Multi-agent cognitive mechanism extraction**: resume → 7-stage pipeline → evidence-backed report.
- **Stack**: Python 3.11+, Pydantic v2, FastAPI + SSE, vanilla HTML/CSS/JS, **DeepSeek V4** via the Anthropic-compatible endpoint.
- **Two entry points**: CLI (`python -m lyrebird.main`) and web (`uvicorn lyrebird.web.app:app`).

## Common commands

```bash
# Install (one-time)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run all tests (offline; 129 passed, 1 skipped)
pytest

# Run one file / one test
pytest tests/test_schemas.py
pytest tests/test_llm_client.py::test_complete_json_bumps_max_tokens_on_truncation

# Real-API smoke test (burns ~15k DeepSeek tokens — opt-in)
LYREBIRD_E2E=1 pytest tests/test_pipeline_e2e.py

# CLI end-to-end
python -m lyrebird.main --resume resume.redacted.md --target-role "macOS 终端安全架构师" --turns 6

# Web server (dev)
uvicorn lyrebird.web.app:app --host 127.0.0.1 --port 8765 --reload

# Override model per role at runtime (no code change)
LYREBIRD_MODEL_HEAVY=deepseek-v4-flash uvicorn lyrebird.web.app:app
```

There is no linter or formatter wired in. There is no build step for the frontend (it is plain HTML/CSS/JS served from `src/lyrebird/web/static/`).

## Working mode (sediment from prior sessions)

This repo was built by a single AI agent over multiple sessions following the rules below. Future sessions should keep operating this way — the patterns are not optional, they are how the codebase stays coherent.

### 1. TDD, always

For every non-trivial change, write the failing test first, then the implementation. The repo's 129 tests are not coverage theater — each one locks a specific business rule. Examples:

- `test_mechanism_card_requires_evidence` locks the "≥2 distinct evidence_ids" naming gate.
- `test_apply_review_downgrades_validated_on_high_severity` locks the consistency gate.
- `test_sse_replay_honors_last_event_id_header` locks SSE reconnect dedupe.
- `test_project_locales_have_matching_keys` locks zh/en parity.
- `test_complete_json_bumps_max_tokens_on_truncation` locks the V4 thinking-block recovery.

When you change one of those behaviors, the test should fail loudly. When you introduce a new behavior, add the test that fails before the code that passes.

### 2. Memo-driven decisions

Every non-trivial decision lands in `memo/NN-topic.md`, sequentially numbered. The current series is `00-12`. Add `13-...` when you ship something that:
- Introduces a new architectural concept (e.g., observability event bus, i18n loader)
- Documents a tradeoff that future-you will forget (e.g., why flash vs pro, why three SSE defenses)
- Captures a bug whose root cause is non-obvious (e.g., V4 thinking-block max_tokens truncation)

Memos are **not** auto-generated summaries. They are written *as the work happens* and they record:
- The decision
- The alternatives considered
- The reason for choosing one
- Concrete examples / numbers / failure modes

Index updates: after writing `memo/NN-topic.md`, also link it from `README.md`'s "实现备忘" section. The numbered ordering is a feature — readers can pick up the timeline.

### 3. Verify with reality

Tests pass ≠ feature works. After any pipeline / Agent / UI change, run the real flow end-to-end:

- LLM-side change → kick off a real run via CLI or web, watch the resulting transcript in `runs/`.
- UI change → use the gstack `/browse` skill (`$B goto http://127.0.0.1:8765/ && $B screenshot ...`). Inspect the screenshot. Don't claim "looks good" without seeing it.
- Web API change → `curl -N -s http://127.0.0.1:8765/api/runs/.../events` and read the actual event stream.

Three real runs have produced ~stable artifacts at `runs/` — use them as oracles.

### 4. Track tasks, mark complete as you go

Use `TaskCreate` / `TaskUpdate` for any multi-step work. Mark tasks `in_progress` *before* starting and `completed` immediately when done — do not batch. This is the only externally-visible progress indicator the user has during long sessions.

## Architecture orientation (read order if you have 15 minutes)

1. **`src/lyrebird/schemas.py`** — the four core Pydantic contracts: `CandidateProfile`, `EvidenceCard`, `MechanismCard`, `ExtractionReport`. Plus 9 helper schemas. **Business rules are encoded as `model_validator`** (e.g., a `MechanismCard` rejects fewer than 2 distinct evidence_ids before it can be constructed). All boundaries — LLM input/output, ArtifactStore, REST — pass through these schemas.

2. **`src/lyrebird/llm/client.py`** — DeepSeek wrapper. The interesting method is `complete_json(role, system, user, schema)`. Key concerns it owns: model routing (Role enum → `deepseek-v4-pro` / `-flash`), markdown fence stripping, **V4 thinking-block truncation auto-bump** (see `_Truncated` class + `MAX_TOKENS_CAP=16000`), and retry with prompt-mutation.

3. **`src/lyrebird/agents/`** — 7 agents. Each is a 60-line file with `PERSONA` (Chinese), a factory `make_xxx_agent()`, and a `run_xxx()` callable. They all derive from `BaseAgent` (in `base.py`) which owns the EventBus instrumentation. Read `intake.py` first — it's the smallest.

4. **`src/lyrebird/agents/orchestrator.py`** — `Pipeline.run()` is the seven-stage state machine. It coordinates agents, runs deterministic gates (`sufficiency_gate`, `evidence_gate`, `naming_gate`, `consistency_gate`, `publish_gate`), persists artifacts, and emits events. The orchestrator **never calls an LLM** — it routes between agents and applies post-hoc rules.

5. **`src/lyrebird/observability.py`** — `EventBus` is a thread-safe pub/sub. `Event` carries `seq`, `run_id`, `timestamp`, `type`, `payload`. The bus is **optional**: `ctx.bus=None` makes all `bus.emit()` calls no-ops, which is how CLI / tests stay decoupled from the web stack.

6. **`src/lyrebird/web/`** — FastAPI app + `RunRegistry` (thread-pool around `Pipeline`) + static frontend. The SSE handler bridges the synchronous bus to async via `asyncio.to_thread(queue.get, ...)`. Three defenses against duplicate event delivery — see [memo/08](memo/08-sse-design-and-traps.md).

7. **`src/lyrebird/i18n/`** — locale registry with three-tier negotiation (query > cookie > `Accept-Language` > default) and three-tier fallback (locale → default → key). Locale files are JSON, flattened at load time. A CI test (`test_project_locales_have_matching_keys`) catches zh/en key drift.

## Project-specific conventions

These are not generic best practices — they are decisions baked into the codebase.

### `ctx.bus=None` backward-compat idiom

`AgentContext` carries an optional `EventBus`. **Every event emit must be guarded**:

```python
if self.ctx.bus is not None:
    self.ctx.bus.emit(EventType.STAGE_STARTED, stage=name)
```

The same idiom in `BaseAgent.run()`. Reason: the CLI path and 100+ unit tests never construct a bus — they would all need updating otherwise. New code follows the same pattern.

### Schema-first LLM IO

When adding an LLM call site, do **not** parse a free-form response. Instead:

1. Define the output as a Pydantic model in `schemas.py`.
2. Call `LLMClient.complete_json(role=..., system=..., user=..., schema=YourModel)`.
3. `complete_json` injects the JSON Schema into the system prompt, strips fences, validates against the Pydantic model, retries on failure, and auto-bumps `max_tokens` on truncation.

If the model returns garbage and you find yourself doing regex on its output, you have skipped the schema step. Go back.

### V4 thinking-block budget

DeepSeek V4 models (both `flash` and `pro`) emit a `ThinkingBlock` before the `TextBlock`, and **the thinking tokens count against `max_tokens`**. Flash thinking is typically 200–1500 tokens; Pro thinking can be 1000–3000.

Each agent in `src/lyrebird/agents/*.py` carries its own `max_tokens=` setting in the factory. These values are sized for thinking + output. If you add a new agent, **start at 3000 minimum** even for short outputs. The auto-bump in `complete_json` will recover from underestimates, but base configs should make the auto-bump rare. A warning like `truncated (hit max_tokens=1500 ... bumping 1500 → 2400)` firing on every turn means the base is too low — increase the agent's `max_tokens`.

### Model selection: role-based with env override

Two agents (`mechanism_modeler`, `report_composer`) declare `Role.HEAVY` → `deepseek-v4-pro`. The rest use `Role.STANDARD` → `deepseek-v4-flash`. See [memo/12-model-selection.md](memo/12-model-selection.md) for the full quantitative reasoning and the "should we run all-pro?" tradeoff.

Override per role without code changes:
```bash
LYREBIRD_MODEL_HEAVY=deepseek-v4-flash
LYREBIRD_MODEL_STANDARD=deepseek-v4-pro
```

### Confidence is a business rule, not a model probability

Each mechanism's `confidence` is computed by `Pipeline._estimate_components()` using 5 explicit weighted dimensions (`evidence_richness=0.30`, `cross_context_replication=0.25`, etc.), then **50/50 blended** with whatever number the LLM produced. The blend is intentional — we trust neither the model's self-rating nor pure heuristics alone. See `src/lyrebird/validators/confidence_scorer.py`.

### Static-asset versioning

`index.html` references `/static/styles.css?v=N` and `/static/app.js?v=N`. **Bump `N` when you edit either file.** FastAPI's `StaticFiles` sends long-cache headers, and browsers don't re-fetch linked subresources on simple reload. The `?v=` query is our cheapest cache-bust.

### i18n: do both sides, every time

UI strings live in `src/lyrebird/i18n/locales/{zh,en}.json`. Every visible string must:
1. Exist in **both** locales (CI fails otherwise — `test_project_locales_have_matching_keys`)
2. Be referenced via `data-i18n="key"` (HTML), `data-i18n-placeholder=`, `data-i18n-html=`, or `t("key", {vars})` (JS dynamic strings)
3. Use `{var}` placeholders for interpolation, not string concatenation

Default locale is `zh`. To add French: `cp zh.json fr.json`, translate values, change `meta.lang_native` + `meta.html_lang`. Server picks it up on restart — no code change. See [memo/11](memo/11-v4-and-i18n.md).

### SSE: three defenses against duplicate event delivery

When changing the SSE pipeline, preserve all three:
1. **Client closes the EventSource** on `run.completed`/`run.failed` (prevents auto-reconnect storm).
2. **Client dedupes by `seq`** (`if data.seq <= seenSeq) return`).
3. **Server reads `Last-Event-ID` header** in `stream_events()` (browsers auto-send it on reconnect).

Skip any one and you risk the "220 agent rows for 11 LLM calls" bug. See [memo/08](memo/08-sse-design-and-traps.md).

### Design tokens: the cream / coral / dark navy trinity

Do not introduce a fourth surface color. Coral (`#cc785c`) only on primary CTAs and full-bleed callouts. Slab-serif Cormorant Garamond (replacement for Anthropic's Copernicus) for display headlines with negative letter-spacing, always weight 500, never bold. Three banded surfaces (cream / cream-card / dark navy) must alternate — never two adjacent bands in the same surface tone. The lyrebird logo at `static/img/logo-{96,256}.png` is the only place the blue-purple gradient is allowed; treat it as an illustration, not a brand color. See [memo/09](memo/09-design-token-mapping.md).

### Run artifacts and transcripts

Every web/CLI run writes:
- `artifacts/<artifact_type>/<id>.json` and `.prov.json` (per-artifact + provenance)
- `runs/run_YYYYMMDD_HHMMSS_mmm_NNNN.json` (full transcript including all events and the report)

These are read-only after the run. Don't manually edit them. If you need to compare runs, write a small Python script that loads two transcripts and diffs the structured data, not the raw JSON.

## Where to put new things

| Adding... | Lives in... |
|---|---|
| A new Pydantic schema | `src/lyrebird/schemas.py` (add to `__all__` and write a test) |
| A new LLM call site | A new file in `src/lyrebird/agents/` derived from `BaseAgent` |
| A new pipeline stage | `Pipeline.run()` in `src/lyrebird/agents/orchestrator.py`, wrapped in `_enter_stage` / `_exit_stage` + a gate in the same file |
| A new event type | `EventType` enum in `src/lyrebird/observability.py` + JS handler in `web/static/app.js` |
| A new web endpoint | `src/lyrebird/web/app.py`, with a test in `tests/test_web_api.py` |
| Procedural prompt knowledge | A new `skills/<name>/SKILL.md` (markdown with YAML frontmatter); load via `SkillsLibrary` |
| A new UI string | All `src/lyrebird/i18n/locales/*.json` files (same key) + `data-i18n` attr or `t()` call |
| A new locale | One new JSON file in `locales/`; the parity test enforces key coverage |
| A new validator (deterministic) | `src/lyrebird/validators/<name>.py` — never as a free agent |
| A non-trivial decision | `memo/NN-topic.md` + link from `README.md` |

## Anti-patterns to refuse

- **Calling an LLM for what a regex can do.** PII detection, JSON schema validation, counting, and citation checking are deterministic — they live under `validators/`.
- **Letting the model self-rate.** Confidence numbers from the LLM are blended 50/50 with `ConfidenceComponents`; never used raw.
- **Using `display: flex` (or grid) on an element that needs to be hidden via `[hidden]`.** It silently overrides the default UA rule. Force with `[hidden] { display: none !important; }`.
- **Hardcoding model IDs in agent files.** Use the `Role` enum. Override via `LYREBIRD_MODEL_*` env, not by editing the agent.
- **Adding UI strings inline.** Even one-liner alert text goes through `t()` and into the locale JSONs.
- **Skipping `?v=N` bumps.** Browsers will serve stale CSS/JS and you'll spend an hour debugging "why didn't my change take effect".
- **Manually closing finished SSE streams server-side without `id:` field.** Browser reconnects without `Last-Event-ID` will re-replay everything.

## Honest limitations

- No CI is wired up. `pytest` is run manually.
- No linter / formatter is configured. Style is "match the surrounding code".
- The web stack is single-tenant, no auth. Anyone who reaches the port can burn API tokens. Add auth before deploying anywhere shared.
- Agent personas are Chinese; English UI is i18n'd but agent outputs follow input-resume language. Full agent-prompt i18n is V0.4 territory.
