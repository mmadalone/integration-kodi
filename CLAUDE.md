# CLAUDE.md -- Kodi Integration for UC Remote 3 (Patched Fork)

DON'T BE SYCOPHANTIC

## Project Identity

Patched fork of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (v1.21.0) for the **Unfolded Circle Remote 3**. Python 3.11 async integration driver using the `ucapi` library.

**Owner:** madalone
**Device:** UC Remote 3 at `192.168.2.204`, PIN `6984`
**Upstream:** `albaintor/integration-kodi` tag `v1.21.0` (commit `2ecd63b`, merged 2026-08-28; prior base `v1.20.2`/`229d0b2`)
**Current branch:** `v1.21.0-patched` (working toward tag `v1.21.0-madalone.1` — HELD until on-device validation, checklist V0-V11 in `KODI-INTEGRATION-PATCHES.md` "Upstream Merge to v1.21.0"; last released tag `v1.20.2-madalone.1` at `62a61de` on `v1.20.2-patched`, 2026-07-24)
**Language:** Python 3.11 (async/await, `ucapi` 0.7.0, `aiohttp` 3.14, Kodi JSON-RPC)
**Build toolchain:** `docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0`

---

## Directory Structure

```
src/
  driver.py              # Main entry point, entity registration, event wiring
  kodi_device.py         # Core device logic (~1800 lines): state, commands, WebSocket events
  media_player.py        # Media player entity: command dispatcher, browse, search
  remote.py              # Remote control entity
  sensor.py              # Sensor entities (volume, mute, streams, chapters, video/audio info)
  selector.py            # Select/dropdown entities (audio/subtitle stream, chapter)
  const.py               # Constants: features, keymaps, button mappings, simple commands
  config.py              # KodiConfigDevice dataclass, JSON persistence
  setup_fields.py        # Setup form field definitions (checkboxes, dropdowns)
  setup_flow.py          # Multi-step setup + reconfigure flow
  pykodi/
    kodi.py              # Low-level Kodi JSON-RPC wrapper
docker/
  Dockerfile             # Docker build (alternative to PyInstaller)
  docker-compose.yml     # Docker Compose (alternative deployment)
driver.json              # Integration metadata (ID, version, name, icon)
driver.spec              # PyInstaller spec
kodi.png                 # Integration icon
requirements.txt         # Python dependencies (includes local ucapi wheel)
KODI-INTEGRATION-PATCHES.md  # Detailed patch documentation
```

---

## PLANNING

Before presenting a plan, run this checklist in order:

1. **Identify operational mode** — BUILD / TROUBLESHOOT / AUDIT (see `STYLE_GUIDE.md` §2). Default to BUILD if ambiguous.
2. **Run AP-K trigger** — name which AP-K* (from `## Fork Design Discipline`) applies, or explicitly negate. No silent skips.
3. **Research first** — official docs and community sources before invention:
   - **ucapi:** `unfoldedcircle/core-api` AsyncAPI spec, `unfoldedcircle/integration-python-library` README + examples
   - **Python/asyncio:** `docs.python.org/3/library/asyncio-*.html`, PEP 484/526/654
   - **Kodi:** `https://kodi.wiki/view/JSON-RPC_API`, `xbmc/xbmc` issues, Kodi forums
   - **Upstream fork base:** `albaintor/integration-kodi` issues + PRs
   - **Aiohttp:** `docs.aiohttp.org` (ClientSession lifecycle, cancellation)
4. **Codebase check** — search existing code for duplicates, related implementations, reusable patterns. Don't reinvent.
5. **No hacky workarounds** — only proven approaches. If a workaround is unavoidable (e.g., firmware bug), flag it explicitly with `# Workaround for X — remove after Y` and document in `KODI-INTEGRATION-PATCHES.md`.
6. **Preserve working logic** — improve upon existing patterns; never silently alter working behavior.
7. **Flag breaking changes** — any change to entity features, attribute semantics, or stored config field meaning MUST be called out with impact assessment.
8. **Ask, don't guess** — if requirements are unclear, ask before drafting the plan.

See `STYLE_GUIDE.md` §1.7 (Reasoning-first) and §1.8 (Research-first mandate) for full detail.

## Build & Deploy

### Build (cross-compile for ARM64)

On Windows Git Bash (current environment):

```bash
cd "C:/Users/mique/_Claude Projects/integration-kodi-patch"
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd)":/sources -w /sources \
  docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0 \
  bash -c "pip install --user -r requirements.txt && pyinstaller --collect-submodules zeroconf --clean -y --onedir --name driver src/driver.py"
```

