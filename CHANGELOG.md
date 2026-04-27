# Kodi integration for Remote Two / Remote 3 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-patch implementation notes for the madalone fork live in [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md).

---

## Fork (madalone)

### v1.18.13-madalone.5 — 2026-04-27

> **Post-mortem note (added 2026-04-27, after firmware v1.4.10 release):** the user-visible "blank artwork on first card open after integration reinstall" symptom that motivated this hotfix turned out to be a firmware-side bug on UC-Remote-UI commit `1266974` (and pre-v1.4.10), fixed in **UC-Remote-UI v1.4.10** by reconnecting an orphan `entityAdded` core-API signal in `entityController.cpp`, replacing a silent early-return on unknown-entity CHANGE with a `load()` fallback, and adding a missing `entityLoaded` listener to `MediaComponent.qml`. Integration emit pipeline was correct end-to-end (verified via wire capture + UC core API). Patch 41 in this release is now strictly redundant on v1.4.10 firmware but is retained as harmless belt-and-braces for users on older firmware. Patch 42 fixes a real integration-side bug (deferred-retry was self-skipping) and remains load-bearing on any firmware. See `KODI-INTEGRATION-PATCHES.md` patches 41/42 for the original problem statements; the post-mortem section there for the actual root cause.

**Hotfix on top of madalone.4: artwork blank on first activity-card open after reinstall (patches 41–42).**

User reported the symptom persisted after deploying madalone.4. Live websocket capture against the UC3 (`/ws` Core API, subscribed to channel `all`) showed steady-state behavior was clean — every entity_change emitted by the integration during 90s of playback was either `media_title` (re-flush) or `media_position` (rolling). `media_image_url` was never re-emitted at steady state, which is the correct patch-36 omit-on-no-change behavior.

The narrowed reinstall trigger pointed at the subscribe-during-initial-connect race that I dismissed too quickly when writing the original plan: after reinstall, the integration's first `_update_states()` is in flight (worst case ~38s with patch 37's retry budget), and `on_subscribe_entities` runs synchronously against `device.attributes`, which reads `_media_image_data=""` (initial state) and ships `MEDIA_IMAGE_URL=""` to the remote. The eventual `Events.UPDATE` from the first poll *should* propagate via `on_device_update`, but the timing-sensitive corner case left the new subscriber's view stuck on the empty value until close+reopen.

While tracing also found a self-defeating bug in patch 36's deferred-retry path: the +4s deferred `_update_states()` task on artwork-fetch-failure was skipping the artwork block entirely on re-entry because `self._thumbnail` had already been mutated by the failed attempt — so `_thumbnail_real_change` evaluated False and the retry never actually retried.

- **Added** `_post_subscribe_refresh` async helper in `src/driver.py` (patch 41). On every media_player subscribe, schedules a one-shot listener for the device's next `Events.UPDATE` (via `pyee` `events.once` + `asyncio.Future` + 30s timeout), then re-pushes `filter_attributes(device.attributes, ucapi.media_player.Attributes)` so the new subscriber's view is overwritten with the fresh snapshot. Belt-and-braces: the existing `on_device_update` path remains the canonical propagator.
- **Fixed** the deferred-retry bug (patch 42). Added `_artwork_pending_retry` flag in `KodiDevice.__init__`. The artwork block in `_update_states()` is now entered when `(_thumbnail_real_change OR (download_artwork AND _media_image_url AND _artwork_pending_retry))`. Flag set on `_fetch_artwork_with_retry` returning None, cleared on success or genuine no-art state. Both the existing +4s deferred re-poll AND the natural watchdog cadence (~10s ±25%) now drive recovery — a permanently-broken URL still bounds at the same retry budget as patch 37 (3 inline + 1 deferred = 4 attempts before stable failure), but a transient outage on the *first* poll after reinstall now recovers automatically.

**Breaking changes flagged:** none observable. Both patches are additive: patch 41 only schedules a follow-up task, patch 42 widens an entry condition without altering the success/failure outcomes.

### v1.18.13-madalone.4 — 2026-04-27

**Thumbnail retention & display fixes for `download_artwork=true` mode (patches 36–40).**

Diagnosed against UC Remote 3 firmware `0.38.4-32-g1266974` (pre-v1.4.9), which has zero retry resilience for the base64 (`download_artwork=true`) path — only the URL-fetch path gets the firmware's 3×15s retry budget. The integration must be the resilience layer for download-mode users until v1.4.9 firmware lands. Architecturally, the prior code emitted `MEDIA_IMAGE_URL=""` on transient fetch failures, which actively destroys the previous-value retention that ucapi's partial-update protocol provides for free.

