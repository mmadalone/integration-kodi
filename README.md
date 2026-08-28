# Kodi Integration for Unfolded Circle Remote 3 (Patched Fork)

Fork of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (currently rebased onto **v1.21.0**) with bug fixes for title formatting, artwork loading, playback state, and power-off control, plus additional setup-flow toggles and simple commands.

All upstream features (including the v1.20.0 PVR/Addons browsing + Favourites support, the v1.20.1 livetv/favourites improvements, the v1.20.2 Kodi-credential URL-encoding fix and the v1.21.0 browse-artwork groundwork — the latter only lights up on Kodi 22 once xbmc/xbmc#28244 ships) are inherited as-is. All credit for the integration itself goes to [Albaintor](https://github.com/albaintor). This fork applies targeted patches only — no upstream logic has been altered.

Requires remote firmware `>= 1.7.10`.

**Current build:** `v1.21.0-madalone.1` (2026-08-28, on-device validation pending; last validated release `v1.20.2-madalone.1`, 2026-07-24). See [`CHANGELOG.md`](CHANGELOG.md) for release history and [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md) for per-patch implementation notes.

## Patches

### 1. Kodi Label Formatting Tag Stripping

Kodi uses BBCode-style markup tags (`[COLOR tomato]`, `[B]`, `[I]`, `[CR]`, etc.) in media titles, especially from PVR/IPTV EPG data and addon-sourced content. The upstream integration passes these through verbatim, resulting in raw tags displayed on the remote.

This patch strips all [Kodi label formatting](https://kodi.wiki/view/Label_Formatting) tags from media titles before they reach the UC3 display. The regex covers the full spec: `[COLOR name/hex]`, `[/COLOR]`, `[B]`, `[I]`, `[LIGHT]`, `[UPPERCASE]`, `[LOWERCASE]`, `[CAPITALIZE]`, and `[CR]`.

**Before:** `[COLOR tomato]Breaking News[/COLOR] - Local weather update`
**After:** `Breaking News - Local weather update`

### 2. Deferred Artwork Re-poll on Connect

When opening the Kodi integration while media is already playing, the integration polls Kodi for the current state once on connect. If artwork metadata isn't available yet (common with already-playing sessions), there's only a single retry at +4 seconds — and only under specific conditions.

This patch adds a deferred re-poll 3 seconds after the initial connection, using the same `asyncio.create_task` pattern already in the codebase. This gives artwork a second chance to load, and if it's still empty, the existing +4s retry logic chains for a third attempt at ~7 seconds total.

### 3. Stop Handler Clears Stale Media Info

The upstream `on_stop` handler emits only a state change when playback stops. Title, artwork, progress bar, and artist info remain on screen showing the previously playing media.

This patch clears all media attributes (title, artist, album, artwork, position, duration) on stop and emits them in a single update. The UC3 display now properly clears when playback ends.

### 4. Artwork on First Entity Open (Subscribe Fix)

The upstream integration uses two different code paths for sending artwork:
- **Real-time updates** (`_update_states`): sends via `media_artwork` — respects `download_artwork` config, returns base64 data when enabled
- **Entity subscribe** (`attributes` property): sends via `media_image_url` — always returns the raw Kodi HTTP proxy URL, ignoring `download_artwork`

This mismatch means artwork fails to load on first entity open (the UC3 tries to download from Kodi's HTTP proxy and fails or takes too long), but works on subsequent opens when cached from a real-time update.

This patch makes the `attributes` property use `media_artwork` consistently, matching the real-time update path. With `download_artwork` enabled, artwork loads instantly on first open from the integration's pre-cached base64 data.

### 5. "None" Power Off Command Option

Adds a "None (disabled)" option to the Power off command dropdown in integration settings. When selected, the power-off button does nothing — prevents accidental shutdown/hibernate of the Kodi host.

### 6. Suppress Volume Overlay

Opt-in config option that hides the remote's volume overlay popup when changing Kodi volume. The TV already shows Kodi's native OSD — the remote overlay is redundant. Enable "Suppress volume overlay" in integration settings. Also fixes an upstream bug where WebSocket volume events never propagated.

### 7. Security: eval() → ast.literal_eval()

The upstream `custom_command()` method used `eval()` to parse command parameters — a remote code execution risk. Replaced with safe `ast.literal_eval()` after PID variable substitution.

### 8. Missing await in Remote Command Sequences

The remote entity's command sequence handler was missing `await` on `mediaplayer_command()`, causing all commands in a sequence to fire simultaneously instead of sequentially.

### 9. Media Position Elapsed Time Fix

Upstream used `timedelta.seconds` (0–59 range) instead of `timedelta.total_seconds()` to calculate elapsed playback time. Media position reporting was wrong after 1 minute without a Kodi position update.

### 10. Dead Code & Dependency Cleanup

Removed unused `_buffered_callbacks` dead code, credentials from debug logs, unused `httpx`/`defusedxml` dependencies, and pinned loose jsonrpc dependency versions.

### 11. Exception Handling Hardening

Narrowed 6 dangerous `except Exception: pass` blocks to specific exception types (`OSError`, `TransportError`, `ProtocolError`). Unexpected exceptions now propagate instead of being silently swallowed.

### 12. Async Lock Race Condition Fix

Replaced the upstream `_update_lock` timeout mechanism (check-release-acquire, not atomic) with `asyncio.wait_for()` + `try/finally`. Eliminates a race condition that could corrupt shared state under concurrent load.

### 13. Fire-and-Forget Task Observability

Added error-logging callbacks to 11 `create_task()` calls that previously lost exceptions silently. No behavior change — just makes failures visible in logs.

### 14. Sensor State Bug Fix

Fixed `raise self._state` → `return self._state` in the sensor base class `state` property.

### 15–24. Post-`.4` hardening (v1.18.7-madalone.5 through .12)

Patches 15–24 covered a series of stability fixes landed between the initial `.4` release and the `v1.18.13` rebase. Each is documented individually in [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md):

- **15:** `custom_command` returns `BAD_REQUEST` on parse failure instead of silently falling through.
- **16:** Second audit pass narrowing the remaining 16 bare `except Exception:` blocks.
- **17:** Watchdog reconnect delay jitter (±25%) so a fleet of remotes doesn't hammer Kodi in lock-step after a network blip.
- **18:** `KodiConfigDevice.__post_init__` validates types (bool/int coercion, port range, non-empty identity fields).
- **19–21:** Select (audio/subtitle) widget fixes — empty options on subscribe, full-snapshot push on track change, gate `OPTIONS` push on actual list change to dodge a Qt `ListView.model` reset in `Select.qml`.
- **22:** Widen chapter-fetch `except` for Kodi <22 compatibility (`Player.GetChapters` is Kodi 22+).
- **23:** `on_property_changed` uses `any()` instead of `all()` so bundled stream events aren't dropped.
- **24:** Watchdog periodic state-refresh safety net — un-announced state changes now surface within ~12s instead of never.

### v1.18.13-madalone.2 (MediaBrowser artwork handling + new toggles)

Six patches focused on making UC3 MediaBrowser-initiated playback behave like Kodi-UI-initiated playback for artwork, plus two new per-device UX toggles:

- **25.** `video_only_browse_filter` (per-device toggle) — hides music and picture browse categories, strips `.nfo`/`.srt`/`.sub`/`.idx`/`.ass`/`.smi`/`.ssa`/`.sup`/`.vtt` companion files from source-directory listings.
- **26.** `suppress_unsupported_command_errors` (per-device toggle) — swallows Kodi JSON-RPC `ProtocolError` (e.g. pressing Pause on a PVR channel) so they stop surfacing as red-triangle notifications on the UC3. `TransportError` / `ServerTimeoutError` still surface so genuine connectivity issues still alert.
- **27.** Deprecated **`suppress_volume_overlay`** — the original patch-6 feature-removal approach broke Kodi volume control entirely post UC Remote 3 FW v1.4.1 (which correctly respects feature set). Volume features are now always advertised. The toggle has no functional replacement on vanilla UC firmware — OSD hiding requires running the private `Madalones-Defolded-Circle-3` firmware fork (which adds `Config.showVolumeOverlay`, surfaced as **Settings → UI → Show volume indicator**); on stock UC firmware the volume OSD always appears on volume change. Config key retained for backcompat; one-time WARNING logged per device if flag is still set to `True`.
- **28.** Broader artwork fallback chain — when the configured `artwork_type` returns nothing, walks `poster → thumb → landscape → banner → fanart → clearart → icon`. Recovers Netflix-style plugins that expose real thumbnails only under `art["icon"]`.
- **29.** Kodi placeholder filter + HTTP status validation — `image://Default*.png` (Kodi's internal placeholders like `DefaultVideo.png`) are now filtered from any resolution path. When `download_artwork` is enabled, the fetch validates HTTP status 200 before base64-encoding. Content-Type is **not** checked because Kodi omits that header for thumbnails.
- **30.** Sidecar thumbnail detection — at both browse time and play time, the integration recognizes Sonarr/Radarr `<basename>-thumb.jpg` / `-poster.jpg` / `-landscape.jpg`, Kodi-native `.tbn`, and folder-level `poster.jpg` / `folder.jpg` / `banner.jpg` / `cover.jpg`. Browse-time detection is free (reuses the existing `Files.GetDirectory` response); play-time detection adds one extra round-trip only when the primary art chain produced nothing. Since v1.21.0 the browse-time chain is sidecar → Kodi `art` dict → Kodi thumbnail → derive-from-file (image files only).

**Dropped pre-release:** `suppress_media_browser`, `suppress_shuffle`, `suppress_repeat` were drafted and then pulled after diagnosis showed integration-side feature removal doesn't propagate to already-subscribed UC3 entities. The UX for hiding those icons lives at the UC Remote 3 firmware layer instead (`Config.showMediaBrowserButton` / `showShuffleButton` / `showRepeatButton` in v1.4.2+). The three dataclass fields are retained in `KodiConfigDevice` as silent no-ops for backwards compat with pre-release `config.json` entries.

### v1.18.13-madalone.3 (seven new simple commands)

Seven new bindable entries in the UC3 Remote entity's simple-command picker — map each to any button via UC3's per-button mapping:

- **`MODE_CONTEXT_MENU`** (patch 31) — unconditional `Input.ContextMenu` (always opens the context menu, bypass Kodi keymap).
- **`MODE_PLAY_SELECTED`** (patch 32) — Kodi's context-sensitive `play` action. Plays the currently focused folder/item in the Kodi UI (matches Harmony PLAY button behavior).
- **`MODE_CODEC_INFO`** (patch 34) — toggles the codec-info overlay during playback.
- **`MODE_PLAYER_DEBUG`** (patch 34) — toggles the player debug overlay (CPU/GPU/FPS/dropped frames).
- **`MODE_SYSTEM_MENU`** (patch 34) — opens Kodi's shutdown menu (Exit / Power off / Reboot / Hibernate / Suspend / Custom shutdown timer / Minimize / Inhibit idle shutdown).

**Retired in v1.20.1-madalone.2** — `MODE_KEYPRESS_C` (patch 33), `MODE_KEYPRESS_ESC` (patch 35), and `MODE_TVGUIDE` (patch 45). All three were thin aliases for `Input.ButtonEvent(button=X, keymap="KB")` — equivalent to the existing custom-command `"key X"` syntax (see "Custom-command syntax" below). Removed to keep the simple-commands list focused.

### Custom-command syntax

The Remote entity's "Send command" action (and the media-player entity's `custom_command`) accept a few prefix forms beyond the named simple commands. Type any of these in the activity-button "Command" field:

- **`key <button> [<keymap>] [<holdtime>]`** — fires `Input.ButtonEvent`. Examples: `key c` (keyboard `c`), `key escape` (Esc), `key r` (replaces retired `MODE_TVGUIDE` for Harmony users with `<key id="61522">` mapped to `activatewindow(tvguide)`), `key f1 KB 500` (F1 with 500ms hold), `key guide R1` (Guide button on remote keymap).
- **`action <name>`** — fires `Input.ExecuteAction(name)`. Examples: `action codecinfo`, `action playerdebug`, `action queue`.
- **`activatewindow <window>`** — fires `GUI.ActivateWindow(window)`. Examples: `activatewindow tvguide`, `activatewindow shutdownmenu`, `activatewindow settings`.
- **`viewmode <mode>` / `zoom <in|out|N>` / `speed <increment|decrement|N>` / `audiodelay <float>` / `stereoscopimode <mode>`** — Kodi-specific actions with one parameter.

Any other command falls through to a raw Kodi JSON-RPC method call (the first token is the method name, optional second token a Python-literal dict of params).

Underlying mechanism distinction (relevant when picking between named simple commands and `custom_command` syntax):
- `Input.ExecuteAction(...)` — direct named action, bypass keymap.
- `Input.ButtonEvent(...)` — simulate a key/button press, route through `keymap.xml`, respect per-window overrides. Use this (via `key <X>`) when you want physical-keyboard parity with a setup (e.g. Harmony remote configurations).

Also in this release:
- **`build.yml` workflow fixes** — removed the upstream Docker Hub publish job (fork has no counterpart namespace), added `permissions: contents: write` so the GitHub Release job can now auto-publish the tar.gz asset on tag push.

### v1.18.13-madalone.4 → .8 (artwork pipeline + channel-type selection)

Post-`.3` work concentrated on the artwork pipeline. Full per-patch detail in [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md); concise per-release writeups in [`CHANGELOG.md`](CHANGELOG.md).

- **`.4`** (patches 36–40) — partial-update emit semantic (omit `MEDIA_IMAGE_URL` on transient fetch failure instead of blanking it), 3-attempt retry budget on artwork download, item-identity guard against `art={}` flicker on PVR/plugin sources, magic-byte MIME sniff for data URIs (Kodi omits `Content-Type`; Qt rejects `application/octet-stream`), shared `aiohttp.ClientSession` per device + new `artwork_timeout_seconds` config field (range 5–60, default 12).
- **`.5`** (patches 41–42) — `_post_subscribe_refresh` re-pushes the device snapshot to new media_player subscribers (turned out to be a firmware bug fixed in UC-Remote-UI v1.4.10; harmless on newer firmware); `_artwork_pending_retry` flag fixes the deferred-retry path that was self-skipping after a fetch failure.
- **`.6`** (patch 43) — clear `MEDIA_IMAGE_URL` in the no-players watchdog branch so the remote stops showing stale artwork when Kodi goes idle without firing a clean `OnStop`.
- **`.7`** (patch 44) — new `artwork_type_channels` config field with its own `MediaContentType.CHANNEL` branch in artwork-type selection. PVR / PseudoTV channels (`_item['type']='channel'`) were silently inheriting the generic `artwork_type` setting (default `"thumb"`), which on PseudoTV resolved to the embedded currently-airing show's season poster instead of the channel logo. New dropdown in setup with a `"thumbnail"` sentinel that wraps bare `special://...` paths into `image://...` so they resolve through `pykodi.thumbnail_url()` like any other URL.
- **`.8`** (patch 44b — same-day hotfix to `.7`) — flipped the `artwork_type_channels` default from `"thumbnail"` to `"icon"` after real-PVR testing showed `art["icon"]` is the channel logo on **both** PseudoTV (`image://special://...pseudotv.../logos/<channel>.png/`) and real PVR (`image://pvrchannel_tv@<encoded>/`), while top-level `item['thumbnail']` is structurally inverted between them: channel logo on PseudoTV but EPG program-art (the now-airing show's poster from the broadcaster's CDN) on real PVR. Sentinel handling preserved for the rare opt-in case.

## Recommended Settings

- **Download artwork:** Enabled — provides instant artwork on first entity open by pre-caching images as base64
- **Power off command:** None (disabled) — unless you specifically want the remote to shutdown/hibernate your Kodi host

## Installation

### Build (aarch64 — runs natively on Apple Silicon)

```bash
docker run --rm --name builder \
    --platform=linux/arm64 \
    --user=$(id -u):$(id -g) \
    -v "$PWD":/workspace \
    docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0  \
    bash -c \
      "cd /workspace && python -m pip install -r requirements.txt && \
      pyinstaller --collect-submodules zeroconf --clean -y --onedir --name driver src/driver.py"
```

### Package

```bash
mkdir -p /tmp/kodi-pkg/bin
cp dist/driver/driver /tmp/kodi-pkg/bin/
cp -r dist/driver/_internal /tmp/kodi-pkg/bin/
cp driver.json kodi.png /tmp/kodi-pkg/
cd /tmp/kodi-pkg && tar czf uc-intg-kodi-patched.tar.gz .
```

### Deploy to UC Remote 3

1. Open the Web Configurator at `http://<remote-ip>/`
2. Remove the existing Kodi integration (note your instance config first)
3. Go to **Integrations > Add new > Install custom**
4. Upload the `.tar.gz` file
5. Start setup and re-enter your Kodi instance details

There is no in-place update for custom integrations — removal and reinstall is required.

## Companion Firmware Fix

The fork also includes a fix to the UC Remote 3 firmware (`remote-ui`) for a [known artwork display bug](https://github.com/unfoldedcircle/feature-and-bug-tracker/issues/364) affecting all integrations:

- **`src/ui/entity/mediaPlayer.cpp`**: Re-downloads artwork when the URL matches but image data is missing (e.g., after entity re-subscribe)
- **`src/qml/components/entities/media_player/ImageLoader.qml`**: Allows image reload when `image2.source` is empty, even if the URL matches `prevUrl`

These firmware changes live in the main [UC-Remote-UI](.) project, not in this integration directory.

## Upstream

- **Original repo:** [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi)
- **Base version:** v1.18.13 (branch `v1.18.13-patched`; rebased from `v1.18.7-patched` on 2026-04-22)
- **Current tag:** `v1.18.13-madalone.3`
- **License:** [MPL-2.0](LICENSE) (unchanged from upstream)

## Changed Files

| File | Patches touching it |
|------|---------------------|
| `driver.json` | Version / metadata |
| `src/const.py` | 5 (power-off dropdown), 31–35 (new simple commands: MODE_CONTEXT_MENU, MODE_PLAY_SELECTED, MODE_KEYPRESS_C, MODE_CODEC_INFO, MODE_PLAYER_DEBUG, MODE_SYSTEM_MENU, MODE_KEYPRESS_ESC), upstream rebase touches |
| `src/kodi_device.py` | 1–4, 9, 11–13, 16, 17, 20–24, 26–30, 36–44 (most patch activity) |
| `src/media_player.py` | 7, 15, 16 |
| `src/remote.py` | 8 |
| `src/sensor.py` | 14, 19 |
| `src/selector.py` | 19 |
| `src/config.py` | 6, 16, 18, 25–27, 40, 44 (`artwork_timeout_seconds`, `artwork_type_channels`) |
| `src/setup_fields.py` | 6, 25–27, 40, 44 (`KODI_ARTWORK_CHANNELS_LABELS` + dropdown + new field) |
| `src/setup_flow.py` | 6, 16, 25, 26 (wires 2 new toggles through setup + reconfigure paths) |
| `src/media_browser.py` | 16, 25, 30 (video-only filter + sidecar thumbnail detection) |
| `src/driver.py` | 13 |
| `src/discover.py` | 16 |
| `src/pykodi/kodi.py` | 16 |
| `requirements.txt` | 10, rebase to ucapi 0.6.0 |

See `KODI-INTEGRATION-PATCHES.md` for full per-patch implementation notes. `CHANGELOG.md` lists user-facing changes by release tag.