`MSYS_NO_PATHCONV=1` is **required on Git Bash** — without it, `-w /sources` gets mangled to `C:/Program Files/Git/sources` (`exit 125`). The `--user=$(id -u):$(id -g)` flag from the original macOS command is omitted because MSYS's `id -u/-g` values don't map cleanly into the container; running as the image's default user works fine.

**IMPORTANT:** Must run `pip install` before PyInstaller inside the container. PyInstaller bundles installed packages -- without `pip install` first, the binary will be missing dependencies (`ucapi`, `websockets`, `httpx`, etc.) and crash on the remote with "Connection refused (os error 111)".

Output: `dist/driver/` (binary + `_internal/`)

### Package

```bash
cd "C:/Users/mique/_Claude Projects/integration-kodi-patch"
rm -rf /tmp/kodi-pkg && mkdir -p /tmp/kodi-pkg/bin
cp dist/driver/driver /tmp/kodi-pkg/bin/
cp -r dist/driver/_internal /tmp/kodi-pkg/bin/
cp driver.json /tmp/kodi-pkg/
cp kodi.png /tmp/kodi-pkg/
cd /tmp/kodi-pkg && tar czf /tmp/kodi-integration-v<VERSION>.tar.gz .
mv /tmp/kodi-integration-v<VERSION>.tar.gz "C:/Users/mique/_Claude Projects/integration-kodi-patch/"
```

Note: creating the tarball directly at a `C:/…` path trips `tar` (colon treated as `host:path` separator). Build at `/tmp/` and `mv` into the project directory.

Required tar.gz structure:
```
./driver.json       # Root level
./kodi.png          # Root level
./bin/driver        # Binary in bin/
./bin/_internal/    # Dependencies in bin/
```

### Deploy to UC Remote 3

1. **Uninstall** existing Kodi integration via web UI at `http://192.168.2.204`
2. **Install** the new `.tar.gz` via web UI (Integrations > + > Upload)
3. **Configure** -- run through setup flow (Kodi IP, port, credentials, options)

Do NOT try to update via API (`/api/intg/drivers/kodi_driver/update`) -- it updates metadata only, not the binary. Always uninstall + reinstall via web UI.

### Revert to upstream

