# Kodi Integration for Unfolded Circle Remote 3 (Patched Fork)

Fork of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (v1.18.7) with bug fixes for title formatting, artwork loading, playback state, and power-off control.

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
| `src/kodi_device.py` | Color tag stripping, deferred artwork re-poll on connect, stop handler cleanup, `attributes` property uses `media_artwork`, power-off guard for "None" |

See `KODI-INTEGRATION-PATCHES.md` for detailed implementation notes.
