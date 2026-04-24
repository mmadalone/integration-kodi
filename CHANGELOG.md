# Kodi integration for Remote Two / Remote 3 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-patch implementation notes for the madalone fork live in [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md).

---

## Fork (madalone)

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
