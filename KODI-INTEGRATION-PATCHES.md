# Kodi Integration Patches — Implementation Notes

## Base Version

Built from tag `v1.18.7` of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) on branch `v1.18.7-patched`.

**Builder image:** `docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0`
**Build command:** `pyinstaller --collect-submodules zeroconf --clean -y --onedir --name driver src/driver.py`
**Output:** `dist/driver/` (binary + `_internal/` with Python 3.11 runtime)

---

## Patch 1: Kodi Label Formatting Tag Stripping

**File:** `src/kodi_device.py`

**Problem:** Kodi uses BBCode-style markup in media titles (`[COLOR tomato]text[/COLOR]`, `[B]`, `[I]`, `[CR]`, etc.). The integration passes raw titles from Kodi's JSON-RPC `Player.GetItem` response directly to the UC3. PVR/IPTV EPG data and addon-sourced content are the primary sources of these tags.

**Solution:** Compiled regex constant + helper function applied at the single title extraction point.

```python
# Module-level (after imports)
import re

_KODI_MARKUP_RE = re.compile(
    r'\[(?:COLOR\s[^\]]+|/COLOR|/?(?:B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE)|CR)\]',
    re.IGNORECASE
)

def _strip_kodi_formatting(text: str) -> str:
    if not text or '[' not in text:
        return text
    return _KODI_MARKUP_RE.sub('', text).strip()
```

Applied at the title extraction point in `_update_states()`:
```python
# Before:
media_title = self._item.get("title") or self._item.get("label") or self._item.get("file")
# After:
media_title = _strip_kodi_formatting(
    self._item.get("title") or self._item.get("label") or self._item.get("file") or ""
)
```