Install the upstream release tar.gz from [albaintor/integration-kodi releases](https://github.com/albaintor/integration-kodi/releases).

### Pre-push validation

CI runs `ruff check src`, `ruff format --check src`, and `pyright` on every push (migrated from pylint/flake8/isort/black in the v1.20.2 merge, matching upstream). Run the two blocking checks locally before push to avoid red CI:

```bash
ruff check src/
ruff format --check src/
```

`pyright` runs in CI too but is currently **non-blocking** (`continue-on-error: true`) until its ~22 strict errors are triaged in a deps-installed venv — see the "Upstream Merge to v1.20.2" section in `KODI-INTEGRATION-PATCHES.md`.

See `feedback_run_formatters_pre_push.md` and `STYLE_GUIDE.md` §6.2.

---

## Current Patches

All patches documented in detail in `KODI-INTEGRATION-PATCHES.md` (that file is the source of truth). Summary below (42 active patches as of `v1.20.1-madalone.2`; 3 retired — patches 33, 35, 45 — see Patch Discipline note below). v1.20.0 merge in "Upstream Merge to v1.20.0" section; v1.20.1 merge in "Upstream Merge to v1.20.1"; v1.20.0-madalone.2 / .3 were intermediate iterations; v1.20.1-madalone.2 retired three keypress aliases now reachable via `custom_command "key X"` syntax. **v1.20.2 merge (2026-07-23, "Upstream Merge to v1.20.2" section):** adopted the dependency refresh (`ucapi 0.7` / `aiohttp 3.14` / `zeroconf 0.150` / `jsonrpc-websocket 3.2.1`), upstream's Kodi **credential URL-encoding** fix in `pykodi/kodi.py` (fixes artwork 401s for passwords with `@`/`:`/`/`), a `media_browser` **Kodi-thumbnail fallback** extending patch 30 (sidecar → Kodi thumbnail → derive), and the **ruff/pyright tooling migration**. **v1.21.0 merge (2026-08-28, "Upstream Merge to v1.21.0" section):** one upstream commit (`2ecd63b`) confined to `media_browser.py` browse-time thumbnails — new **art-dict tier** via `get_artwork()` and a **mimetype `image/*` gate** on derive-from-file, `extract_thumbnail=True` at every call site; the fork collapsed its duplicated sidecar pre-computes so `get_item_from_file` owns one chain (**sidecar > art > Kodi thumbnail > derive-iff-image**) and also requests `"art"` at the `kodi://sources` call (library movies show poster with `video_only_browse_filter` ON). The headline feature (art for plain files from sources/favourites) needs **Kodi 22 + xbmc/xbmc#28244 (still open)** — inert on Kodi 21.x. Table below:

| # | Name | Summary |
|---|------|---------|
| 1 | Kodi label formatting tag stripping | Strips BBCode markup from media titles |
| 2 | Deferred artwork re-poll | +3s deferred re-poll on connect |
| 3 | Stop handler cleanup | Clears stale media info on playback stop |
| 4 | Artwork subscribe fix | Uses `media_artwork` in `attributes` property |
| 5 | "None" power-off option | Disables the power-off button |
| 6 | ~~Suppress volume overlay~~ | **Reworked in patch 27 — see below** |
| 7 | `eval()` → `ast.literal_eval()` | Security fix for `custom_command` |
| 8 | Missing `await` | Command-sequence serialization fix |
| 9 | Media position fix | `elapsed_time.seconds` → `total_seconds()` |
| 10 | Dead code + dependency cleanup | Removes unused `_buffered_callbacks`, prunes deps |
| 11 | Exception handling hardening | Narrows `except Exception: pass` blocks |
| 12 | Async lock race fix | `asyncio.wait_for()` + try/finally |
| 13 | Fire-and-forget task observability | Error-logging callbacks on `create_task` |
| 14 | Sensor state bug fix | `raise self._state` → `return self._state` |
| 15 | `custom_command` BAD_REQUEST on parse fail | Parse error no longer falls through |
| 16 | Narrow remaining bare `except`s | Final audit pass on exception handling |
| 17 | Reconnect delay jitter | `±25%` on watchdog sleep to avoid fleet thundering herd |
| 18 | `KodiConfigDevice.__post_init__` validation | Bool/int coercion + port/address validation |
| 19 | Empty select/sensor attrs on subscribe | `update_attributes()` returns `all_attributes` (dynamic) |
| 20 | Select entity push robustness | Full snapshot push + post-command refresh |
| 21 | Gate `OPTIONS` push on actual list change | Avoids Qt ListView.model reset bug in Select.qml |
| 22 | Widen chapter-fetch `except` for Kodi <22 | `Player.GetChapters` missing no longer aborts poll |
| 23 | `on_property_changed` filter: `any()` not `all()` | Bundled stream events no longer dropped |
| 24 | Periodic state-refresh safety net | Watchdog tick pokes `_update_states` |
| 25 | `video_only_browse_filter` | Hide music/pictures + strip nfo/srt/sub from browse |
| 26 | `suppress_unsupported_command_errors` | Swallow Kodi JSON-RPC ProtocolError (e.g. PVR pause) |
| 27 | Deprecate `suppress_volume_overlay` | Feature-removal reverted; toggle now no-op (no replacement on vanilla UC firmware — OSD hiding requires `Madalones-Defolded-Circle-3` fw fork's `Config.showVolumeOverlay`); WARNING logged if flag still True |
| 28 | Broader artwork fallback chain | poster/thumb/landscape/banner/fanart/clearart/icon walk when primary `artwork_type` yields nothing |
| 29 | Placeholder filter + HTTP status validation | Drops `image://Default*.png`; validates HTTP 200 before base64 encode (do **not** filter on Content-Type — Kodi omits the header) |
| 30 | Sidecar thumbnail detection | Sonarr `<base>-thumb.jpg`, Kodi `.tbn`, folder-level `poster.jpg` resolved at browse-time (free) + play-time (1 Files.GetDirectory) |
| 31 | `MODE_CONTEXT_MENU` simple command | `Input.ContextMenu` (always, bypass keymap) — raw context menu on any button |
| 32 | `MODE_PLAY_SELECTED` simple command | Kodi `play` action — context-sensitive play (plays focused folder/item) |
| 33 | ~~`MODE_KEYPRESS_C` simple command~~ — **RETIRED in v1.20.1-madalone.2** | Use `custom_command "key c"` instead — same `Input.ButtonEvent(c, KB)` |
| 34 | `MODE_CODEC_INFO` / `MODE_PLAYER_DEBUG` / `MODE_SYSTEM_MENU` simple commands | `codecinfo` / `playerdebug` / `GUI.ActivateWindow(shutdownmenu)` |
| 35 | ~~`MODE_KEYPRESS_ESC` simple command~~ — **RETIRED in v1.20.1-madalone.2** | Use `custom_command "key escape"` instead |
| 36 | Partial-update emit semantic | Omit `MEDIA_IMAGE_URL` on transient fetch failure instead of emitting `""` (which destroys the remote's cached image). Removes the dead `_reset_media_artwork()` workaround + `is_starting_media`/`current_artwork` snapshots that supported it. |
| 37 | Artwork-fetch retry budget | 3 attempts (delays 0/0.5/1.5s + ±20% jitter) inside `_fetch_artwork_with_retry()`. On exhaustion, schedules a deferred `_update_states(deferred=4)` retry. Replaces single-attempt fetch. |
| 38 | Item-identity guard | Track `(id, file)` of the playing item; only nuke artwork state when item changes OR new thumbnail is non-None. Eliminates flicker from transient `art={}` on PVR/plugin sources. |
| 39 | Magic-byte MIME sniff | Override `application/octet-stream` (Kodi omits Content-Type, aiohttp falls back) with correct `image/jpeg`/`png`/`webp`/`gif` from buffer magic bytes. Defaults to `image/jpeg` for unknown bytes — Qt rejects unknown declared MIME outright but tolerates declared-MIME mismatch. |
| 40 | Shared `ClientSession` + configurable artwork timeout | Single `aiohttp.ClientSession` per device (lifecycle = connect/disconnect) instead of per-fetch construction. New `artwork_timeout_seconds` setup field (range 5-60, default 12s, was 5s hardcoded). `UPDATE_LOCK_TIMEOUT` 10→30s to accommodate worst-case retry budget. |
| 41 | Subscribe-time refresh | `on_subscribe_entities` schedules `_post_subscribe_refresh` for media_player entities. Helper waits (via `events.once` + `asyncio.Future` + 30s timeout) for next `Events.UPDATE` from the device, then re-pushes `filter_attributes(device.attributes)`. Originally added to address blank-artwork-after-reinstall — turned out to be a firmware bug fixed in **UC-Remote-UI v1.4.10**; patch 41 is now redundant on v1.4.10+ firmware but retained as a harmless no-op for older firmware. See "Post-mortem" in `KODI-INTEGRATION-PATCHES.md`. |
| 42 | Deferred-retry actually retries | Adds `_artwork_pending_retry` flag + `_retry_pending` term to the artwork-block guard. Without it, the deferred re-poll scheduled on artwork-fetch failure was self-skipping (because `_thumbnail` had already been mutated by the failed attempt, so `_thumbnail_real_change` was false). The flag is set on fetch failure and cleared on success or genuine no-art state — letting both the explicit deferred retry and the natural watchdog cadence drive recovery. |
| 43 | Clear artwork in no-players branch | The no-players else-branch in `_update_states` cleared `media_title`, `media_album`, `media_artist`, etc. but left `media_image_url` populated. Combined with patch 36's omit-on-no-change semantic, the remote retained stale artwork when Kodi went idle without firing a clean `OnStop` event (e.g., Kodi crashed, connection dropped, user navigated away inside Kodi). Patch 43 explicitly clears `_thumbnail` / `_media_image_url` / `_media_image_data` / `_artwork_pending_retry` and emits `MEDIA_IMAGE_URL=""` in the same branch, mirroring the on-stop handler. |
| 44 | Channel-type artwork selection | New `artwork_type_channels` config field (default `"icon"`, dropdown in setup) with its own branch in the `_update_states` artwork-type selection. PVR / PseudoTV channels (`_item['type']='channel'`) were silently inheriting the generic `artwork_type` setting (default `"thumb"`), which on PseudoTV resolved to the embedded currently-airing show's season poster instead of the channel logo. Adds a `"thumbnail"` sentinel handling that wraps bare `special://...` paths into `image://...` so they resolve through `pykodi.thumbnail_url()` like any other URL. **Default flipped from `"thumbnail"` (madalone.7) → `"icon"` (madalone.8, hotfix 44b)** after real-PVR testing showed `art["icon"]` is the channel logo on both PseudoTV (`image://special://...pseudotv.../logos/<channel>.png/`) and real PVR (`image://pvrchannel_tv@<encoded>/`), while top-level `item['thumbnail']` is structurally inverted: channel logo on PseudoTV but EPG program-art on real PVR. See `KODI-INTEGRATION-PATCHES.md` patches 44 + 44b for the full diagnosis. |

**Dropped pre-release (v1.18.13-madalone.2):** `suppress_media_browser`, `suppress_shuffle`, `suppress_repeat` were drafted as integration-side feature-removal toggles. Pulled after diagnosis showed the feature list doesn't re-propagate to already-subscribed UC3 entities. UX for these now lives in UC-Remote-UI `Config.showMediaBrowserButton` / `showShuffleButton` / `showRepeatButton` (v1.4.2+). Dataclass fields retained as silent no-ops for config backward-compat.

### Patch 6 / 27: `suppress_volume_overlay` (deprecated)

Patch 6 (original) removed `Features.VOLUME` / `VOLUME_UP_DOWN` / `MUTE*` + suppressed `MediaAttr.VOLUME`/`MUTED` emission to hide the UC3 volume overlay. Patch 27 (v1.18.13-madalone.2) reverts both — the approach broke Kodi volume control entirely post remote-ui v1.4.1 (which correctly respects feature removals). Volume features are now always advertised; the deprecated toggle has no functional replacement on vanilla UC firmware. OSD visibility CAN be controlled when running the `Madalones-Defolded-Circle-3` firmware fork (which adds `Config.showVolumeOverlay`, surfaced as **Settings → UI → Show volume indicator**) — but this is NOT in upstream UC firmware. The config key is retained for backcompat; a one-time WARNING is logged per device if set to `True`. Patch 6's correctness fix to `on_volume_changed` (int-comparison) is retained.

---

## Architecture Quick Reference

### Event Flow
```
UC Remote button press
  -> media_player.py command()
  -> kodi_device.py (volume_up/down/mute/etc.)
  -> pykodi/kodi.py JSON-RPC to Kodi
  -> Kodi executes + shows OSD on TV
  -> Kodi fires WebSocket event (OnVolumeChanged, OnPlay, OnStop, etc.)
  -> kodi_device.py event handler updates state
  -> Events.UPDATE emitted to driver.py
  -> ucapi broadcasts to UC Remote
```

### Entity Types
- **Media Player** (`KodiMediaPlayer`): primary control entity with ~30 features
- **Remote** (`KodiRemote`): button mappings + simple commands
- **Sensors** (`KodiSensor*`): volume, muted, audio stream, subtitle stream, chapter, video info, audio info
- **Selectors** (`KodiSelect*`): audio stream picker, subtitle stream picker, chapter picker

### Config Pattern
`KodiConfigDevice` dataclass in `config.py` with `field(default=...)` defaults. Setup fields defined in `setup_fields.py`. Setup flow wiring in `setup_flow.py` (3 locations per field: initial setup parsing, device creation args, reconfigure parsing + assignment + pre-population).

### Key Dependencies
- `ucapi` 0.7.0 -- UC integration API (pulled from PyPI; **no local wheel** — the old `src/ucapi-*.whl` note was stale)
- `jsonrpc-async` / `jsonrpc-websocket` 3.2.1 -- Kodi JSON-RPC communication
- `aiohttp` 3.14 -- async HTTP
- `zeroconf` 0.150 -- mDNS discovery
- `pyee` -- event emitter

---

## Companion Firmware Fixes

Documented in `KODI-INTEGRATION-PATCHES.md` under "Companion Firmware Fixes". These live in the separate [UC-Remote-UI project](../UC-Remote-UI/) (sibling directory on Windows: `C:\Users\mique\_Claude Projects\UC-Remote-UI\`), not here:
- C++ duplicate URL gate in `mediaPlayer.cpp`
- QML image loader guard in `ImageLoader.qml`

---

## Mandatory Rules

1. **Read the relevant patch sections in `KODI-INTEGRATION-PATCHES.md` before modifying patched code.** The full file is ~47K tokens — DO NOT read wholesale. Use `Grep` to find the patch number(s) covering the file/method you're changing, then read just those patches. Each patch's "Problem / Solution / Reference" block is what you need; surrounding patches are not. The scan-table preamble at the top of the file is the index.

2. **Don't modify upstream logic.** Patches are targeted additions. Don't refactor surrounding upstream code -- it complicates future merges.

3. **Follow the config pattern.** New options need 5 touch points: `config.py` field, `setup_fields.py` checkbox/dropdown, `setup_flow.py` (initial parse + device creation + reconfig parse + reconfig assign + reconfig pre-populate).

   **Default-value migration:** the `__post_init__` MISSING-default loop only fills *absent* fields. If a future patch needs to *change* an existing field's default, persisted configs from prior versions still carry the old default. Either: (a) accept the migration cost (users reconfigure, document in patch entry), OR (b) add an explicit version-gated migration step in `__post_init__`. Patch 44 → 44b is the canonical case — flipped a 1-day-old default and accepted the manual-reconfigure UX.

4. **Test on device.** macOS/Docker builds verify syntax and packaging but NOT runtime behavior. Always deploy to the UC Remote and verify.

5. **Version the tar.gz.** Output file: `kodi-integration-v<VERSION>.tar.gz` in the project directory. Version in `driver.json` field `version`.

6. **`pip install` before PyInstaller.** See Build section. Omitting this produces a binary that starts but immediately crashes.

7. **Type hints required on public functions.** All new or modified public functions in `src/*.py` must have parameter and return type annotations (PEP 484/526). Private helpers (`_name`) may omit them when types are obvious from context. Exception: `pykodi/` is vendored — match the vendor's existing style. See `STYLE_GUIDE.md` §6.4.

8. **Never swallow `asyncio.CancelledError`.** Cancellation must propagate. If you catch a broad exception type for cleanup (e.g., `OSError` in a `_clear_connection`), explicitly check for and re-raise `CancelledError` first — or list it separately. Watchdog cancellation paths (`pykodi/kodi.py:159` style) must propagate cancellation, not log-and-continue. See `STYLE_GUIDE.md` §6.7 and §7.3.

9. **Logging conventions.** Module-level `_LOG = logging.getLogger(__name__)`. Use %-style format strings in log args (`_LOG.debug("[%s] %r", x, y)`), never f-strings — the formatter defers interpolation to the handler. Include device address `[%s]` prefix when logging device-scoped events (matches existing pattern in `kodi_device.py`). See `STYLE_GUIDE.md` §6.6.

---

## Fork Design Discipline

**Trigger before drafting any patch that touches artwork, UI rendering, PVR/channel handling, or `Features.*`:** name the AP-K* row that applies, OR state explicitly "no AP-K* applies, because…". No silent skips.

| ID    | Sev | Trigger                                                          | Fix ref                                                               |
|-------|-----|------------------------------------------------------------------|------------------------------------------------------------------------|
| AP-K1 | ❌  | Hiding a UI element by removing entity `Features.*`              | UC-Remote-UI `Config.show*`; see Patch 6 → 27 cycle, dropped pre-release toggles in `.2` |
| AP-K2 | ❌  | Mutating artwork-block state without auditing all 3+ guard predicates that gate re-entry | Map gating, walk 2-3 next watchdog ticks; prefer state machine OR transition queue OR eliminate shared state; see Patches 36 → 38 → 42 cycle |
| AP-K3 | ⚠️  | Symptom is rendering (blank/stale image), not data — patching integration before verifying firmware/UI | Required artifacts BEFORE patching: (a) WS capture showing emitted `entity_change` attributes, (b) `GET /api/entities/<id>` showing UC core entity-store state. See Patch 41 post-mortem |
| AP-K4 | ⚠️  | Defaulting a Kodi-shape-dependent config from one PVR/source     | Validate on ≥3 source classes (library, real PVR backend, plugin/addon source) before shipping; see Patches 44 → 44b, xbmc/xbmc#19151 |
| AP-K5 | ℹ️  | Divergent Change Signal: 3+ targeted patches on one subsystem in one release window | Stop. Inventory mutable state + assumed invariants. Refactor (extract module, explicit state machine, etc.) before the 4th patch. See Fowler, *Refactoring*, "Divergent Change" smell; artwork pipeline is the canonical example (Patches 36, 37, 38, 42, 43) |

### Prose

1. **AP-K1 — Don't strip `Features.*` to hide UI.** ucapi feature-set is effectively immutable post-subscribe in the documented protocol (no `features_changed` event in `unfoldedcircle/core-api` AsyncAPI spec). Modern UC firmware (remote-ui v1.4.1+) respects feature checks correctly, so stripping a feature breaks the underlying function (Patch 6 broke Kodi volume control entirely; reverted in Patch 27). UI visibility belongs in remote-ui `Config.show*` — surface UI hiding via firmware, not integration. The same wrong instinct was reached for twice (Patch 6, then dropped `suppress_media_browser`/`suppress_shuffle`/`suppress_repeat` in v1.18.13-madalone.2). See `reference_uc3_ucapi_features.md` and `STYLE_GUIDE.md` §8.1.

2. **AP-K2 — Trace shared mutable state through every gating predicate before patching the artwork pipeline.** `_update_states` artwork block has ≥4 mutable fields (`_thumbnail`, `_media_image_url`, `_media_image_data`, `_artwork_pending_retry`, `_last_item_identity`) and ≥3 guard predicates. When the same flag participates in 3+ guards across async functions, prefer an explicit transition mechanism (state machine, transition queue, OR eliminate the shared state) over scattered booleans. Patch 36 (omit-on-failure) silently broke its own deferred retry because Patch 38's `_thumbnail_real_change` guard already evaluated false on the second pass — Patch 42 had to add a separate `_artwork_pending_retry` flag to fix it. See `feedback_trace_patch_interactions.md`, `project_artwork_dropout_diagnosis.md`, Inngest's "lost updates in asyncio" essay, and `STYLE_GUIDE.md` §7.4.

3. **AP-K3 — Suspect firmware/UI before patching the integration when the symptom is rendering, not data.** Required artifacts before drafting an integration patch for a rendering issue: (a) live `ws://uc3:80/ws` capture showing the `entity_change` attribute the integration is emitting, (b) `GET /api/entities/<entity_id>` confirming UC core's configured-entity store has the populated value. Only if BOTH are correct AND the firmware-side fix is unavailable, write a workaround — and mark it `# Workaround for firmware bug X — remove after vY.Z`. Patch 41 was a UC-Remote-UI delivery-path bug fixed in v1.4.10; the integration patch is now a permanent no-op. Cross-ref Agans, *Debugging: 9 Indispensable Rules* (Rule 3, Rule 6). See `feedback_ws_capture_on_deploy.md` and `STYLE_GUIDE.md` §13.2.

4. **AP-K4 — Don't default a Kodi-data-shape-dependent config from one test target.** Kodi's `Player.GetItem` shape varies across PVR backends (PseudoTV addon vs Kodi PVR client w/ TVHeadend / Movistar+ / etc.), plugin sources (Netflix, YouTube, Movistar+ web), and library content. Documented behavior — xbmc/xbmc#19151 (PVR schema break), #16245 (`InfoVideoTag` inconsistency). Any config default that depends on art-dict shape must be validated against ≥3 source classes (library + real PVR + plugin/addon) before shipping. Patch 44 → 44b inverted in 1 day because PseudoTV and Movistar+ Kodi PVR have inverted `art["icon"]` vs `item['thumbnail']` semantics. See `STYLE_GUIDE.md` §12.2.

5. **AP-K5 — Divergent Change Signal: 3+ targeted patches on one subsystem in one release window = refactor signal.** This is Fowler's *Divergent Change* code smell (a single module accumulating many kinds of changes). Don't ship the 4th patch — stop, inventory mutable state and assumed invariants, propose a structural change (e.g., extract artwork pipeline into its own module with explicit state transitions). The artwork pipeline accumulated 5+ patches in two release windows (36, 37, 38, 42, 43 in `.4`-`.6`; then 44, 44b in `.7`-`.8`); each fixed a real bug, collectively they expose a state machine that isn't right. See [refactoring.guru "Divergent Change"](https://refactoring.guru/smells/divergent-change) and `STYLE_GUIDE.md` §1.6.

---

## Open Items / Pending Work

Snapshot as of 2026-04-29 (post v1.18.13-madalone.8 release).

### Validation pending

- **v1.21.0 merge on device (2026-08-28).** Merge commit `b019648` on `v1.21.0-patched` is built but NOT yet deployed/tagged. Run V0-V11 from `KODI-INTEGRATION-PATCHES.md` "Upstream Merge to v1.21.0" — V5 (poster art for library movies with `video_only_browse_filter` ON) is the only fork-decided behaviour change; V2/V6 confirm the mimetype gate. Re-check xbmc/xbmc#28244 when Kodi 22 RC lands (stacked paths, `episodes://` pseudo-dirs, long SMB paths vs `MAX_MEDIA_ID_LEN`).
- **Patch 44b on diverse PVR sources.** Verified working on PseudoTV (`plugin.video.pseudotv.live`) and Movistar+ Kodi PVR client. Other PVR backends — TVHeadend, MythTV, IPTV Simple Client, Pluto.tv addon, etc. — have not been live-tested. They may report `_item['type']='channel'` with a different art-dict shape; if a user reports "channel logo missing on X PVR backend" the diagnostic chain is documented in `.claude-memory/project_pseudotv_logo_diagnosis.md` (Logdy WS capture → `Player.GetItem` direct probe → compare art-dict shape).
- **madalone.7 → .8 migration**. Devices that completed setup on `.7` have `artwork_type_channels="thumbnail"` persisted in stored config. The dataclass MISSING-default loop only fills *absent* fields — won't migrate existing values. Users must reconfigure (open setup → save) OR manually delete the line from `/data/<intg-uuid>/config.json` to pick up the `.8` default. Could be auto-migrated in a future patch but flagged as low-priority since it's a 1-day-old default.

### Upstream PR work (Phase 0 triage complete)

`PHASE0-UPSTREAM-PR-TRIAGE.md` is the authoritative source. Summary:

- **Ready to send (mechanical rebase, NONE/LOW conflict):** PRs 1, 2, 3, 4, 7 covering Tiers A (8 patches), B (6), G-subset (3), C (4), F-subset (5+26).
- **Rebase work (MEDIUM/HIGH conflict):** PRs 5 (Tier D incl. patch 30 sidecar), 6 (Tier E artwork download hardening), 8 (patch 25 video_only_browse_filter rework).
- **Held pending maintainer input:** Tier H simple commands (5 patches, blocked on upstream's planned `MODE_*` rename).
- **Skip:** patches 6, 27, 41 — non-load-bearing on modern firmware.
- **NEW (this session):** Patch 44 added to Tier D queue. Default value MUST be `"icon"` (per `.8`), not `"thumbnail"` (was `.7`'s wrong default).

Pre-PR-1 actions tracked in `PHASE0-UPSTREAM-PR-TRIAGE.md` "Pre-PR-1 actions" section.

### Other quality items

- **`test_driver.py` has zero coverage** for the artwork-type branch in `kodi_device.py:1209-1245`. Adding tests is out of fork scope per existing convention (none of patches 36-44 added tests) but should be in any upstream PR.
- **x86_64 build matrix is disabled.** `.github/workflows/build.yml` has the `x86_64` branch (`if: matrix.platform == 'x86_64'`) but the matrix config only lists `aarch64`. Re-enable if a use case for x86_64 builds appears (e.g. a contributor running the integration in a non-UC3 environment).
- **No automated migration script** for stored device configs across major fork bumps. Each new field relies on `__post_init__` MISSING-default. If a future patch needs to *change* an existing field's value (vs add a new one), we'd need an explicit migration step in `KodiConfigDevice.__post_init__` keyed on a version string.

### Future upstream issues to file

`PHASE0-UPSTREAM-PR-TRIAGE.md` "Future upstream issues to file" section tracks pre-existing upstream behaviors flagged during fork debugging that aren't fixed here (e.g., no-players branch dirty-checking).

---

## Troubleshooting Notes

### `CONNECTION_REFUSED` at end of setup wizard is ambiguous

When the integration setup wizard reports `CONNECTION_REFUSED` at the final "test connection" step (after Kodi credentials are entered), the error can mean any of three different failures. **Diagnose in this order before chasing build/binary issues:**

1. **Hostname / mDNS resolution failure (most common).** The user typed `<host>.local` (or any DNS name) and the resolver couldn't find it. Symptom: identical to a driver crash. **First diagnostic: have the user re-run setup with the IP address instead of the hostname.** If that works, the integration is fine; the issue is mDNS / Avahi / DNS on their network. Fix is on the user side: DHCP reservation + router DNS entry, restart the Kodi host's `avahi-daemon`, or just keep using the IP.
2. **Integration → Kodi network reachability.** Even with IP, the UC3 might not reach the Kodi host (different VLAN, firewall blocking 8080/9090, Kodi's HTTP control disabled). Test: `curl http://<kodi-ip>:8080/jsonrpc -u user:pass` from any machine on the same network as the UC3.
3. **Integration driver process actually crashed.** Only suspect this if (1) and (2) are ruled out. Check integration logs at `http://<uc3-ip>:8088/api/integration-logs/entries?service=core` (filter for `kodi_driver` lines around the install/setup time). Look for ImportError / ModuleNotFoundError → missing-deps build issue (CLAUDE.md Build & Deploy "Must run pip install before PyInstaller" rule). Look for tracebacks on startup → import-time error in our code.

The 2026-05-02 session burned ~1 hour chasing a missing-deps hypothesis when the actual issue was mDNS resolution to `madteevee.local` after the host had been up too long without re-broadcasting. The IP worked immediately. Don't repeat — IP-vs-hostname is the cheapest first test.

---

## AUDITING CODEBASE

When the user asks to audit the codebase, run a structured pass:

1. **Read full codebase** — `src/*.py` only (skip `pykodi/` — vendored).
2. **Run industry checks:**
   - **Lint:** pylint, flake8 — surface unfixed warnings.
   - **Type check:** mypy `--strict` against `src/` — flag any `Any` leakage.
   - **Security:** bandit `-r src/` — flag any unfixed findings.
   - **Async correctness:** scan for AP-K2 violations (multi-guard mutable state), `asyncio.create_task` without `add_done_callback`, missing `CancelledError` handling.
   - **ucapi correctness:** scan for AP-K1 violations (Features-stripping toggles), AP-K3 patterns (rendering workarounds without firmware-side check).
3. **Grade as a pro dev would.** No glazing. Brutally honest.
4. **Output:** structured report with severity (❌/⚠️/ℹ️), file:line citations, and concrete remediation suggestions. Tier as quick-pass (default) or deep-pass (full sweep across all files).

See `STYLE_GUIDE.md` §10 for full audit checklist.