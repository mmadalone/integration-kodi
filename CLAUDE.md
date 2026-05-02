# CLAUDE.md -- Kodi Integration for UC Remote 3 (Patched Fork)

DON'T BE SYCOPHANTIC

## Project Identity

Patched fork of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (v1.20.0) for the **Unfolded Circle Remote 3**. Python 3.11 async integration driver using the `ucapi` library.

**Owner:** madalone
**Device:** UC Remote 3 at `192.168.2.204`, PIN `6984`
**Upstream:** `albaintor/integration-kodi` tag `v1.20.0` (commit `d3ec217`, merged 2026-05-02)
**Current tag:** `v1.20.0-madalone.1` (branch `v1.20.0-patched`)
**Language:** Python 3.11 (async/await, `ucapi` 0.6.0, `aiohttp`, Kodi JSON-RPC)
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

make sure the plan follows c++/python/ucapi/uc3 best practices and consult official c++/python/ucapi/uc3 docs and community forums online for true & tried solutions with reported success. IMPORTANT: NO HACKY SOLUTIONS! do not break logic, only improve upon it and flag code breaking changes in the plan. do thorough research and codebase check (to avoid dupes and propose arch improvements), ask me anything that's unclear before presenting plan.

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

---

## Current Patches

All patches documented in detail in `KODI-INTEGRATION-PATCHES.md` (that file is the source of truth). Summary below (44 patches as of `v1.20.0-madalone.1`; v1.20.0 merge documented in the "Upstream Merge to v1.20.0" section of the same doc):

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
| 27 | Deprecate `suppress_volume_overlay` | Feature-removal reverted; OSD hiding moves to UC3 FW `Config.showVolumeOverlay` (v1.4.2+); WARNING logged if flag still True |
| 28 | Broader artwork fallback chain | poster/thumb/landscape/banner/fanart/clearart/icon walk when primary `artwork_type` yields nothing |
| 29 | Placeholder filter + HTTP status validation | Drops `image://Default*.png`; validates HTTP 200 before base64 encode (do **not** filter on Content-Type — Kodi omits the header) |
| 30 | Sidecar thumbnail detection | Sonarr `<base>-thumb.jpg`, Kodi `.tbn`, folder-level `poster.jpg` resolved at browse-time (free) + play-time (1 Files.GetDirectory) |
| 31 | `MODE_CONTEXT_MENU` simple command | `Input.ContextMenu` (always, bypass keymap) — raw context menu on any button |
| 32 | `MODE_PLAY_SELECTED` simple command | Kodi `play` action — context-sensitive play (plays focused folder/item) |
| 33 | `MODE_KEYPRESS_C` simple command | `Input.ButtonEvent(c, KB)` — routes through Kodi keymap (Harmony MENU parity: `contextmenu` globally, `queue` in `<FullscreenVideo>`) |
| 34 | `MODE_CODEC_INFO` / `MODE_PLAYER_DEBUG` / `MODE_SYSTEM_MENU` simple commands | `codecinfo` / `playerdebug` / `GUI.ActivateWindow(shutdownmenu)` |
| 35 | `MODE_KEYPRESS_ESC` simple command | `Input.ButtonEvent(escape, KB)` — routes through Kodi keymap (Esc-key behavior: close dialog / previous menu / stop / shutdown menu per window context) |
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

Patch 6 (original) removed `Features.VOLUME` / `VOLUME_UP_DOWN` / `MUTE*` + suppressed `MediaAttr.VOLUME`/`MUTED` emission to hide the UC3 volume overlay. Patch 27 (v1.18.13-madalone.2) reverts both — the approach broke Kodi volume control entirely post remote-ui v1.4.1 (which correctly respects feature removals). Volume features are now always advertised; OSD visibility is owned by UC Remote 3 firmware v1.4.2+ via `Config.showVolumeOverlay`. The config key is retained for backcompat; a one-time WARNING is logged per device if set to `True`. Patch 6's correctness fix to `on_volume_changed` (int-comparison) is retained.

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
- `ucapi` -- UC integration API (local wheel: `src/ucapi-*.whl`)
- `jsonrpc-async` / `jsonrpc-websocket` -- Kodi JSON-RPC communication
- `aiohttp` -- async HTTP
- `zeroconf` -- mDNS discovery
- `pyee` -- event emitter

---

## Companion Firmware Fixes

Documented in `KODI-INTEGRATION-PATCHES.md` under "Companion Firmware Fixes". These live in the separate [UC-Remote-UI project](../UC-Remote-UI/) (sibling directory on Windows: `C:\Users\mique\_Claude Projects\UC-Remote-UI\`), not here:
- C++ duplicate URL gate in `mediaPlayer.cpp`
- QML image loader guard in `ImageLoader.qml`

---

## Mandatory Rules

1. **Read `KODI-INTEGRATION-PATCHES.md` before modifying patched code.** Each patch documents the problem, solution, and reasoning.

2. **Don't modify upstream logic.** Patches are targeted additions. Don't refactor surrounding upstream code -- it complicates future merges.

3. **Follow the config pattern.** New options need 5 touch points: `config.py` field, `setup_fields.py` checkbox/dropdown, `setup_flow.py` (initial parse + device creation + reconfig parse + reconfig assign + reconfig pre-populate).

4. **Test on device.** macOS/Docker builds verify syntax and packaging but NOT runtime behavior. Always deploy to the UC Remote and verify.

5. **Version the tar.gz.** Output file: `kodi-integration-v<VERSION>.tar.gz` in the project directory. Version in `driver.json` field `version`.

6. **`pip install` before PyInstaller.** See Build section. Omitting this produces a binary that starts but immediately crashes.

---

## Open Items / Pending Work

Snapshot as of 2026-04-29 (post v1.18.13-madalone.8 release).

### Validation pending

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

## AUDITING CODEBASE

When user asks to audit codebase, read full codebase, and throw all industry tests at it. grade it as a pro dev would. IMPORTANT: no glazing, be brutally honest.