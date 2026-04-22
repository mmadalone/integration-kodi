# Kodi Integration for Unfolded Circle Remote 3 (Patched Fork)

Fork of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (v1.18.13) with bug fixes for title formatting, artwork loading, playback state, and power-off control.

All credit for the integration goes to [Albaintor](https://github.com/albaintor). This fork applies targeted patches only — no upstream logic has been altered.

Requires remote firmware `>= 1.7.10`.

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
- **Base version:** v1.18.7 (branch `v1.18.7-patched`)
- **License:** [MPL-2.0](LICENSE) (unchanged from upstream)

## Changed Files

| File | Changes |
|------|---------|
| `driver.json` | Updated version, developer, description |
| `src/const.py` | Added "None (disabled)" to `KODI_POWEROFF_COMMANDS` |
| `src/kodi_device.py` | Patches 1-6, 9-13: tag stripping, artwork, stop handler, volume overlay, lock refactor, exception hardening, task callbacks, dead code removal |
| `src/media_player.py` | Patch 7: `eval()` → `ast.literal_eval()` |
| `src/remote.py` | Patch 8: missing `await` fix |
| `src/sensor.py` | Patch 14: `raise` → `return` bug fix |
| `src/config.py` | Patch 6: `suppress_volume_overlay` config field |
| `src/setup_fields.py` | Patch 6: setup UI checkbox |
| `src/setup_flow.py` | Patches 6, 10: config wiring, credential scrub |
| `src/driver.py` | Patch 13: task error callbacks |
| `src/pykodi/kodi.py` | Documentation: auth check comment |
| `requirements.txt` | Patch 10: removed unused deps, pinned jsonrpc versions |

See `KODI-INTEGRATION-PATCHES.md` for detailed implementation notes.