- **Fixed** sticky thumbnail blanking after a single transient fetch failure (patch 36) — emit-on-failure changed to omit-on-failure. ucapi treats absent attributes as "no change," so prior good URL is retained on the remote until a successful fetch overwrites it. Removes destructive `MEDIA_IMAGE_URL=""` emissions on the failure path.
- **Added** exponential-backoff retry budget on the artwork download (patch 37) — 3 attempts at 0/0.5/1.5s ±20% jitter, each subject to the per-device timeout. Replaces the prior single-attempt fetch with a budget that survives transient Kodi webserver hiccups, network blips, and brief 5xx storms. On exhaustion, schedules a deferred re-poll at +4s (mirrors the existing `changed_media+empty` retry pattern).
- **Fixed** thumbnail flicker on PVR / plugin sources (patch 38) — item-identity guard distinguishes a real media change from Kodi briefly returning `art={}` for the same item. Prior code path nuked `_media_image_data` on every poll where `thumbnail` flipped to `None`; now the previous value is retained unless the playing item's `(id, file)` actually changed.
- **Fixed** `data:application/octet-stream;base64,…` data URIs being silently rejected by the UC3 firmware's QML `Image` element (patch 39) — magic-byte sniff now declares the correct `image/jpeg` / `image/png` / `image/webp` / `image/gif` MIME on the data URI. Kodi omits the `Content-Type` header on thumbnail responses, so aiohttp's `response.content_type` defaulted to `application/octet-stream` — a MIME Qt's QML data-URI loader rejects regardless of the actual byte content. Defaults to `image/jpeg` for unknown bytes (Qt is forgiving of declared-MIME mismatch but rejects unknown declared types outright).
- **Added** shared `aiohttp.ClientSession` for artwork downloads, lifecycle-tied to the Kodi connection (patch 40). Replaces per-fetch `ClientSession()` construction (TLS/connect overhead, no pooling) with the official aiohttp guidance of one session per app/device. Closed cleanly in `_clear_connection()`.
- **Added** per-device `artwork_timeout_seconds` configuration (patch 40) — exposed in the setup flow as a number field (range 5–60, default 12). Replaces hardcoded `ARTWORK_TIMEOUT = 5.0` which was tight on slow Kodi instances. Backward-compatible: configs without the field automatically receive the default via `KodiConfigDevice.__post_init__` MISSING-default coercion.
- **Changed** `UPDATE_LOCK_TIMEOUT` 10s → 30s — sized to accommodate the worst-case retry budget (~38s = 3 × 12s timeout + 2s backoff) without abandoning legitimate just-slow Kodi instances.
- **Removed** `_reset_media_artwork()` method and its single caller — the prior workaround for "same media replayed shows same art" emitted the *current* `media_artwork` value (a no-op given ucapi's deduplication). The underlying remote bug it papered over was firmware-side and fixed long ago. Patches 36/38 make the workaround both unnecessary and harmful (it would re-emit on transient empty), so the entire block is gone.

**Breaking changes (all LOW risk, all backward-compatible upgrades from v1.18.13-madalone.3):**
- Integration no longer emits empty-string `MEDIA_IMAGE_URL` on transient fetch failure — remote retains prior URL/data instead of blanking. Genuine no-art states (on_stop, no media playing, no `_media_image_url`) still emit `""` as before.
- Data URIs now declared with the correct image MIME instead of `application/octet-stream`. Images that previously failed to render now render.
- Transient `art={}` from Kodi mid-playback no longer blanks artwork. Real media changes (item id/file shift) still flow through unchanged.
- `ARTWORK_TIMEOUT` and `UPDATE_LOCK_TIMEOUT` raised. Longer max lock-hold; existing watchdog log line at the timeout still warns on genuinely-stuck polls.
- New `artwork_timeout_seconds` field in setup. Additive; no existing field changed.
- Shared `ClientSession` lifecycle tied to device connect/disconnect; closed defensively to avoid leaks.

### v1.18.13-madalone.3 — 2026-04-24

**Seven new bindable simple commands for the UC3 Remote entity + GitHub Actions workflow fixes.**

- **Added** `MODE_CONTEXT_MENU` (patch 31) — unconditional `Input.ContextMenu` on any bindable button.
- **Added** `MODE_PLAY_SELECTED` (patch 32) — context-sensitive Kodi `play` action; plays whatever folder/item is currently focused.
- **Added** `MODE_KEYPRESS_C` (patch 33) — simulates keyboard `c` keypress via `Input.ButtonEvent`, routed through Kodi's keymap hierarchy. Gives Harmony-style per-window behavior: `contextmenu` globally, `queue` in `<FullscreenVideo>`, respects user keymap overrides.
- **Added** `MODE_CODEC_INFO` / `MODE_PLAYER_DEBUG` / `MODE_SYSTEM_MENU` (patch 34) — `codecinfo` overlay / player debug overlay / shutdown menu window.
- **Added** `MODE_KEYPRESS_ESC` (patch 35) — simulates keyboard Esc via `Input.ButtonEvent`. Context-aware "Exit" behavior: close dialog / previous menu / stop playback / shutdown menu depending on focused window.
- **Fixed** `Build & Release` workflow — removed the Docker Hub publish job (fork has no DockerHub credentials / namespace) and added `permissions: contents: write` so the GitHub Release job can publish the tar.gz artifact on tag push.

### v1.18.13-madalone.2 — 2026-04-24

**MediaBrowser artwork handling + two new per-device UX toggles.**

- **Added** `video_only_browse_filter` per-device toggle (patch 25) — hides music and pictures browse categories, strips `.nfo`/`.srt`/`.sub` companion files from source-directory listings.
- **Added** `suppress_unsupported_command_errors` per-device toggle (patch 26) — swallows Kodi-side JSON-RPC `ProtocolError` (e.g. Pause on a PVR channel) so they stop red-triangling on the UC3. Transport / timeout errors still surface as before.
- **Deprecated** `suppress_volume_overlay` (patch 27) — the original feature-removal approach (patch 6) broke Kodi volume control entirely after UC Remote 3 FW v1.4.1 started respecting feature-set removals. Volume features are always advertised now; OSD hiding moved to UC Remote 3 **Settings → UI → Show volume indicator** (FW v1.4.2+). Config key retained for backward compat; one-time WARNING logged per device if set.
- **Fixed** Netflix / plugin thumbnails not rendering on the player widget — broadened the artwork fallback chain to walk `poster → thumb → landscape → banner → fanart → clearart → icon` when the configured `artwork_type` yields nothing (patch 28).
- **Fixed** broken/placeholder artwork on the UC3 — filters out Kodi's internal `image://Default*.png` placeholders from the art resolution path, validates HTTP 200 before base64-encoding in the `download_artwork` path (patch 29).
- **Fixed** UC3 MediaBrowser-initiated playback showing no thumbnail when Kodi's own UI showed one — integration now detects Sonarr/Radarr-style `<basename>-thumb.jpg` sidecars, Kodi-native `.tbn` files, and folder-level `poster.jpg`/`folder.jpg`/`banner.jpg` at both browse time (free — scans the existing `Files.GetDirectory` response) and play time (one extra round-trip when primary art chain produces nothing) (patch 30).
- **Not included — drafted and pulled pre-release:** `suppress_media_browser`, `suppress_shuffle`, `suppress_repeat`. Integration-side feature removal proved unable to propagate to already-subscribed UC3 entities. UX for those toggles moved to the UC Remote 3 firmware (`Config.showMediaBrowserButton` / `showShuffleButton` / `showRepeatButton` in v1.4.2+). The three `KodiConfigDevice` fields are retained as silent no-ops for backwards compat with pre-release `config.json` entries.

### v1.18.13-madalone.1 — 2026-04-22

Rebase onto upstream `v1.18.13` (from `v1.18.7-patched`). Adopts upstream's `ucapi~=0.6.0` dependency set; drops the local `ucapi-0.5.3.dev…` wheel. Picks up upstream search-media fixes and category refactor. 18-patch chain on top of upstream.

### v1.18.7-madalone.1 through v1.18.7-madalone.12

Initial fork on upstream `v1.18.7`. Added 24 targeted patches covering title formatting, artwork (connect-time re-poll, stop-handler cleanup, subscribe-path fix, SMB handling), power-off control, volume-overlay suppression (later deprecated), `eval()` security fix, command-sequence `await` correctness, media-position fix, dead-code + dependency cleanup, exception-handling hardening, async-lock race fix, task observability, sensor-state bug, `custom_command` parse-error handling, config validation, select-widget robustness (four rounds), Kodi-version compat for `Player.GetChapters`, stream-event bundling fix, and periodic state-refresh safety net. See `KODI-INTEGRATION-PATCHES.md` for per-patch implementation notes (patches 1–24).

---

## Upstream

The sections below are inherited from upstream's `CHANGELOG.md` at the time of forking and are not maintained here.

## Unreleased (upstream)

- Rename the predefined simple commands to match [expected UC name patterns](https://github.com/unfoldedcircle/core-api/blob/main/doc/entities/entity_media_player.md#command-name-patterns)
- Brings support for the different keymaps (e.g by bringing a separator in the command name to set the keymap name)

## v1.0.2 - 2024-04-25
### Added remote entity and default mapping
- New remote entity (firmware >= 1.7.10) with support for custom commands and command sequences with repeat, delay, holding time
- Default buttons mapping when raising entity page
- Default interface mapping when raising entity page

## v1.0.0 - 2024-03-16
### Initial release