**Reference:** [Kodi Wiki: Label Formatting](https://kodi.wiki/view/Label_Formatting), Kodi's own `StringUtils::RemoveFormatting()` in `xbmc/utils/StringUtils.cpp`.

**Scope:** Only `media_title` is stripped. `media_artist`, `media_album` could theoretically contain tags but this is rare. Can extend later if needed.

---

## Patch 2: Deferred Artwork Re-poll on Connect

**File:** `src/kodi_device.py`, method `connect()`

**Problem:** `connect()` calls `_update_states()` once on connection. If Kodi hasn't populated artwork metadata yet (common when connecting to an already-playing session), there's only a single deferred retry at +4s inside `_update_states()` — and only when `changed_media` is true AND artwork is empty.

**Solution:** Added a deferred re-poll 3 seconds after initial connection:

```python
await self._update_states()
# Deferred re-poll
asyncio.create_task(self._update_states(deferred=3))
```

Uses the exact same `asyncio.create_task(self._update_states(deferred=N))` pattern already in the codebase (line 1291). Lock-protected via `_update_lock`. No-op when nothing is playing (`get_players()` returns empty).

---

## Patch 3: Stop Handler Clears Stale Media Info

**File:** `src/kodi_device.py`, method `on_stop()`

**Problem:** The upstream `on_stop` handler calls `_reset_state([])` and emits only `{MediaAttr.STATE: self.state}`. Internal state fields (`_media_title`, `_media_position`, etc.) are not cleared. The UC3 sees the state go to "on" (stopped) but still displays the previous media's title, artwork, and progress bar.

Compare with the `else` branch in `_update_states()` (no active players) which properly clears all fields — `on_stop` should do the same.

**Solution:** Added cleanup of all media fields and emission:

```python
def on_stop(self, sender, data):
    ...
    self._reset_state([])
    self._media_position = 0
    self._media_duration = 0
    self._media_title = ""
    self._media_album = ""
    self._media_artist = ""
    self._media_id = ""
    self._thumbnail = None
    self._media_image_url = ""
    self._media_image_data = ""
    updated_data = {}
    if current_state != self.get_state():
        self._attr_state = self.get_state()
        updated_data[MediaAttr.STATE] = self.state
    updated_data[MediaAttr.MEDIA_POSITION] = 0
    updated_data[MediaAttr.MEDIA_DURATION] = 0
    updated_data[MediaAttr.MEDIA_TITLE] = ""
    updated_data[MediaAttr.MEDIA_ALBUM] = ""
    updated_data[MediaAttr.MEDIA_ARTIST] = ""
    updated_data[MediaAttr.MEDIA_IMAGE_URL] = ""
    self.events.emit(Events.UPDATE, self.id, updated_data)
```

---

## Patch 4: Artwork on First Entity Open (Subscribe Fix)

**File:** `src/kodi_device.py`, property `attributes`

**Problem:** Two code paths exist for sending artwork to the UC3:

| Path | Property used | With `download_artwork` enabled |
|------|--------------|--------------------------------|
| Real-time updates (`_update_states`) | `self.media_artwork` | Returns base64 data URI |
| Entity subscribe (`attributes`) | `self.media_image_url` | Returns raw Kodi HTTP URL |

When the user opens the entity view, `on_subscribe_entities` fires and pushes `attributes`. With `download_artwork` enabled, this sends the raw HTTP URL instead of cached base64. The UC3's C++ layer receives the URL, starts an async download from `http://kodi:8080/image/...`, which is slow or fails. On subsequent opens, `m_mediaImage` is already populated from a previous real-time update's base64 push, so it shows instantly.

**Solution:** Changed one line in the `attributes` property:

```python
# Before:
MediaAttr.MEDIA_IMAGE_URL: self.media_image_url if self.media_image_url else "",
# After:
MediaAttr.MEDIA_IMAGE_URL: self.media_artwork if self.media_artwork else "",
```

Now both paths use `media_artwork`, which returns base64 when `download_artwork` is enabled. The integration pre-downloads and caches artwork in the background as Kodi sends WebSocket updates, so the data is ready before the user opens the entity.

**Recommended config:** `download_artwork: true` for instant artwork on first open.

---

## Patch 5: "None" Power Off Command

**Files:** `src/const.py`, `src/kodi_device.py`

**Problem:** No way to disable the power-off button. Users can accidentally shutdown/hibernate the Kodi host.

**Solution:**

`const.py` — added entry to `KODI_POWEROFF_COMMANDS`:
```python
"None": {"en": "None (disabled)", "fr": "Aucune (désactivé)"},
```

`kodi_device.py` — early return guard in `power_off()`:
```python
if self._device_config.power_off_command == "None":
    _LOG.debug("[%s] Power off command disabled", self.device_config.address)
    return
```

---

## Patch 6: Suppress Volume Overlay on Remote

**Files:** `src/config.py`, `src/kodi_device.py`, `src/setup_fields.py`, `src/setup_flow.py`

**Problem:** When changing Kodi volume via the UC Remote's hardware buttons, the remote displays a large volume overlay (number + slider, or "+" icon) on its screen. This is redundant because Kodi already shows its own volume OSD on the TV.

**Solution:** Configurable option `suppress_volume_overlay` (default `False`). When enabled:

1. Removes all volume-related features from the media player entity: `Features.VOLUME`, `Features.VOLUME_UP_DOWN`, `Features.MUTE_TOGGLE`, `Features.MUTE`, `Features.UNMUTE`.
2. Stops emitting `MediaAttr.VOLUME` and `MediaAttr.MUTED` in media player update events and the `attributes` property.
3. Keeps internal state tracking (`self._volume`, `self._is_volume_muted`) intact — needed for mute toggle logic.
4. Sensor entities (`KodiSensorVolume`, `KodiSensorMuted`) continue updating via separate `KodiSensors.SENSOR_VOLUME` keys.

Volume commands still work through the remote entity's button mappings (`KODI_REMOTE_BUTTONS_MAPPING`), which route through `KodiMediaPlayer.mediaplayer_command()` independently of the media player entity's feature list.

**Config field:** `suppress_volume_overlay: bool = field(default=False)` in `KodiConfigDevice`.

**Setup UI:** Checkbox "Suppress volume overlay on remote (use TV's OSD instead)".

**Bug fix included:** `on_volume_changed()` had a comparison `volume != self._volume` (line 469 upstream) that was always `False` because `self._volume` hadn't been updated yet. Changed to `volume != int(self._app_properties["volume"])`. This means WebSocket volume events now actually propagate — upstream only caught volume changes via polling.

---

## Patch 7: eval() Replaced with ast.literal_eval() (Security Fix)

**File:** `src/media_player.py`

**Problem:** `custom_command()` used `eval(arguments[1])` to parse command parameters, allowing arbitrary Python code execution. The `eval()` was needed to support `PID` variable substitution (e.g., `{"playerid": PID, "to": "next"}`).

**Solution:** Replace `PID` in the argument string with the actual player ID value, then parse with `ast.literal_eval()`:

```python
# Before:
PID = device.player_id
params = eval(arguments[1])

# After:
pid = device.player_id if device.player_id is not None else 1
arg_str = arguments[1].replace("PID", str(pid))
params = ast.literal_eval(arg_str)
```

`ast.literal_eval()` only accepts Python literals (dicts, lists, strings, numbers, booleans, None) — no function calls, imports, or arbitrary expressions.

---

## Patch 8: Missing await in Remote Command Sequence

**File:** `src/remote.py`

**Problem:** In `send_commands()`, the command sequence branch (`SEND_CMD_SEQUENCE`) called `KodiMediaPlayer.mediaplayer_command()` without `await`:

```python
# Before:
result = KodiMediaPlayer.mediaplayer_command(self.id, self._device, command, params)

# After:
result = await KodiMediaPlayer.mediaplayer_command(self.id, self._device, command, params)
```

Without `await`, the result was a coroutine object (always truthy), never `StatusCodes.NOT_IMPLEMENTED`, so the keyboard button fallback never triggered. Commands in a sequence also fired simultaneously instead of sequentially.

---

## Patch 9: Media Position Elapsed Time Fix

**File:** `src/kodi_device.py`

**Problem:** `media_position_updated` property used `elapsed_time.seconds` to calculate current playback position. `timedelta.seconds` returns only the seconds component (0–59), not total elapsed seconds. After 1 minute of playback without a position update from Kodi, the reported position wraps incorrectly.

```python
# Before:
position = self.media_position + elapsed_time.seconds

# After:
position = self.media_position + int(elapsed_time.total_seconds())
```

`total_seconds()` returns the full duration as a float (e.g., 125.3 for 2m5.3s). `int()` truncates to match the integer position format.

---

## Patch 15: Custom Command BAD_REQUEST on Parse Failure

**File:** `src/media_player.py`

**Problem:** Patch 7 replaced `eval()` with `ast.literal_eval()` but left the surrounding control flow intact: on parse failure the except block logged the error and then fell through to `device.call_command(command_key, **params)` with `params = {}`. The user saw "success" while a corrupted command was issued.

**Solution:** Return `StatusCodes.BAD_REQUEST` when `ast.literal_eval` raises, and when the parsed value is not a dict (defensive — custom commands require a mapping to unpack as `**params`). Narrows the exception set to `(ValueError, SyntaxError, TypeError)`.

---

## Patch 16: Narrow Remaining Bare Exceptions

**Files:** `src/config.py`, `src/discover.py`, `src/pykodi/kodi.py`, `src/setup_flow.py`, `src/kodi_device.py`, `src/media_browser.py`

**Problem:** Audit of the `.4` build found 16 remaining `except Exception: pass` / `except Exception:` blocks outside the scope of patch 11. Most silently swallowed failures: discovery UUID extraction, connection close cleanup, setup-flow pairing cleanup, chapter-extraction parsing, play-pause fallback, top-level browse fallback, config-restore-on-import-failure, task cancellation paths.

**Solution:** Every catch narrowed to a concrete exception set appropriate for the operation. Every silent `pass` replaced with a debug/warning log so failures are visible.

| Location | Old | New |
|----------|-----|-----|
| `config.py:272` (import) | `Exception` | `(OSError, ValueError, TypeError, KeyError)` |
| `config.py:282` (restore) | `Exception: pass` | `OSError` + error log |
| `discover.py:55` (uuid) | `Exception: pass` | `(KeyError, AttributeError, UnicodeDecodeError)` + debug |
| `pykodi/kodi.py:159` (cancel) | `Exception: pass` | `(OSError, CancelledError, TransportError)` + debug |
| `pykodi/kodi.py:213` (get_name) | `Exception` | `(TransportError, ProtocolError, KeyError, TypeError)` + debug |
| `setup_flow.py:175,181,584,590` (close) | `Exception: pass` | `(OSError, CannotConnectError)` + debug |
| `kodi_device.py:376` (init close) | `Exception: pass` | `(OSError, TransportError)` + debug |
| `kodi_device.py:613` (clear close) | `Exception: pass` | `(OSError, TransportError, AttributeError)` + debug |
| `kodi_device.py:626` (ping) | `Exception` | `(OSError, ProtocolError)` |
| `kodi_device.py:740` (OS wait) | `Exception: pass` | `(IndexError, AttributeError)` |
| `kodi_device.py:820,840,1206` (cancel) | `Exception: pass` | `(RuntimeError, AttributeError)` |
| `kodi_device.py:1175` (chapters) | `Exception: pass` | `(KeyError, IndexError, TypeError, ValueError)` + debug (uncommented log) |
| `kodi_device.py:1795` (playpause) | `Exception` | `(TransportError, ProtocolError, CannotConnectError, ServerTimeoutError, OSError)` + debug |
| `kodi_device.py:2044` (language) | `Exception` | `(TransportError, ProtocolError, KeyError, TypeError)` + debug |
| `media_browser.py:637,806,1010` (per-item) | `Exception: pass` | `(KeyError, IndexError, TypeError[, AttributeError])` + debug, loop continues |
| `media_browser.py:1065` (top-level browse) | `Exception` | `(TransportError, ProtocolError, KeyError, IndexError, TypeError, AttributeError, ValueError)` — added `import jsonrpc_base` |

**Intent:** per-item loops in `media_browser.py` keep broad-ish catches (all the dict-shape errors) because one bad item should never kill a whole library browse — but they now log the skip so we can see it. Every other catch is tight enough that unknown bugs propagate instead of vanishing.

**Result:** zero remaining `except Exception:` or bare `except:` in live code (one commented-out line remains in `media_browser.py`, unreachable).

---

## Patch 17: Reconnect Delay Jitter

**File:** `src/kodi_device.py`

**Problem:** `start_watchdog()` slept for a fixed `WEBSOCKET_WATCHDOG_INTERVAL` (10s, or 30s once `_reconnect_retry >= 20`). In a fleet-of-Remotes deployment — or even a single Remote after a router reboot — every driver instance wakes up on the exact same cadence, hammering the Kodi instance with synchronized reconnect bursts.

**Solution:** Multiply each sleep by `random.uniform(0.75, 1.25)` — ±25% jitter. Added `import random`. No change to the mean cadence, just breaks the lock-step.

---

## Patch 18: KodiConfigDevice Validation in `__post_init__`

**File:** `src/config.py`

**Problem:** `KodiConfigDevice` was a bare dataclass that accepted wrong types silently. Invalid ports, blank addresses, or string-typed booleans from legacy configs would slip through to runtime where they'd fail in obscure places (JSON-RPC URL construction, Kodi connect, etc.).

**Solution:** Extend `__post_init__` after the existing default-application pass:

1. **Boolean coercion.** Fields that may arrive as `"true"`/`"false"` strings from setup flow or legacy JSON (`ssl`, `media_update_task`, `download_artwork`, `disable_keyboard_map`, `suppress_volume_overlay`, `show_stream_name`, `show_stream_language_name`, `sensor_include_device_name`, `log_additional_data`) are coerced to `bool`.
2. **Integer coercion.** `sensor_audio_stream_config` / `sensor_subtitle_stream_config` are coerced via `int()`; `ValueError` raised on garbage.
3. **Identity fields.** `id`, `name`, `address` must be non-empty strings (whitespace-only is rejected).
4. **Ports.** `port` (required) and `ws_port` (may be None for HTTP-only mode) pass through `_validate_port()`, which accepts ints or int-parseable strings, requires the 1–65535 range, and returns the canonical string form.

`config.py:load()` already catches `TypeError` when constructing `KodiConfigDevice` from JSON — extended to also catch the new `ValueError`, so a single corrupt config entry is skipped with a warning rather than killing the entire load.

**Why in `__post_init__` and not elsewhere:** fail-fast at the boundary. An invalid config should be rejected the moment it's materialized, not when it eventually gets used during a network call.

---

## Patch 19: Fix Empty Select/Sensor Attributes on Entity Subscribe

**Files:** `src/selector.py`, `src/sensor.py`

**Problem:** After shipping `.5` the audio-stream and subtitle-stream select entities on the Remote were empty even when Kodi had real tracks available. Regression introduced by the upstream cherry-pick in `.4` (commit `0589714`, "Fixed warnings with unknown and initialization of entities attributes").

The upstream commit added a dynamic `all_attributes` property to `KodiSelect` and `KodiSensor` and used it to initialize the base class — so the entities now boot with real values instead of empty dicts. But the same commit changed `update_attributes(update=None)` to return `self.attributes` (the **frozen** dict stored by the base class at `__init__` time) instead of recomputing via `all_attributes`.

`driver.py:146,148` calls `entity.update_attributes()` with no argument on every `SUBSCRIBE_ENTITIES` event — i.e. every time the Remote opens the select widget. At that moment the driver returned the stale dict from construction time, when `audio_tracks`/`subtitle_tracks` were still empty (the first Kodi poll hadn't happened yet). The Remote cached that empty list and never saw the real options arrive.

**Solution:** Change the `return self.attributes` fallback in both `KodiSelect.update_attributes` (`selector.py:76`) and `KodiSensor.update_attributes` (`sensor.py:92`) to `return self.all_attributes`. `all_attributes` is the dynamic property that reads `current_option` / `select_options` / `sensor_value` fresh every call — so a subscribe event always gets the current state.

Upstream never hit this because their manual test didn't subscribe-after-play — the bug only appears in the subscribe-then-populate-then-resubscribe flow the Remote firmware actually uses.

---

## Companion Firmware Fixes (remote-ui)

These fixes live in the main UC-Remote-UI project, not in this integration directory. They address [UC firmware bug #364](https://github.com/unfoldedcircle/feature-and-bug-tracker/issues/364) which affects all media player integrations.

### C++ Duplicate URL Gate

**File:** `src/ui/entity/mediaPlayer.cpp`, method `updateAttribute()`

**Problem:** `if (m_mediaImageUrl != newImageUrl)` skips the entire image download pipeline when the URL hasn't changed. But `m_mediaImage` (the downloaded data) may be empty if the entity was re-subscribed or the previous download was lost.

**Fix:**
```cpp
// Before:
if (m_mediaImageUrl != newImageUrl) {
// After:
if (m_mediaImageUrl != newImageUrl || (!newImageUrl.isEmpty() && m_mediaImage.isEmpty())) {
```

### QML Image Loader Guard

**File:** `src/qml/components/entities/media_player/ImageLoader.qml`

**Problem:** `if (url == prevUrl) { return; }` prevents reloading when the URL matches, even if the image was never actually loaded (e.g., first entity open).

**Fix:**
```javascript
// Before:
if (url == prevUrl) {
// After:
if (url == prevUrl && image2.source != "") {
```
