# STYLE_GUIDE.md — Kodi Integration for UC Remote 3 (Patched Fork)

> **Scope:** This guide governs all AI-assisted development on the Kodi integration fork (`mmadalone/integration-kodi`, branched from `albaintor/integration-kodi`). It covers coding conventions, async/ucapi/Kodi domain patterns, operational workflow, anti-patterns, quality gates, and session discipline. Adapted from the UC-Remote-UI `STYLE_GUIDE.md` (Qt 5.15 / QML / C++17 firmware fork) — same author, same operational framework, retargeted for Python 3.11 / asyncio / `ucapi` 0.6.0 / Kodi JSON-RPC.
>
> **Reference docs:**
> - **Python:** [PEP 8 Style](https://peps.python.org/pep-0008/) · [PEP 257 Docstrings](https://peps.python.org/pep-0257/) · [PEP 484 Type Hints](https://peps.python.org/pep-0484/) · [PEP 526 Variable Annotations](https://peps.python.org/pep-0526/) · [PEP 654 Exception Groups](https://peps.python.org/pep-0654/)
> - **asyncio:** [asyncio Synchronization Primitives](https://docs.python.org/3/library/asyncio-sync.html) · [asyncio Tasks](https://docs.python.org/3/library/asyncio-task.html) · [asyncio cancellation](https://docs.python.org/3/library/asyncio-task.html#task-cancellation)
> - **aiohttp:** [ClientSession docs](https://docs.aiohttp.org/en/stable/client_reference.html#client-session) · [ClientTimeout](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout)
> - **ucapi:** [unfoldedcircle/integration-python-library](https://github.com/unfoldedcircle/integration-python-library) · [unfoldedcircle/core-api WebSocket Integration API](https://unfoldedcircle.github.io/core-api/integration/) · [Entities API](https://unfoldedcircle.github.io/core-api/entities/)
> - **Kodi:** [Kodi JSON-RPC API](https://kodi.wiki/view/JSON-RPC_API) · [JSON-RPC v13](https://kodi.wiki/view/JSON-RPC_API/v13) · [xbmc/xbmc issues](https://github.com/xbmc/xbmc/issues)
> - **Upstream fork base:** [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (track for upstream merges)
>
> **Verification status (2026-05-02):**
>
> | Layer | Source | Confidence |
> |---|---|---|
> | PEP 8 / 257 / 484 / 526 / 654 conventions | Official Python docs | ✅ High |
> | asyncio synchronization primitives + task semantics | Official Python docs | ✅ High |
> | aiohttp ClientSession lifecycle | Official aiohttp docs | ✅ High |
> | ucapi entity registration / event surface | `core-api` AsyncAPI spec + `integration-python-library` README | ✅ High |
> | upstream MPL-2.0 file-header convention | Read from existing `src/*.py` (`config.py:1-6`, `driver.py:2-7`) | ✅ High |
> | Kodi JSON-RPC `Player.GetItem` shape variation | xbmc/xbmc#19151, #16245, forum #371822 | ✅ High |
> | Patch-derived rules (patches 1-44) | `KODI-INTEGRATION-PATCHES.md` — empirical, fork-specific | ⚠️ Source-derived |
> | UC3 device REST surface (PIN auth, entity store) | UC3 device + dev REST API | ⚠️ Empirical |
> | PyInstaller bundling gotchas (`pip install` ordering) | Empirical, see `feedback_*.md` memory entries | ⚠️ Empirical |
> | Upstream merge cadence (`v1.18.7` → `v1.18.13` → `v1.20.0`) | Project history, `KODI-INTEGRATION-PATCHES.md` rebase/merge sections | ⚠️ Project-specific |
>
> **What this means for Claude Code:** Items marked ✅ can be trusted as-is. Items marked ⚠️ are derived from reading existing source code, project history, or empirical device testing — they are the best available truth, but re-verify after upstream merges by reading the updated source. There is no single "Kodi-integration on UC3" reference doc; this guide IS that doc.

---

## §1 CORE PHILOSOPHY

### §1.1 Modular over monolithic
- Prefer small, composable modules over large all-in-one files.
- If a Python class exceeds ~500 lines of implementation, consider extracting collaborators (e.g., the artwork pipeline in `kodi_device.py:_update_states` is a candidate for extraction — see AP-K5).
- If a Python module exceeds ~1500 lines, decompose. `kodi_device.py` is at ~1800 today — at the upper threshold.
- When building something new, **always ask the user** whether complexity warrants multiple modules, a single class with extracted helpers, or a flat file. Never decide silently.

### §1.2 Separation of concerns
The fork has four concentric layers — keep them distinct:
1. **`pykodi/kodi.py`** — low-level Kodi JSON-RPC wrapper. Vendored. Don't refactor.
2. **`kodi_device.py`** — domain logic: state machine, WebSocket events, command dispatch, polling.
3. **`media_player.py` / `remote.py` / `sensor.py` / `selector.py`** — ucapi entity wrappers. Thin.
4. **`driver.py`** — entry point: entity registration, event wiring, configured-device lifecycle.

Don't smear concerns. Don't add `media_player`-aware logic to `kodi_device`. Don't have `driver.py` reach into Kodi JSON-RPC directly.

### §1.3 Never remove features without asking
If a refactor would change observable behavior — entity capability set, attribute semantics, command response codes, persisted config field meaning — **stop and ask first**. Patch 27's lesson: stripping `Features.VOLUME` to hide an OSD broke Kodi volume control entirely. See AP-K1.

### §1.4 Follow upstream patterns and official docs
Before inventing, study:
1. **Upstream.** `albaintor/integration-kodi` `src/` — read the existing pattern for the area you're touching. Follow upstream conventions even when you disagree, unless you have a documented reason in `KODI-INTEGRATION-PATCHES.md`.
2. **ucapi-python examples.** `https://github.com/unfoldedcircle/integration-python-library/tree/main/examples` — canonical entity-registration and event-emission shapes.
3. **Python stdlib.** asyncio, dataclasses, logging, typing — read the docs, don't invent.

### §1.5 Uncertainty signals — stop and ask, don't guess (MANDATORY)
If you're uncertain about:
- The ucapi entity contract (which attribute to emit, when, with what value)
- Kodi's `Player.GetItem` shape for a content type you haven't probed
- Whether a Python pattern is upstream-style or fork-style
- Whether a behavior is firmware-side or integration-side (AP-K3)

→ **Stop. Ask. Don't ship a guess as an authoritative recommendation.** Specifically: do NOT label sources you haven't verified as "documented" or "canonical." If you didn't read the doc, say so. The user is non-dev for some Python/Qt internals; calibrated uncertainty signals matter more than confident-sounding wrongness.

### §1.6 Complexity budget — quantified limits
- **Per function:** ~80 lines max body. `_update_states` is ~250 lines and shows the cost (see AP-K2, AP-K5).
- **Per class:** ~500 lines.
- **Per module:** ~1500 lines.
- **Mutable instance fields participating in gating logic:** **3+ is the threshold** to trigger AP-K2. Refactor to explicit state machine, transition queue, or eliminate shared state.
- **Patches on one subsystem in one release window:** **3+ is the Divergent Change threshold** (Fowler) — see AP-K5.

### §1.7 Reasoning-first directive (MANDATORY)
Before generating code:
1. State what you're going to do, in plain English.
2. Name the patches/sections that are relevant context.
3. Name the AP-K* row that applies (or explicitly state "no AP-K* applies, because…" — see CLAUDE.md § Fork Design Discipline trigger).
4. **Then** generate the code.

Code-first responses mask flawed reasoning. The reasoning is the artifact; the code is the consequence.

### §1.8 Research-first mandate (MANDATORY)
For any non-trivial change, consult docs/forums BEFORE proposing:
- **ucapi:** `unfoldedcircle/core-api` AsyncAPI spec, `unfoldedcircle/integration-python-library` README + examples, UC community forum
- **Kodi:** Kodi wiki JSON-RPC pages, Kodi forum, `xbmc/xbmc` GitHub issues
- **Python/asyncio:** `docs.python.org/3/library/asyncio-*.html`, relevant PEPs
- **Aiohttp:** `docs.aiohttp.org` (ClientSession lifecycle, cancellation, ClientTimeout)
- **Upstream fork base:** `albaintor/integration-kodi` issues + PRs (open + closed) for prior art
- **Codebase check:** `git grep` / `Grep` for the symbol you'd add — likely it exists already.

No hacky workarounds. If a workaround is unavoidable (e.g., upstream-firmware bug not yet fixed), flag it with `# Workaround for X — remove after vY.Z` and document in `KODI-INTEGRATION-PATCHES.md`. Patch 41 is the warning example — shipped a workaround for what was actually a UC-Remote-UI v1.4.10 bug.

### §1.9 Violation report severity taxonomy
When auditing or reporting issues, tag severity:
- **❌ ERROR** — code is broken or violates a load-bearing invariant. Block merge.
- **⚠️ WARNING** — code works but violates a convention or has known fragility. Should fix.
- **ℹ️ INFO** — convention nudge or refactor suggestion. Lowest priority.

Severity drives review urgency. Don't downgrade an ERROR to WARNING to make a report less alarming.

### §1.10 Directive precedence — when MANDATORYs conflict
If two MANDATORY rules conflict:
1. User-explicit direction wins (current conversation > prior memory).
2. Safety-critical wins over convention (e.g., security patch > formatting).
3. Documented protocol contract wins over local convention (e.g., ucapi entity_change semantics > local field-naming style).
4. CLAUDE.md Mandatory Rules > STYLE_GUIDE.md anti-patterns (operational floor first, then design pattern).
5. When in doubt: ask.

### §1.11 Minimum-disruption upstream-mergeability principle
This is a fork. Every mod increases merge cost. To minimize:
- **Custom additions at END of lists/blocks** (config dataclass fields, simple-command dicts, feature lists, `KODI_BROWSING` entries). Insertions in the middle collide with upstream insertions.
- **Don't reformat upstream code.** No `ruff format`-applied unrelated lines, no import re-sorting outside the file you're patching.
- **Don't rename upstream symbols.** Even when names violate PEP 8 (e.g., `KodiConfigDevice` docstring still says "Sony device configuration" — leave it; that's upstream's bug to fix).
- **Don't insert custom logic mid-upstream-function.** Add a helper, call from end of upstream function. Keeps the diff additive.
- **Document divergences in `KODI-INTEGRATION-PATCHES.md`.** Every patch entry includes a "Reference" section pointing to the upstream line/method touched.

See AP-K1 for the inverse failure mode (stripping upstream-advertised entity features).

---

## §2 OPERATIONAL MODES

At the start of every task, identify the mode:

### §2.1 BUILD mode
**Trigger:** User asks to create, implement, modify, or extend functionality (a new patch, a new feature, a refactor).

**Workflow:**
1. Identify mode → load relevant style guide sections + KODI-INTEGRATION-PATCHES.md scan-table preamble
2. Run AP-K trigger (CLAUDE.md § Fork Design Discipline)
3. Run git pre-flight (§3.3)
4. Reasoning-first (§1.7) — explain approach before code
5. Generate code in chunks (§4.5) if >150 lines
6. Anti-pattern scan (§5) before presenting
7. Post-task state checkpoint (§4.3)

### §2.2 TROUBLESHOOT mode
**Trigger:** User reports a bug, crash, regression, rendering artifact, or unexpected behavior.

**Workflow:**
1. Identify the symptom — ask for specifics if vague
2. **Apply AP-K3 first if rendering issue:** verify wire output (`ws://uc3:80/ws`) and UC core entity store (`GET /api/entities/<id>`) BEFORE reading integration code
3. Read relevant source files to understand current implementation
4. Form a hypothesis and explain it
5. If the fix requires editing files → **auto-escalate to BUILD mode** (run git pre-flight first)
6. If the fix is configuration or conceptual → explain without editing

### §2.3 AUDIT mode
**Trigger:** User asks to review, audit, check, validate, or grade existing code.

**Workflow:**
1. Read the files under audit (skip `pykodi/` — vendored)
2. Cross-reference against this style guide, CLAUDE.md AP-K1..K5, KODI-INTEGRATION-PATCHES.md, Python/asyncio/ucapi best practices
3. Produce a violations report (§1.9 severity format) with file:line citations
4. **Be brutally honest.** No glazing. The user explicitly invokes "audit" expecting a pro-grade pass.
5. If fixes are requested → **escalate to BUILD mode**

### §2.4 Auto-escalation
If a TROUBLESHOOT or AUDIT session requires editing files, escalate to BUILD mode BEFORE the first edit: run git pre-flight (§3.3), announce the mode switch, and follow BUILD workflow from that point.

---

## §3 GIT DISCIPLINE

### §3.1 Remotes & branches

| Remote | URL | Purpose |
|---|---|---|
| `origin` | `mmadalone/integration-kodi` | Our private fork — push here |
| `upstream` | `albaintor/integration-kodi` | Fork base — pull updates, send PRs |

**Active branches** (as of 2026-05-02):
- `v1.20.0-patched` — current dev branch (44 patches on upstream `v1.20.0`)
- `v1.18.13-patched` — prior base (retained as safety net)
- `v1.18.7-patched` — pre-rebase base (retained as safety net)
- `backup/pre-v1.20.0-merge` — rollback target for the v1.20.0 merge

Backup branches stay until a release confidence window closes. Don't delete prior `*-patched` branches without user confirmation.

### §3.2 Commit message convention
```
[<type>] <scope>: <description>

Types: fix, feat, docs, refactor, test, build, chore, audit, patch, hotfix
Scope: filename, patch number, or short feature name

Examples:
[patch 44b] config: flip artwork_type_channels default thumbnail → icon
[fix] kodi_device: clear artwork in no-players branch (AP-K2 cleanup)
[docs] CLAUDE.md: add Fork Design Discipline section
[refactor] artwork pipeline: extract _update_states block into its own module
[chore] requirements.txt: bump aiohttp ~=3.13.5 (upstream merge)
[audit] post-merge doc audit pass (v1.20.0)
```

The recent `git log` style is `vX.Y.Z-madalone.N: description` for release-tagged commits and `[type] description` for everything else. Match the convention you see.

### §3.3 Pre-flight checklist (MANDATORY — before first edit in any BUILD session)

**Stop. Before you edit any project file:**

1. ✅ Check `git status` — resolve any uncommitted changes from a previous session.
2. ✅ Commit or stash anything dirty with a descriptive message.
3. ✅ Confirm you're on the right branch (`v1.20.0-patched` for new work; never `main` — there is no `main` in our fork).
4. ✅ **If the task touches the artwork pipeline or `Features.*`:** confirm AP-K1/K2/K3 trigger (CLAUDE.md § Fork Design Discipline) — name the AP that applies or explicitly negate.
5. ✅ Only NOW may you edit files.

If you realize mid-edit that you forgot: don't panic — `git diff` shows what changed. Skipping deliberately is a violation.

### §3.4 Atomic multi-file edits
Many patches require coordinated changes across `config.py`, `setup_fields.py`, `setup_flow.py`, `kodi_device.py` (the documented 5-touch-point config pattern — see CLAUDE.md Mandatory Rule 3):

1. **Single commit covers all files** for one patch.
2. **Edit in dependency order.** `const.py` before `kodi_device.py`. `config.py` before `setup_fields.py`. Headers before consumers.
3. **If any edit fails mid-batch:** stop, report, decide with user whether to revert or fix.

### §3.5 Upstream rebase/merge strategy

```bash
git fetch upstream
git merge upstream/main      # OR git rebase upstream/main
```

For >5 fork patches, **prefer `merge`** — rebasing forces per-commit conflict resolution. The v1.20.0 merge (44 patches) chose merge for this reason; the v1.18.13 rebase (20 patches at the time) chose rebase. Decide per-merge: if upstream restructured a file your patches touch (e.g., `media_browser.py` rewrite during v1.20.0), merge is safer.

**Custom additions at END of lists** in `config.py` (`KodiConfigDevice` fields), `const.py` (`KODI_*` dicts, simple commands), and `setup_fields.py` (`SETUP_FIELDS` list) to minimize conflicts. Never reformat upstream files. Never rename upstream symbols.

**Post-merge doc audit (MANDATORY).** Conflict resolution focuses on code; documentation goes stale silently. After every successful upstream rebase or merge, audit ALL of: `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `STYLE_GUIDE.md`, `CONTRIBUTING.md`, `KODI-INTEGRATION-PATCHES.md`, and any `PHASE*` / `*-PLAN.md` analysis docs for stale version refs, branch names, patch counts, and upstream-tag references. Fix in a single follow-up commit before tagging the new release.

---

## §4 BUILD WORKFLOW

### §4.1 Session start
1. Identify operational mode (§2)
2. Read relevant patch sections in `KODI-INTEGRATION-PATCHES.md` (use `Grep`; don't read wholesale — see CLAUDE.md Mandatory Rule 1)
3. Load relevant style guide sections (don't load everything for a one-line fix)
4. Run git pre-flight (§3.3)

### §4.2 Build logs (optional but recommended for >100-line changes)
For non-trivial builds (new patch with multi-file impact, refactor, new config field), create a build log:

**File:** `_build_logs/YYYY-MM-DD_<task>.md` (gitignored — these are working notes)

```markdown
# Build Log: <task description>
**Date:** YYYY-MM-DD | **Mode:** BUILD | **Patch #:** <if applicable>

## Plan
<reasoning-first output from §1.7>

## AP-K trigger
<which AP-K applies, or explicit "none applies, because…">

## Edit Log
| # | File | Change | Status |
|---|------|--------|--------|
| 1 | src/config.py | Add field foo | ✅ |
| 2 | src/setup_fields.py | Add UI field | 🔧 |

## Decisions Made
<trade-offs, approaches chosen>

## Outstanding
<deferred items, open questions>
```

Update the edit log between consecutive edits — not batched at the end. Crash recovery depends on this.

### §4.3 Post-task checkpoint
After completing a deliverable: summarize decisions, current state, and outstanding items. If the task introduced or modified a patch, update `KODI-INTEGRATION-PATCHES.md` with the patch entry (see §9 Patch Anatomy template) BEFORE committing the code change — keep the doc + code change atomic.

### §4.4 Crash recovery
1. `git status` + `git diff` to see uncommitted changes.
2. Check `_build_logs/` for in-progress logs.
3. Decide with user: commit `[wip]`, revert, or continue.
4. **Prior tarball at project root** (`uc-intg-kodi-v<prev>-<arch>.tar.gz`) is the deploy-side rollback — don't delete it during cleanup; it's the "known good" we revert to if a build breaks.

### §4.5 Chunked generation (>150 lines)
1. **Chunk 1:** Imports + module-level constants + class declaration → write to disk
2. **Chunk 2:** Core logic (methods, public surface) → write to disk
3. **Chunk 3:** Helpers + `__post_init__` + edge cases → write to disk
4. **Chunk 4:** Polish, type hints on internals, docstring pass → write to disk

Write each chunk before proceeding. Don't stack in conversation.

### §4.6 Convergence
If ~15 exchanges pass without shipping: pause, summarize, ask whether to continue, decompose, or ship what exists.

---

## §5 ANTI-PATTERNS (NEVER DO THESE)

> **AI self-check:** Before presenting generated code, scan this table top to bottom. If output matches any trigger, fix it first. **Fork-policy anti-patterns (AP-K1..K5)** live in `CLAUDE.md` § Fork Design Discipline and supersede this table when they apply.

### Core / General

| ID | Sev | Trigger pattern | Fix ref |
|---|---|---|---|
| AP-K-01 | ❌ | File edit without git pre-flight (§3.3) | §3.3 |
| AP-K-02 | ⚠️ | Removed observable behavior without user confirmation | §1.3 |
| AP-K-03 | ⚠️ | Code generated with no preceding reasoning | §1.7 |
| AP-K-04 | ❌ | Hardcoded device address / port / credential outside `config.py` | §6.5 |
| AP-K-05 | ⚠️ | Single-pass generation over ~150 lines | §4.5 |
| AP-K-06 | ⚠️ | Missing/incorrect copyright header on new file | §6.1 |
| AP-K-07 | ❌ | Type hints missing on a new public function | §6.4 |
| AP-K-08 | ⚠️ | Custom config field placed mid-list in `KodiConfigDevice` (merge-conflict risk) | §1.11 |
| AP-K-09 | ⚠️ | Upstream code reformatted by `ruff format` outside the file's actual edit | §1.11 |
| AP-K-10 | ⚠️ | Doc reference attributes a fork-only feature to upstream (or vice versa) | §3.5 |

### Async / Asyncio

| ID | Sev | Trigger pattern | Fix ref |
|---|---|---|---|
| AP-K-20 | ❌ | `asyncio.create_task(...)` without `.add_done_callback(_log_task_exception)` (Patch 13 pattern) | §7.1 |
| AP-K-21 | ❌ | `await lock.acquire()` without `asyncio.wait_for()` timeout (Patch 12 pattern) | §7.2 |
| AP-K-22 | ❌ | `except Exception:` swallowing `asyncio.CancelledError` (must re-raise or list separately) | §7.3 |
| AP-K-23 | ⚠️ | `aiohttp.ClientSession()` constructed per-call instead of per-device-lifetime (Patch 40 lesson) | §7.5 |
| AP-K-24 | ⚠️ | Periodic task with fixed interval (no jitter) — fleet thundering-herd risk (Patch 17 lesson) | §7.6 |
| AP-K-25 | ⚠️ | `events.once(...)` listener without timeout-bounded `asyncio.wait_for` and explicit `remove_listener` cleanup on timeout | §7.7 |
| AP-K-26 | ⚠️ | f-string in log args (`_LOG.debug(f"x={x}")`) — use %-style: `_LOG.debug("x=%s", x)` | §6.6 |

### ucapi

| ID | Sev | Trigger pattern | Fix ref |
|---|---|---|---|
| AP-K-30 | ❌ | Stripping advertised `Features.*` to hide UI | CLAUDE.md AP-K1 |
| AP-K-31 | ❌ | Emitting `MEDIA_IMAGE_URL=""` on transient fetch failure (destroys cached image; use omit-on-failure — Patch 36) | §8.3 |
| AP-K-32 | ⚠️ | `entity.update_attributes()` returning the frozen `__init__`-time dict instead of `all_attributes` (Patch 19 regression) | §8.2 |
| AP-K-33 | ⚠️ | Pushing full `{OPTIONS, CURRENT_OPTION}` snapshot when only `CURRENT_OPTION` changed (Qt ListView reset bug — Patch 21) | §8.2 |
| AP-K-34 | ⚠️ | Returning `StatusCodes.OK` from a command handler when the underlying call failed (silent corruption — Patch 15 lesson) | §8.5 |

### Kodi JSON-RPC

| ID | Sev | Trigger pattern | Fix ref |
|---|---|---|---|
| AP-K-40 | ❌ | `eval()` on Kodi-call argument string. Use `ast.literal_eval()` AND return `BAD_REQUEST` on parse failure (Patches 7 + 15) | §8.5 |
| AP-K-41 | ⚠️ | `Player.GetChapters` (or any Kodi 22+ method) without `ProtocolError` catch — older Kodi raises `-32601 Method not found` (Patch 22) | §12.1 |
| AP-K-42 | ⚠️ | `all(...)` filter on `OnPropertyChanged` event keys instead of `any(...)` — Kodi bundles properties (Patch 23) | §12.4 |
| AP-K-43 | ⚠️ | Defaulting an art-dict-shape config field from one PVR/source class | CLAUDE.md AP-K4 |
| AP-K-44 | ⚠️ | `Content-Type` header check on Kodi `/image/` responses — Kodi omits the header; always defaults to `application/octet-stream` (Patch 29 lesson) | §12.3 |

### Build / Deploy

| ID | Sev | Trigger pattern | Fix ref |
|---|---|---|---|
| AP-K-50 | ❌ | PyInstaller invoked without preceding `pip install -r requirements.txt` (binary will crash on UC3) | §13.5 |
| AP-K-51 | ❌ | `tar czf` at a `C:\...` path on Windows Git Bash (treats colon as `host:path`) — build at `/tmp/`, then `mv` | §13.5 |
| AP-K-52 | ⚠️ | `docker run -w /sources` on Git Bash without `MSYS_NO_PATHCONV=1` (path mangled to `C:\Program Files\Git\sources`) | §13.5 |
| AP-K-53 | ⚠️ | Pushed without local `ruff check` / `ruff format --check` — CI red on push | §6.2 |
| AP-K-54 | ⚠️ | Skipped post-merge doc audit (§3.5) | §3.5 |

> **Cross-reference layer:** Severe fork-policy patterns (artwork pipeline state, Features-stripping, rendering-symptom misdiagnosis, single-target config defaults, Divergent Change) live as **AP-K1..K5** in `CLAUDE.md § Fork Design Discipline` because they're load-bearing rules with patch-specific case studies. The table above is the broader domain catch-all.

---

## §6 PYTHON CONVENTIONS

### §6.1 File headers

Match upstream's MPL-2.0 docstring header (read from `src/config.py:1-6`, `src/driver.py:2-7`):

```python
#!/usr/bin/env python3      # ONLY on entry point (driver.py)
"""
<one-line module description>.

:copyright: (c) <year> by <Author>.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""
```

For new files in our fork, use `:copyright: (c) <year> by madalone.` plus a brief description; for modified upstream files, **leave the upstream header intact** and don't add a parallel `madalone` line (keeps merge surface clean — see §1.11).

### §6.2 Formatting & linting

CI runs (and you must run locally before push) — migrated to **ruff + pyright** in the v1.20.2 merge (matching upstream), replacing pylint/flake8/isort/black:

```bash
ruff check src/          # lint (blocking in CI)
ruff format --check src/ # format (blocking in CI)
```

- **ruff** (`==0.15.21`): lint + format in one tool. Config in `pyproject.toml` (adopted from upstream, `line-length = 120`, `target-version = "py311"`, ~90 ignored rule codes). `ruff format` is >99.9% black-compatible; our files were already black@120-shaped so the migration reformatted almost nothing. Skip `pykodi/` only where the vendor style demands it. Suppress fork-patch false positives **inline** (`# noqa: S311` on jitter, `# noqa: PTH122` on the sidecar `os.path.splitext` helpers) to keep `pyproject.toml` byte-identical to upstream.
- **pyright** (`==1.1.411`, strict): runs in CI but currently **non-blocking** (`continue-on-error: true`) pending a triage of ~22 pre-existing/patch-related strict errors in a deps-installed venv.

See `feedback_run_formatters_pre_push.md` and CLAUDE.md `### Pre-push validation`.

### §6.3 Import ordering (PEP 8 / isort)

Three sections, alphabetical within each, blank line between:

```python
# 1. Stdlib
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

# 2. Third-party
import jsonrpc_base
import ucapi
from aiohttp import ClientError, ClientSession, ClientTimeout
from pyee.asyncio import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr

# 3. Local (no leading dots — fork uses `from x import` style)
from config import KodiConfigDevice
from const import KODI_*
from pykodi.kodi import Kodi, KodiWSConnection
```

Pylint may flag `jsonrpc_base` (no PEP 561 stubs) — silence with `# pylint: disable=E0401` only on that import line.

### §6.4 Type hints (PEP 484 / 526)

**Required on:**
- All new public functions and methods (parameters AND return type).
- All new dataclass fields.
- Module-level constants where the type isn't obvious from the literal.

**Optional on:**
- Private helpers (`_name`) when types are obvious from context.
- Lambda functions and trivial closures.

**Exception:** `pykodi/` is vendored — match the vendor's existing style (often partial type hints).

```python
async def _fetch_artwork_with_retry(self, url: str) -> str | None:
    """Fetch artwork with up to 3 attempts; returns base64 data URI or None on exhaustion."""
    ...
```

Use `X | None` (PEP 604, Python 3.10+) over `Optional[X]` for new code. `Optional[X]` is fine in modified upstream code (don't churn imports).

### §6.5 Dataclass conventions

Pattern from `KodiConfigDevice` in `src/config.py:47-87`:

```python
@dataclass
class MyConfig:
    """One-line class description (PEP 257)."""

    # Required fields first (no default)
    id: str
    name: str

    # Optional fields with defaults — ALL custom additions go at END
    new_field: int = field(default=12)

    def __post_init__(self):
        """Apply default values on missing fields and validate critical fields."""
        # 1. Fill missing defaults (handles legacy JSON load)
        for attribute in fields(self):
            if not isinstance(attribute.default, dataclasses.MISSING.__class__) \
               and getattr(self, attribute.name) is None:
                setattr(self, attribute.name, attribute.default)

        # 2. Coerce types (string booleans from legacy configs, int parsing, etc.)
        # 3. Validate ranges, raise ValueError on garbage
```

**Default-value migration caveat (Patch 44 → 44b):** the MISSING-default loop fills *absent* fields only — won't migrate existing values when a default *changes*. If a future patch needs to flip a default, either: (a) accept manual reconfigure (document in patch entry), OR (b) add an explicit version-gated migration in `__post_init__`. See CLAUDE.md Mandatory Rule 3.

### §6.6 Logging conventions

Module-level logger:

```python
_LOG = logging.getLogger(__name__)

# Exception: driver.py uses a literal name to avoid `__main__` in messages:
# _LOG = logging.getLogger("driver")
```

**%-style format strings, NEVER f-strings in log args:**

```python
# CORRECT — formatter defers interpolation; works with structured log handlers
_LOG.debug("[%s] artwork fetch ok url=%s len=%d", self.address, url, len(data))

# WRONG — interpolation happens at call time even if level disabled
_LOG.debug(f"[{self.address}] artwork fetch ok url={url} len={len(data)}")
```

**Device-scoped log prefix:** when logging an event for a specific device, lead with `[%s]` carrying `self.device_config.address`. Matches the existing pattern across `kodi_device.py`. Makes multi-device log triage trivial.

**Levels:**
- `_LOG.debug(...)` — verbose; safe to spam during diagnosis
- `_LOG.info(...)` — lifecycle events (connect, disconnect, setup complete)
- `_LOG.warning(...)` — recoverable degradation (fallback used, retry exhausted but state retained)
- `_LOG.error(...)` — unhandled exception, lost data

Don't use `_LOG.critical` — UC3 has no concept of critical-level alerting.

### §6.7 Exception handling

**Narrow except blocks.** Patches 11, 16, and 22 spent significant effort eliminating bare `except Exception: pass` blocks. Don't reintroduce them.

```python
# CORRECT
try:
    await self._kodi_connection.connect()
except (OSError, TransportError, CannotConnectError) as ex:
    _LOG.debug("[%s] connect failed: %r", self.address, ex)
    return False

# WRONG — too broad, hides bugs
try:
    await self._kodi_connection.connect()
except Exception:
    pass
```

**Never swallow `asyncio.CancelledError`.** Cancellation must propagate. If you have a broad cleanup catch, list `CancelledError` separately and re-raise:

```python
try:
    await self._do_thing()
except asyncio.CancelledError:
    raise
except (OSError, RuntimeError) as ex:
    _LOG.debug("[%s] cleanup failed: %r", self.address, ex)
```

See CLAUDE.md Mandatory Rule 8 and §7.3.

### §6.8 Constants and module-level state

- `UPPER_CASE` for constants (`UPDATE_LOCK_TIMEOUT = 30`, `ARTWORK_FETCH_RETRY_DELAYS = (0.0, 0.5, 1.5)`).
- `_underscore_prefix` for module-private (helpers not part of the export surface).
- No mutable module-level state. Per-device state lives on `KodiDevice` instance.

### §6.9 Docstring conventions (PEP 257)

- One-line summary in imperative mood for public functions/methods.
- Multi-line: summary + blank line + details + parameters/returns. Keep tight.
- Don't repeat the type annotations in the docstring (they're in the signature).

```python
async def call_command(self, method: str, **params: Any) -> Any:
    """Send a Kodi JSON-RPC method call. Returns the response dict or raises."""
```

---

## §7 ASYNC PATTERNS

### §7.1 `asyncio.create_task` vs `await` — never fire-and-forget without observability

The `_log_task_exception` helper in `src/kodi_device.py:94` is mandatory for every fire-and-forget task:

```python
def _log_task_exception(task: asyncio.Task) -> None:
    """Log unhandled exceptions from background tasks; called as add_done_callback."""
    if task.cancelled():
        return
    if task.exception() is not None:
        _LOG.error("Unhandled exception in background task: %s", task.exception())

# Usage:
asyncio.create_task(self._update_states(deferred=4)).add_done_callback(_log_task_exception)
```

Patch 13 introduced this; bare `asyncio.create_task(...)` without the callback silently swallows exceptions on any failure path. AP-K-20.

### §7.2 Locks, semaphores, `asyncio.wait_for`

**Always wrap lock acquisition in `asyncio.wait_for`** (Patch 12 lesson). A held lock on a background task that crashes leaves callers waiting forever:

```python
try:
    async with asyncio.wait_for(self._update_lock.acquire(), timeout=UPDATE_LOCK_TIMEOUT):
        try:
            ...  # critical section
        finally:
            self._update_lock.release()
except asyncio.TimeoutError:
    _LOG.warning("[%s] Update states lock acquisition timed out, skipping", self.address)
    return
```

`UPDATE_LOCK_TIMEOUT` is 30s (Patch 40 raised from 10s to accommodate worst-case retry budget). AP-K-21.

### §7.3 Cancellation handling

Per [asyncio docs](https://docs.python.org/3/library/asyncio-task.html#task-cancellation): `CancelledError` must propagate. Watchdog cancellation paths (`pykodi/kodi.py:159` style) must NOT log-and-continue.

```python
try:
    await self._websocket_task
except asyncio.CancelledError:
    raise   # let it propagate
except (OSError, TransportError) as ex:
    _LOG.debug("[%s] websocket task cleanup: %r", self.address, ex)
```

If you must swallow CancelledError (rare; only on a graceful shutdown path), document why in a comment. AP-K-22 / CLAUDE.md Mandatory Rule 8.

### §7.4 Shared state and gating predicates

When a flag participates in 3+ guard predicates across async functions, **stop adding flags**. Either:
- Extract to an explicit state machine (`enum`-keyed transitions), OR
- Use a transition queue / per-consumer buffer (the Inngest "lost updates in asyncio" pattern), OR
- Eliminate the shared state entirely.

The artwork pipeline (`_update_states` artwork block) is the canonical example: 4+ mutable fields, 3+ guards, 5+ patches mutating the same logic. See CLAUDE.md AP-K2 and AP-K5.

### §7.5 `aiohttp.ClientSession` lifecycle (Patch 40)

**One `ClientSession` per device, lifecycle = connect/disconnect.** Never construct per-call.

```python
# In __init__:
self._artwork_session: ClientSession | None = None

# In connect() (after event loop is running):
if self._artwork_session is None or self._artwork_session.closed:
    self._artwork_session = ClientSession()

# In _clear_connection():
if self._artwork_session is not None and not self._artwork_session.closed:
    try:
        await self._artwork_session.close()
    except (ClientError, OSError) as ex:
        _LOG.debug("[%s] artwork session close: %r", self.address, ex)
self._artwork_session = None
```

Per-call construction loses connection pooling, pays TLS/connect overhead each time, and breaks `keepalive`. AP-K-23. See [aiohttp ClientSession docs](https://docs.aiohttp.org/en/stable/client_reference.html#client-session).

### §7.6 Periodic tasks and watchdogs (jitter, bounded intervals)

Patch 17 added ±25% jitter to the watchdog reconnect interval. Patch 24 added periodic state-refresh on watchdog tick. Pattern:

```python
import random

async def _watchdog(self) -> None:
    while not self._closing:
        try:
            interval = WEBSOCKET_WATCHDOG_INTERVAL
            if self._reconnect_retry >= RETRY_BACKOFF_THRESHOLD:
                interval = WEBSOCKET_WATCHDOG_BACKOFF_INTERVAL
            jittered = interval * random.uniform(0.75, 1.25)
            await asyncio.sleep(jittered)
            ...
        except asyncio.CancelledError:
            raise
        except (OSError, ProtocolError) as ex:
            _LOG.debug("[%s] watchdog tick error: %r", self.address, ex)
```

Without jitter, a fleet of UC3s wakes lock-step after a router reboot and hammers Kodi. AP-K-24.

### §7.7 Event emitters (`pyee`)

The fork uses `pyee.asyncio.AsyncIOEventEmitter`. Pattern for one-shot listeners (Patch 41):

```python
loop = asyncio.get_running_loop()
fut: asyncio.Future = loop.create_future()

def _on_next(*_args, **_kwargs):
    if not fut.done():
        fut.set_result(None)

device.events.once(Events.UPDATE, _on_next)

try:
    await asyncio.wait_for(fut, timeout=30.0)
except asyncio.TimeoutError:
    try:
        device.events.remove_listener(Events.UPDATE, _on_next)
    except (KeyError, ValueError):
        pass
    return
```

The `events.once` registration self-removes on first fire; `asyncio.wait_for` bounds the wait so a permanently-idle integration doesn't leak the listener. Explicit `remove_listener` in the timeout path is defensive — `pyee` raises `KeyError`/`ValueError` if already removed, which is fine. AP-K-25.

---

## §8 ucapi CONVENTIONS

### §8.1 Entity registration — features declared once at startup

The ucapi protocol has **no `features_changed` event** ([core-api WebSocket Integration API](https://unfoldedcircle.github.io/core-api/integration/) — event surface includes `entity_change`, `entity_available`, `entity_removed`, `device_state`, `driver_setup_change`, `assistant_event`; no feature-set mutation event).

**Implication:** once a UC Remote 3 has subscribed to an entity, the feature set is effectively immutable for that subscription. Removing a feature post-subscribe doesn't propagate — and modern remote-ui (v1.4.1+) honors the feature set strictly, so a stripped feature breaks the underlying function.

UI hiding belongs in remote-ui `Config.show*` (firmware concern), NOT in integration entity capabilities. See CLAUDE.md AP-K1 for the patch history (Patch 6 / dropped pre-release toggles in `.2` / Patch 27).

### §8.2 Attribute updates — partial-update semantic

`entity_change` is a **partial state delta**. Three distinct semantics:
- **Emit a real value** — state changed, value is the new value.
- **Omit the attribute** — no change; canonical "no update" signal. The remote retains its prior value.
- **Emit `""`** — state is genuinely empty (e.g., on-stop). Destructive — replaces prior value with empty.

**Patch 36 lesson:** emitting `""` on transient artwork-fetch failure destroyed the remote's cached image. Use omit-on-failure semantic; emit `""` only on genuine no-art states (on-stop, no-players). AP-K-31.

**Subscribe-time push:** when `on_subscribe_entities` fires, push `filter_attributes(device.attributes, ucapi.media_player.Attributes)` synchronously. The `attributes` property must return current (not frozen `__init__`-time) state — see Patch 19 / `update_attributes()` returning `all_attributes`. AP-K-32.

### §8.3 `MediaAttr.MEDIA_IMAGE_URL` semantics

| State | Emit | Reason |
|---|---|---|
| New artwork resolved successfully | base64 data URI (when `download_artwork=true`) or HTTP URL | Update propagates |
| Same artwork as before | omit | No change — partial-update semantic |
| Transient fetch failure | omit | Retain prior value (Patch 36) |
| Genuine no-art (on-stop, no-players, item changed to art-less) | `""` | Destructive clear is intended |

**MIME header on data URIs:** Kodi's `/image/` endpoint omits `Content-Type`. `aiohttp` defaults to `application/octet-stream`. Qt rejects unknown declared MIME outright. **Sniff magic bytes** before constructing the data URI (Patch 39):

```python
if buffer[:3] == b"\xff\xd8\xff": mime = "image/jpeg"
elif buffer[:8] == b"\x89PNG\r\n\x1a\n": mime = "image/png"
elif len(buffer) >= 12 and buffer[:4] == b"RIFF" and buffer[8:12] == b"WEBP": mime = "image/webp"
elif buffer[:6] in (b"GIF87a", b"GIF89a"): mime = "image/gif"
else: mime = "image/jpeg"   # safest unknown — Qt is forgiving of mismatch but rejects unknown
```

AP-K-44 forbids checking the actual `Content-Type` response header.

### §8.4 `Events.UPDATE` emission

```python
self.events.emit(Events.UPDATE, self.id, updated_data)
```

`updated_data` is a `dict[MediaAttr | SelectAttributes | ..., Any]`. Only include keys that actually changed (partial-update). Don't emit a full snapshot per tick — let `attributes` property handle subscribe-time pushes.

### §8.5 `StatusCodes` — when to return what

Command handler returns:
- **`StatusCodes.OK`** — operation succeeded.
- **`StatusCodes.BAD_REQUEST`** — request was malformed (parse error, missing required argument). Patches 7+15 lesson: returning OK on parse failure silently corrupted commands.
- **`StatusCodes.NOT_IMPLEMENTED`** — command not supported by current device state (used as fallback signal in remote button-mapping path).
- **`StatusCodes.SERVICE_UNAVAILABLE`** — device not connected.
- **`StatusCodes.SERVER_ERROR`** — unhandled exception during command execution.

`@retry()` decorator in `kodi_device.py` swallows ProtocolError on the second attempt when `suppress_unsupported_command_errors=True` (Patch 26) — returning OK is acceptable there because the user opted in.

AP-K-34: never return OK from a command handler when the underlying call failed.

### §8.6 Setup flow / config flow — 5 touch-points (CLAUDE.md Mandatory Rule 3)

When adding a new config field:

1. **`src/config.py`** — add field to `KodiConfigDevice` dataclass (at END of fields list — see §1.11).
2. **`src/setup_fields.py`** — add UI definition (checkbox, dropdown, number).
3. **`src/setup_flow.py` initial parse** — read from setup form into a local var.
4. **`src/setup_flow.py` device creation** — pass to `KodiConfigDevice(...)` constructor.
5. **`src/setup_flow.py` reconfig** — three sub-steps: parse from form, assign to existing config, pre-populate the form on next reconfig open.

Skipping any of the 5 produces silent partial behavior. Search for an existing field name (e.g., `download_artwork`) and grep all call sites — that's your template.

---

## §9 PATCH ANATOMY — Template for new patches

### §9.1 Format (mirrors existing entries in `KODI-INTEGRATION-PATCHES.md`)

```markdown
## Patch N: <Short Title>

**File(s):** `src/X.py`, `src/Y.py` (and method or line range when relevant)

**Problem:** What's broken. Be specific. Include reproduction steps OR live capture (`ws://uc3:80/ws`, `Player.GetItem` JSON-RPC sample) when the bug is shape-dependent.

**Solution:** What changes. Code snippet showing before/after when the change is small enough.

**Reference:** Link to upstream issue / Kodi wiki / xbmc PR / aiohttp doc / external source.

**Scope:** What this affects vs what it doesn't.

**Breaking changes flagged:** Explicit "none observable" or list the changes.
```

### §9.2 Patch design checklist (run AP-K1..K5 in order before drafting)

1. **AP-K1 trigger:** Does this patch hide a UI element by stripping `Features.*`? → Stop. Refer to remote-ui `Config.show*`.
2. **AP-K2 trigger:** Does this patch mutate artwork-block state (`_thumbnail`, `_media_image_url`, `_media_image_data`, `_artwork_pending_retry`, `_last_item_identity`)? → Map gating predicates, walk 2-3 next watchdog ticks.
3. **AP-K3 trigger:** Is the symptom rendering (blank/stale image) rather than data? → Wire capture + entity store check BEFORE drafting integration code.
4. **AP-K4 trigger:** Does the patch add a config default that depends on Kodi `Player.GetItem` shape? → Validate against ≥3 source classes (library + real PVR + plugin) first.
5. **AP-K5 trigger:** Is this the 3rd+ patch on this subsystem in this release window? → Stop. Inventory mutable state. Consider extraction refactor.

### §9.3 Required artifacts before patching (AP-K3 — for rendering-symptom patches)

1. **Wire capture:** `tools/diag_ws_capture.py` against `ws://uc3:80/ws` showing the `entity_change` attribute the integration emits during the buggy scenario.
2. **Entity store snapshot:** `curl http://uc3/api/entities/<entity_id>` showing UC core's configured-entity-store state for that entity.
3. **Kodi-side probe (when shape-relevant):** direct `Player.GetItem` JSON-RPC call against the live Kodi to capture the `art` and `thumbnail` shape.

If all three are correct but the screen is wrong → the bug is firmware-side. Document it; don't patch the integration unless the firmware fix is unavailable.

---

## §10 QA AUDIT CHECKLIST

### §10.1 Pre-build gate (run before any deploy)

| Check | Command | Pass criteria |
|---|---|---|
| Lint (ruff) | `ruff check src/` | All checks passed (blocking) |
| Format (ruff) | `ruff format --check src/` | No diff (blocking) |
| Type check (pyright) | `pyright` | Non-blocking until strict-error triage; no NEW errors vs baseline |
| Smoke build | PyInstaller per CLAUDE.md Build & Deploy | tar.gz produced, contents valid |

### §10.2 Pre-output self-check (before presenting code or patch)

1. Did I run reasoning-first (§1.7)?
2. Did I scan §5 anti-patterns (table top to bottom)?
3. Did I run AP-K1..K5 trigger (CLAUDE.md § Fork Design Discipline)?
4. Did I cite the relevant patch numbers, PEP, or external doc?
5. Did I flag breaking changes explicitly?
6. Are all new public functions type-annotated?
7. Did I use %-style log strings (not f-strings)?

### §10.3 Periodic audit (sectional sweep)

Every release window, sweep one section of `src/`:
1. Read each module top to bottom.
2. Cross-reference against §5 + AP-K1..K5.
3. File findings into `_audit_logs/YYYY-MM-DD_<module>.md` with severity (§1.9).
4. Triage: ❌ ERROR → fix this release; ⚠️ WARN → next release; ℹ️ INFO → backlog.

Skip `pykodi/` — vendored.

---

## §11 SESSION DISCIPLINE

### §11.1 Ship it or lose it
When a file is finalized, write it to disk immediately. Don't hold finished code in conversation.

### §11.2 Reference, don't repeat
Once a code block has been established, refer to it by file:line — don't paste it again. If the user needs to see something again, re-read the file.

### §11.3 Artifact-first
When the deliverable is code, write the file. Don't narrate 300 lines of Python across conversational messages.

| Situation | Do this | Not this |
|---|---|---|
| Delivering a new patch | Write the file edits + the patches-doc entry, summarize in 2-3 sentences | Walk through every method conversationally |
| Applying 5 fixes | Make the edits, list what changed | Explain each fix in a paragraph, then edit |
| User asks "what changed?" | Reference the git diff | Paste before and after |

### §11.4 Session scoping
One major patch per session. Don't start a second patch in the same conversation where you just finished a multi-file change. Quick follow-ups (typo fixes, doc updates) are fine.

### §11.5 Turn threshold
~15 exchanges without shipping = pause and reassess scope.

### §11.6 Propose style-guide updates from session learnings

This guide is a living document. Propose an update if you've hit:
- The same gotcha in two different sessions (codify so a third doesn't happen)
- A new memory entry that captures a behavioral rule the guide doesn't have a section for
- An upstream-merge surprise that future sessions will repeat without the rule
- A pattern from a shipped patch worth generalizing (new template, new anti-pattern, new sub-§)

**Process:** propose in one sentence — what the rule is and where it'd live (existing §, new sub-§, or new AP-K). Wait for yes/no/defer. If yes, make the edit in the same session.

**Don't propose:**
- Speculative or tentative rules — only add what's proven by repeated incidence
- One-off observations — patterns only
- Backlog items — those belong in build logs or memory, not the guide

---

## §12 KODI INTEGRATION CONSTRAINTS

### §12.1 Kodi JSON-RPC version compatibility

| Method | Min Kodi version | Catch | Fix ref |
|---|---|---|---|
| `Player.GetChapters` | Kodi 22 | `(KeyError, IndexError, TypeError, ValueError, TransportError, ProtocolError)` | Patch 22 |
| `Player.GetItem` | Kodi 19+ baseline | Always available; but `art` dict shape varies | §12.2 |

When using a Kodi-version-gated method, **always catch `ProtocolError`** — older Kodi raises `(-32601, "Method not found")` and abort the entire `_update_states` call. AP-K-41.

Test against Kodi 19, 20, 21, 22 if possible. The reference test device runs Kodi 21.x on `madteevee.local`.

### §12.2 PVR data shape variation

Kodi's `Player.GetItem` returns differently-shaped `art` and `thumbnail` fields depending on source:

| Source | `art` keys present | Top-level `thumbnail` | Notes |
|---|---|---|---|
| Library movie | `poster`, `thumb`, `fanart`, `icon`, `clearlogo` | populated | Default `artwork_type="thumb"` works |
| Library TV episode | + `tvshow.poster`, `tvshow.clearlogo` | populated | `artwork_type_tvshows="tvshow.poster"` |
| Netflix plugin | `icon` only (with real URL) | `""` | Fallback chain (Patch 28) needed |
| YouTube plugin | `icon`, `thumb`, `poster`, `fanart` | populated | Works |
| Unscraped local | `icon: "DefaultVideo.png"` | `""` | Patch 29 filters Default*.png |
| PseudoTV channel | `icon: <addon-path>`, `thumb: <embedded show poster>` | `<addon-path>` (channel logo) | `artwork_type_channels="icon"` |
| Real PVR (Kodi PVR client) | `icon: <pvrchannel_tv@...>` | `<EPG program image>` | `artwork_type_channels="icon"` (Patch 44b) |

Kodi upstream issues confirm this is documented behavior, not a quirk — see [xbmc/xbmc#19151](https://github.com/xbmc/xbmc/issues/19151), [#16245](https://github.com/xbmc/xbmc/issues/16245), [forum thread #371822](https://forum.kodi.tv/showthread.php?tid=371822). Default-value selection for any shape-dependent config field MUST validate on ≥3 source classes (library + real PVR + plugin/addon). See CLAUDE.md AP-K4.

### §12.3 Kodi `/image/` endpoint behavior

- **No `Content-Type` header** on thumbnail responses. `aiohttp` defaults to `application/octet-stream`. NEVER filter on Content-Type — every legitimate thumbnail will be rejected. Magic-byte sniff instead (Patch 39, §8.3). AP-K-44.
- **`image://Default*.png` URIs return HTML error body**, not images. Filter at the integration layer (Patch 29a) AND validate HTTP 200 before base64 (Patch 29b).
- **Bare `special://...` paths** (not wrapped in `image://`) are NOT resolved by `pykodi.thumbnail_url()`. Wrap with `image://<urllib.parse.quote(path, safe="")>/` before passing through the fetch pipeline (Patch 44 sentinel handling).
- **Sidecar thumbnails** (Sonarr `<base>-thumb.jpg`, Kodi `.tbn`, folder-level `poster.jpg`) — Kodi's JSON-RPC does NOT scan for these (skin-only behavior). Replicate the scan at browse-time (free, in `media_browser.py`) AND play-time (1 extra `Files.GetDirectory` call, Patch 30).

### §12.4 Kodi WebSocket events — bundled property changes

Kodi frequently bundles multiple properties in a single `OnPropertyChanged` notification (e.g., `{"property": {"currentsubtitle": {...}, "speed": 1}}`). The handler filter MUST use `any()`, not `all()` — `all()` requires every key to be in the whitelist and silently drops bundled events (Patch 23). AP-K-42.

```python
# CORRECT
if any(x in {"currentaudiostream", "currentsubtitle", "subtitleenabled", "currentvideostream"}
       for x in data.get("property", {}).keys()):
    asyncio.create_task(self._update_states()).add_done_callback(_log_task_exception)
```

---

## §13 UC3 INTEGRATION-API DIAGNOSTICS

This section is the operational counterpart to §1.8 (research-first) and AP-K3 (suspect firmware before patching). Once you've decided to instrument something, here's how.

### §13.1 Sources of truth (where to look first)

| Source | URL / path | Auth | Use for |
|---|---|---|---|
| ucapi protocol spec | [unfoldedcircle/core-api WebSocket Integration API](https://unfoldedcircle.github.io/core-api/integration/) | Anonymous (docs) | Event surface, attribute names, status codes |
| ucapi-python README + examples | [unfoldedcircle/integration-python-library](https://github.com/unfoldedcircle/integration-python-library) | N/A | Entity registration patterns, event emission |
| UC3 device entity store | `GET http://<uc3>/api/entities/<entity_id>` | PIN-based | What state UC core thinks the entity is in |
| Integration logs | `GET http://<uc3>:8088/api/integration-logs/entries?service=core` | PIN-based | Driver process stdout/stderr captured by UC core |
| Logdy WS log stream | `ws://<uc3>:80/log/ws` | Anonymous | Live diagnostic stream during repro |

### §13.2 ucapi entity store inspection

When debugging a "screen shows wrong value" symptom (AP-K3):

```bash
# What did UC core last receive?
curl -s http://<uc3>/api/entities/media_player.kodi_driver.<device_id> \
  -u "web-configurator:<PIN>" | jq '.attributes.media_image_url'
```

If the entity store has the right value but the screen shows the wrong value → firmware-side rendering bug. Don't patch the integration. (Patch 41 lesson.)

### §13.3 Authentication

UC3 dev REST API uses PIN-based basic auth: `Authorization: Basic base64(web-configurator:<PIN>)`. Test device PIN is in `CLAUDE.md` Project Identity section (gitignored from this guide for shareability). Anonymous endpoints exist for reachability probes but aren't useful for entity store inspection.

### §13.4 Logdy WS capture — diagnostic, not telemetry

`tools/diag_ws_capture.py` (in fork) wraps a 60s capture during repro. Use for:
- "What does the integration emit during X?" — confirms wire-side behavior matches expectation.
- "Is the bug in our emit or somewhere else?" — first step of AP-K3 diagnostic chain.

Don't use for sustained telemetry (the firmware emits sparingly; relevant signals can be missed).

### §13.5 PyInstaller bundling gotchas

| Gotcha | Symptom | Fix |
|---|---|---|
| `pip install` skipped before PyInstaller | Binary starts then crashes with "Connection refused (os error 111)" — missing `ucapi`, `aiohttp`, etc. | Run `pip install -r requirements.txt` inside container BEFORE `pyinstaller` (AP-K-50) |
| `tar czf` at `C:\...` path on Windows Git Bash | tar fails ("host:path" parse) | Build at `/tmp/`, then `mv` to project dir (AP-K-51) |
| `docker run -w /sources` on Git Bash | exit 125 — path mangled to `C:\Program Files\Git\sources` | Prefix `MSYS_NO_PATHCONV=1` (AP-K-52) |
| Setup wizard `CONNECTION_REFUSED` | Ambiguous — could be mDNS, network, or driver crash | Diagnose in CLAUDE.md Troubleshooting Notes order: hostname/mDNS → network reachability → integration logs |

See `feedback_docker_msys_pathconv.md`, `feedback_tar_windows_colon_paths.md`.

### §13.6 Probing Kodi directly

When debugging Kodi-shape variation (AP-K4, §12.2):

```bash
curl -s http://<kodi-host>:8080/jsonrpc -u <user>:<pass> -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"Player.GetItem","params":{"playerid":1,"properties":["art","thumbnail","title","type"]},"id":1}' | jq
```

This is the cheapest way to verify what shape Kodi returns for the source you're testing. Capture the output into the patch entry's "Problem" section as documentation.

---

## §14 COMMUNICATION STYLE

- Be direct. Don't over-explain obvious things.
- **Don't be sycophantic.** When reviewing fork work — including this fork's prior patches — lead with failures before wins. The user's gut about cycling has been right twice (the artwork pipeline, the Features-stripping reflex). Take it seriously.
- **Default to plain language.** Lead with what changes and why it matters. Patch numbers, AP-K IDs, and code-level detail are for when the user is reviewing those artifacts — not the default shape of every reply. Tables and structured headings are for genuinely complex comparisons, not the default response.
- **Confirm scope before deep multi-step planning.** For multi-file refactors, style-guide overhauls, upstream-PR scoping: ask one or two clarifying questions about scope/preference *before* producing the full structured plan.
- **For cross-fork tasks, confirm direction.** "Plan for Tier A" can mean "merge upstream's Tier A into our fork" OR "send our Tier A patches to upstream as PRs." Ask which.
- **Calibrated uncertainty.** If you didn't read the doc, say so. Don't label sources you haven't verified as "documented" or "canonical." The user is non-dev for some Python/asyncio internals; calibrated honesty matters more than confident-sounding wrongness.
- When reviewing, suggest concrete improvements with code (or precise file:line references).
- Edit files directly when filesystem access is available.
- Present options with trade-offs and let the user choose.
- **Explain as you go** — narrate reasoning in real time. If you hit a surprise mid-generation, say so.
