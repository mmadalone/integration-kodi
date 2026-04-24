# Kodi Integration Patches — Implementation Notes

## Base Version

Built from tag `v1.18.13` of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) on branch `v1.18.13-patched`. Rebased from the prior `v1.18.7-patched` base on 2026-04-22 — see "Upstream Rebase to v1.18.13" section below.

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

> **⚠️ Reworked in v1.18.13-madalone.2 — see Patch 27.** The feature-removal approach below conflates entity capability with UI preference; post remote-ui v1.4.1, removing `Features.VOLUME` to hide the OSD also broke Kodi volume control entirely. Patch 27 deprecates the toggle and redirects users to remote-ui v1.4.2+ `Config.showVolumeOverlay`. The config key is retained for backwards compat; the feature-removal + attribute-suppression behavior below is **no longer active**.

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

## Patch 20: Select Entity Push Robustness

**Files:** `src/kodi_device.py`

**Problem:** After patch 19 the Remote could *open* the select widget and see options, but after the initial `_update_states` poll the select state was not kept current. Two stacked issues:

1. `_update_states()` only pushed the `OPTIONS` list inside `if changed_media:`, so the options were sent exactly once per title change. If the Remote subscribed after that moment, it never saw the options at all. The change-detection branches for audio/subtitle tracks pushed only `{CURRENT_OPTION}` — no `OPTIONS`.
2. `select_audio_track()` / `select_subtitle_track()` sent the Kodi command and returned, trusting that Kodi would fire `OnPropertyChanged`. Kodi does not consistently fire that event for keymap-style actions like `showsubtitles` (the toggle the driver uses when the user picks "Disabled"). The driver never noticed the state change, never pushed a new `CURRENT_OPTION`, and the Remote widget stayed on the old selection.

**Solution (20a — full snapshot push):** Precompute `audio_options` and `subtitle_options` lists unconditionally at the top of the audio/subtitle block. Track the last pushed list in `self._last_pushed_audio_options` / `self._last_pushed_subtitle_options` (reset in `__init__` and `_reset_state()`). Always push a full snapshot `{OPTIONS, CURRENT_OPTION}` when either the current value or the options list changes. This fixed the "options empty at subscribe" failure mode.

**Solution (20b — post-command refresh):** At the end of `select_audio_track()` and `select_subtitle_track()`, fire `asyncio.create_task(self._update_states(deferred=0)).add_done_callback(_log_task_exception)`. The explicit poll guarantees the driver re-reads state from Kodi immediately after the command, regardless of whether Kodi emits `OnPropertyChanged`. The task is fire-and-forget so the command handler can return promptly.

---

## Patch 21: Gate OPTIONS Push on Actual List Change (avoid Qt ListView reset)

**Files:** `src/kodi_device.py`

**Problem:** After patch 20, track-switching introduced a new regression: the very first click updated the Remote widget correctly, then subsequent clicks caused Kodi to change but left the Remote widget stale. Root cause was a latent Qt/QML bug in the Remote firmware's `Select.qml` (shared with upstream `unfoldedcircle/remote-ui`):

- The Remote UI's `EntityController.cpp` iterates incoming attribute updates via `QVariantMap`, which orders keys alphabetically.
- For a Select entity, `"current_option"` is processed *before* `"options"`.
- QML's `Select.qml` has a `Connections { onCurrentOptionChanged: selectCurrent() }` handler but **no** `onOptionsChanged` handler.
- On a bundled `{OPTIONS, CURRENT_OPTION}` update, QML runs `selectCurrent()` against the still-old options list, then the options list is reassigned on the ListView. Reassigning `ListView.model` **resets `currentIndex`**, and `selectCurrent()` never re-runs. The widget loses its highlight.

`.3` happened to avoid this because its mid-playback selection-change push sent `{CURRENT_OPTION}` alone (no `OPTIONS`), which never triggered the `ListView.model` reassignment at all.

**Solution:** Restore `.3`'s wire shape. In the audio and subtitle select-push blocks, only include the `OPTIONS` key in the emitted dict **when the options list has actually changed** (compared via `_last_pushed_audio_options` / `_last_pushed_subtitle_options`). Ordinary selection changes now push `{CURRENT_OPTION}` alone and never cause the Qt `ListView.model` reset. The options list is still pushed on the first poll after connect (trackers start as `None`) and any time Kodi gains or loses a stream mid-playback.

The UC-Remote-UI `Select.qml` bug is still a real bug and a good candidate for a PR upstream, but this driver-side fix works around it completely without needing a custom UI rebuild.

---

## Patch 22: Widen Chapter-Fetch Except for Kodi <22 Compatibility

**Files:** `src/kodi_device.py`

**Problem:** After patch 21, select widgets worked for the *first* track change after activity start, then stopped updating. Live log trace from the device showed `_update_states()` crashing with a JSON-RPC error:

```
WARNING:kodi_device: Update states error: (-32601, 'Method not found.', ...)
```

`Player.GetChapters` is a **Kodi 22+** JSON-RPC method. Older Kodi versions raise `ProtocolError(-32601, "Method not found")`. The chapter-fetch try/except in `_update_states` only caught `(KeyError, IndexError, TypeError, ValueError)` — the `ProtocolError` escaped to the outer `_update_states` handler and aborted the entire poll **before the subtitle/audio push code ran**. No `entity_change` event was emitted for that call.

First click worked because `changed_media=False` (media title hadn't changed yet), so `get_chapters()` was not called. Second click worked if the title had changed in between, which triggered `changed_media=True` and the doomed `get_chapters()` path.

**Solution:** Widen the chapter-fetch except clause to also catch `(TransportError, ProtocolError)`, logging at debug with a hint that `Player.GetChapters` is Kodi 22+. The failure is now isolated — `_update_states` completes normally and the subtitle/audio push runs.

---

## Patch 23: `on_property_changed` filter uses `any()` not `all()`

**Files:** `src/kodi_device.py`

**Problem:** User reported subtitle/audio state changes on Kodi (via keyboard, voice, or another client) sometimes never reflected on the Remote, and when they did there was noticeable lag. The `on_property_changed` WebSocket handler was dropping events silently:

```python
if all(
    x in ["currentaudiostream", "currentsubtitle", "subtitleenabled", "currentvideostream"]
    for x in data.get("property", {}).keys()
):
    ...
```

`all()` requires **every** key in the event to be in the whitelist. Kodi frequently bundles multiple properties in a single `OnPropertyChanged` notification — e.g. `{"property": {"currentsubtitle": {...}, "speed": 1}}`. Any such bundled event was silently dropped because `speed` isn't in the whitelist.

**Solution:** `any()` — if any key in the event is stream-related, trigger a state refresh. The inner `_update_states` already correctly handles events with extra keys. Also switched the whitelist to a set literal for O(1) membership tests.

---

## Patch 24: Periodic state-refresh safety net in the watchdog

**Files:** `src/kodi_device.py`

**Problem:** Even after patch 23, there are still cases where Kodi state changes without notifying the driver:

- Kodi doesn't always emit `OnPropertyChanged` for keymap-style actions (e.g. `showsubtitles`, direct keyboard shortcuts, voice control from Kodi itself).
- Another Kodi client (a second Remote, the Kodi Android app, the web UI) can mutate state without the driver seeing any event.
- Occasional event loss under network pressure.

The driver had **no periodic state refresh**. `start_watchdog` pinged every 10s (with ±25% jitter from patch 17) but only checked connectivity — it didn't refresh media/select state. So the Remote could drift arbitrarily far from Kodi's actual state until the user next triggered a command that forced a poll.

**Solution:** On every successful watchdog tick while the websocket is connected, fire `asyncio.create_task(self._update_states(deferred=0))` as a fire-and-forget task. The existing `_update_lock` handles collision with command-triggered polls. Worst-case lag for an un-announced state change drops from "infinite" to ~12s (watchdog jitter upper bound). The extra traffic is cheap: `_update_states` only emits an `entity_change` event when something actually changed, so idle players generate no extra Remote traffic.

---

## Dropped Patches 25-27 (considered during v1.18.13-madalone.2, pulled pre-release)

Three integration-side toggles were drafted during this release cycle: `suppress_media_browser`, `suppress_shuffle`, `suppress_repeat`. All three removed specific `Features.*` from the advertised feature set to make remote-ui hide the corresponding icons. They were pulled after smoke-testing revealed the mechanism is architecturally unsound for the common use case:

- **Why it looked correct on paper.** Remote-ui's device-class QMLs (e.g. `Receiver.qml:549,567`) gate the shuffle/repeat icons with `visible: entityObj.hasFeature(MediaPlayerFeatures.Shuffle)`. Strip the feature, hide the icon. Straightforward.
- **Why it fails in practice.** `driver.py:_configure_new_device` reuses the existing `KodiDevice` on reconfigure (line 325-326). `_register_available_entities` updates `api.available_entities`, but **not** `api.configured_entities` — the entities already subscribed to activities on the UC3. The ucapi protocol has `update_attributes` and `subscribe`/`unsubscribe` events but no `features_changed` event. So the remote's activity-side cache keeps the old feature list. Even a remote reboot doesn't clear it (persisted state). The only reliable way to pick up new features is a full integration uninstall + reinstall + fresh setup — unacceptable UX for a "toggle a checkbox" action.
- **Same architectural mistake as patch 6** (`suppress_volume_overlay`). Hiding UI by removing entity capabilities conflates "what the entity can do" with "what the user wants to see in the UI". Volume got this right by moving the concern to `UC-Remote-UI` `Config.showVolumeOverlay` (v1.4.2). Shuffle/Repeat/MediaBrowser will follow the same pattern in a future remote-ui release (`Config.showShuffleButton`, `Config.showRepeatButton`, `Config.showMediaBrowserButton` — single QML `visible:` binding each, ~20 lines, no entity-feature games).
- **Config-field residue.** The three fields (`suppress_media_browser`, `suppress_shuffle`, `suppress_repeat`) are retained in `KodiConfigDevice` with `default=False` so that existing `config.json` files from v1.18.13-madalone.2 pre-release builds still load without `TypeError`. They are no longer settable via setup/reconfigure and no code reads them. A future release may remove them entirely.

---

## Patch 25: `video_only_browse_filter` Toggle

**Files:** `src/config.py`, `src/setup_fields.py`, `src/setup_flow.py`, `src/media_browser.py`

**Problem:** Users who only use Kodi for video see music albums, picture sources, and subtitle/metadata companion files (`.nfo`, `.srt`, `.idx`, etc.) cluttering their browse results.

**Solution:** New per-device boolean toggle `video_only_browse_filter` (default `False`). Three interventions in `src/media_browser.py`:

1. **Root-menu filter (4b).** `MediaBrowser.__init__` filters `self._library_items` to drop any `KodiMediaEntry` whose `media_id` or `parent_id` starts with `kodi://music`, `kodi://sources/music`, or `kodi://sources/pictures`. Uses `list(KODI_BROWSING)` to make a copy so the module-level `KODI_BROWSING` constant is never mutated.

2. **Server-side filter (4a).** In `browse_media()`, at the source sub-directory browse path where `arguments` for `Files.GetDirectory` is built, force `arguments["media"] = KodiMediaTypes.VIDEOS.value` when the toggle is on. Uses Kodi's native `Files.GetDirectory` `media` parameter (official JSON-RPC API) so filtering happens server-side. The existing picture-source branch is preserved for backward compat when the toggle is off.

3. **Client-side extension filter (4c).** At both file-iteration sites (root `FILE` output block + source sub-directory block), skip entries whose lowercase extension is in `_VIDEO_ONLY_BLOCKED_EXTENSIONS = frozenset({".nfo", ".sub", ".srt", ".idx", ".ass", ".smi", ".ssa", ".sup", ".vtt"})`. Belt-and-braces: Kodi's `media=video` may leak some of these through depending on source type (plugin vs SMB vs library).

```python
_VIDEO_ONLY_BLOCKED_EXTENSIONS = frozenset(
    {".nfo", ".sub", ".srt", ".idx", ".ass", ".smi", ".ssa", ".sup", ".vtt"}
)

def _is_blocked_video_only_extension(file_dict: dict[str, Any]) -> bool:
    if file_dict.get("filetype") == "directory":
        return False
    name = file_dict.get("file") or file_dict.get("label") or ""
    if not name:
        return False
    return os.path.splitext(name)[1].lower() in _VIDEO_ONLY_BLOCKED_EXTENSIONS
```

**Caveat:** `paging.count` reflects Kodi's server-side total, which will be larger than the displayed count when extension filter drops entries. Minor UI inconsistency, acceptable.

---

## Patch 26: `suppress_unsupported_command_errors` Toggle

**Files:** `src/config.py`, `src/setup_fields.py`, `src/setup_flow.py`, `src/kodi_device.py`

**Problem:** Commands that Kodi doesn't support in the current context (pausing a PVR channel, seeking a live stream, etc.) surface on the UC Remote as red-triangle "Error sending the command / Kodi is not responding. Error code: 400" notifications. The operation legitimately isn't supported, but the error notification is noisy.

**Solution:** New per-device boolean toggle `suppress_unsupported_command_errors` (default `False`). Narrow: only suppresses JSON-RPC `ProtocolError` (Kodi application-layer errors like `-32601 "Method not found"`, and other per-command rejections). `TransportError` and `ServerTimeoutError` still surface as `StatusCodes.BAD_REQUEST` so genuine connectivity issues still alert.

Implementation in the `@retry()` decorator's second-retry except clause (post-retry, just before the fallthrough `return BAD_REQUEST`):

```python
except (TransportError, ProtocolError, ServerTimeoutError) as ex2:
    log_function("[%s] Error calling %s on (%s): %r", ...)
    if (
        isinstance(ex2, ProtocolError)
        and obj._device_config.suppress_unsupported_command_errors
    ):
        _LOG.debug(
            "[%s] Suppressing Kodi ProtocolError on %s per suppress_unsupported_command_errors",
            obj.device_config.address, func.__name__,
        )
        return ucapi.StatusCodes.OK
    return ucapi.StatusCodes.BAD_REQUEST
```

The first-retry except is unchanged — one-off failures still retry once so the toggle only suppresses *persistent* unsupported-command errors. No changes to `retry_call_command`.

---

## Patch 27: Deprecate `suppress_volume_overlay` (Rework of Patch 6)

**Files:** `src/setup_fields.py`, `src/kodi_device.py`

**Problem:** Patch 6's `suppress_volume_overlay` toggle conflated two concerns — entity capability (`Features` set) and UI preference (OSD visibility). It removed `Features.VOLUME`, `Features.VOLUME_UP_DOWN`, `Features.MUTE_TOGGLE`, `Features.MUTE`, `Features.UNMUTE` to hide the volume OSD on the remote.

Remote-ui v1.4.1 added feature-check guards (`mediaPlayer.cpp` / `volume.start()` pipeline now respects the feature set correctly). The side effect: with `suppress_volume_overlay=True`, volume control on Kodi stops working entirely — the OSD goes away, but so does the ability to actually change volume. Before remote-ui v1.4.1 the bug was masked because `volume.start()` was unguarded.

**Root cause:** removing features to hide UI is the wrong knob. UI preferences belong in the remote-ui `Config`, not in the integration's advertised entity capabilities.

**Solution:** Deprecate the toggle and redirect users to remote-ui v1.4.2+ (shipped 2026-04-24, commit `08e193e`) where `Config.showVolumeOverlay` controls OSD visibility independently of entity features.

1. `src/kodi_device.py` `__init__`: **delete the feature-removal block** for `suppress_volume_overlay`. Volume features are now always advertised.
2. `src/kodi_device.py`: **delete 4 MediaAttr emission guards**:
   - `on_volume_changed` × 2 (`MediaAttr.VOLUME`, `MediaAttr.MUTED`).
   - `_update_states` periodic refresh × 2 (same attributes).
   - `attributes` property × 1 (the conditional `if not ...: attributes[MediaAttr.VOLUME] = ...` block).

   Volume and mute attributes are now always emitted.

3. `src/kodi_device.py` `__init__`: add one-time WARNING log if the flag is still set to True in a migrated config:

```python
if device_config.suppress_volume_overlay:
    _LOG.warning(
        "[%s] suppress_volume_overlay is deprecated: volume features are now advertised. "
        "To hide the on-screen volume indicator, use UC Remote 3 Settings > UI > "
        "Show volume indicator (requires remote-ui v1.4.2+).",
        device_config.address,
    )
```

4. `src/setup_fields.py`: rewrite the checkbox label to indicate deprecation:

```
en: "(Deprecated — use UC Remote 3 Settings > UI > Show volume indicator instead) Suppress volume overlay on remote"
fr: "(Obsolète — utilisez UC Remote 3 Paramètres > UI > Afficher l'indicateur de volume) Masquer l'indicateur de volume sur la telecommande"
```

**Retained from patch 6:** the `on_volume_changed()` bug fix at line 477 (`volume != int(self._app_properties["volume"])`, replacing the always-false `volume != self._volume`) is orthogonal to the OSD concern and stays.

**Config key retained:** `suppress_volume_overlay: bool = field(default=False)` remains in `KodiConfigDevice`. Migrated configs with `True` are silently accepted (no migration step needed) — the `__post_init__` boolean coercion still fires, the value is read once in `__init__` solely to drive the deprecation log, and has no other runtime effect.

**User impact on upgrade from `v1.18.13-madalone.1`:**
- Users who had `suppress_volume_overlay=True` will see one WARNING log per device on start.
- Volume +/- buttons now correctly change Kodi volume (was broken in `.1` after remote-ui v1.4.1).
- The OSD fires on volume events. For OSD hiding, install remote-ui v1.4.2+ and set `Config.showVolumeOverlay=false` in UC Remote 3 Settings.

---

## Patch 28: Broader Artwork Fallback Chain (Plugin/Unscraped Content)

**File:** `src/kodi_device.py`

**Problem:** Media played via UC3 MediaBrowser showed no artwork on the player widget for plugin-source content (Netflix, unscraped local files) even when Kodi's `Player.GetItem` response had usable artwork under a key the integration didn't check.

**Diagnosis (live JSON-RPC samples against Kodi 21.3 on `madteevee.local`, 2026-04-24):**

| Source | `art` dict | `thumbnail` | Notes |
|---|---|---|---|
| Library movie | `{poster, thumb, fanart, icon, clearlogo}` | populated | Works via `art["thumb"]` (default `artwork_type`) |
| Netflix plugin | `{icon: <real URL>}` only | `""` | Broke — `art["thumb"]` is None |
| YouTube plugin | `{icon, thumb, poster, fanart}` all populated | populated | Works |
| Unscraped local | `{icon: "DefaultVideo.png"}` | `""` | Broke — art dict has only the placeholder icon key |

Netflix and similar plugins store the real thumbnail URL under `art["icon"]` only. The integration's fallback chain at `kodi_device.py:1070-1078` was:
1. `art.get(artwork_type)` (default `"thumb"`)
2. If `artwork_type == "fanart"`: `self._item["fanart"]`
3. `self._item["thumbnail"]`
4. Give up → `None` → empty URL emitted

That chain never touched `art["icon"]`, `art["poster"]`, `art["landscape"]`, etc. so any source that populated only those got empty artwork.

**Solution:** After the existing chain, walk a broader fallback list of art keys before giving up. Preserves the user's configured `artwork_type` preference (tries it first); only expands when the primary chain produces nothing:

```python
if thumbnail is None or thumbnail == "":
    for fallback_key in ("poster", "thumb", "landscape", "banner", "fanart", "clearart", "icon"):
        candidate = art.get(fallback_key)
        if candidate:
            thumbnail = candidate
            _LOG.debug("[%s] artwork fallback: using art[%r] for type=%s", ...)
            break
```

Order chosen for visual priority: `poster` / `thumb` / `landscape` are the "primary" visual representations; `banner` / `fanart` / `clearart` are contextual; `icon` is last resort (accepts Kodi's `DefaultVideo.png` placeholder rather than emitting blank).

**Trade-off on `DefaultVideo.png`:** unscraped library items now show Kodi's generic default-video icon on the UC3 player widget instead of a blank. Acceptable — users who want real art should scrape their library or use Embuary/TMDb Helper to backfill metadata. Blank was strictly worse as feedback.

**No new config field.** Hardcoded priority list; if users need further control later, an `artwork_fallback_chain` dataclass field could be added.

**Verification:** with the currently-playing Seth Meyers download (`"art": {"icon": "image://DefaultVideo.png/"}`), the fallback picks `"icon"` → `_media_image_url` = `http://madteevee.local:8080/image/image%3A%2F%2FDefaultVideo.png%2F` → UC3 fetches the generic video icon. For Netflix content, the same path emits the profile-thumbnail URL. No regression on library items (configured `artwork_type` still matches first).

---

## Patch 29: Filter Kodi `DefaultXxx.png` Placeholders + Validate Artwork Fetch

**File:** `src/kodi_device.py`

**Problem:** Patch 28's broader fallback chain was picking up `art["icon"]` values in cases where the primary `artwork_type` ("thumb" by default) returned nothing. For unscraped content, Kodi populates `"icon"` with its internal default placeholder URIs (`image://DefaultVideo.png/`, `image://DefaultAlbumCover.png/`, etc.). These URIs are **not servable as useful images** by Kodi's web API:

- When the UC3 (or the integration's `download_artwork` fetch) hits `http://kodi:8080/image/image%3A%2F%2FDefaultVideo.png%2F`, Kodi returns `Content-Type: application/octet-stream` with an HTML error body, not an image.
- With `download_artwork=true`, the integration would base64-encode the HTML body and ship it as `data:application/octet-stream;base64,<junk>` — the remote-ui cannot decode this and renders either a broken image or a blank tile.
- With `download_artwork=false`, the remote-ui fetches the URL directly and gets the same non-image response.

Either way the result is user-visible garbage instead of a clean "no art" placeholder. Diagnosed via a parallel `UC-Remote-UI` debugging session that observed the `application/octet-stream + HTML` response on the wire.

**Solution — two complementary filters:**

**29a — Discard `image://Default*` at the integration layer.** Two check sites in the artwork resolution block:

1. Inside the patch-28 fallback loop, skip candidates that start with `"image://Default"`:
   ```python
   for fallback_key in ("poster", "thumb", "landscape", "banner", "fanart", "clearart", "icon"):
       candidate = art.get(fallback_key)
       if candidate and not candidate.startswith("image://Default"):
           thumbnail = candidate
           ...
   ```
2. After the fallback chain resolves, catch the case where the *primary* `art[artwork_type]` or `self._item["thumbnail"]` returned a placeholder (patch 28's filter only covered the fallback branch):
   ```python
   if thumbnail and thumbnail.startswith("image://Default"):
       thumbnail = None
   ```

Netflix's `icon`-based real-URL case (`image://https%3a%2f%2f...`) is preserved because it doesn't match `image://Default`. Library movies unaffected — they resolve via `art["thumb"]` without hitting either guard. Unscraped content now emits empty → UC3 renders its own clean placeholder.

**29b — HTTP status validation in the `download_artwork` fetch path.** Belt-and-braces for placeholder URIs that slip past 29a, bad SMB mounts, plugin error pages, etc. Before base64-encoding the response, reject non-200 responses:

```python
if response.status != 200:
    _LOG.debug("[...] artwork fetch non-200 (status=%s url=%s), discarding", ...)
    self._media_image_data = ""
else:
    # ... existing encode-to-data-URI logic
```

**Content-Type is NOT checked** — Kodi's webserver deliberately omits the `Content-Type` header entirely for thumbnails. A direct probe against a real library thumbnail confirmed:
```
HTTP/1.1 200 OK
Connection: close
Accept-Ranges: bytes
Content-Length: 20276

<JPEG magic bytes>
```
No Content-Type. `aiohttp.response.content_type` then defaults to `"application/octet-stream"`, so any filter like `startswith("image/")` rejects every legitimate thumbnail. An earlier revision of patch 29b did this and broke all artwork. The 404 case for `image://DefaultVideo.png/` is caught by the status check alone; for a `200 + HTML body` edge case (if one ever exists), a magic-byte check would be the correct addition — not a content-type check.

Also adds an `and self._media_image_url` guard to the `download_artwork` branch so a `thumbnail=None` state doesn't try to HTTP-GET an empty URL.

**29c — Defensive guard on the SMB special-case branch.** The existing `if self._item["type"] == "movie" and "@smb" in thumbnail:` check at the same block would `TypeError` if `thumbnail` is now `None` (rare but possible after the patch 29a filter for a library movie whose `art["thumb"]` happened to be a `DefaultVideo.png`). Added an `and thumbnail` short-circuit.

**Net effect:**
- Unscraped local file (Seth Meyers case): integration emits empty → UC3 renders its own placeholder.
- Netflix profile thumbnail (icon-with-real-URL): unchanged, still shown.
- Netflix / plugin content whose only art is a `DefaultVideo.png` placeholder: now empty instead of broken.
- Library movies: unchanged.
- Video source files played through MediaBrowser: UI FW is tackling this separately via thumbnail handoff from `MediaBrowser.qml`; the integration-side change here means the FW-supplied preview isn't clobbered by a bad `MEDIA_IMAGE_URL` push.

---

## Patch 30: Sidecar Thumbnail Detection (Browse + Play)

**Files:** `src/media_browser.py`, `src/kodi_device.py`

**Problem:** MediaBrowser-initiated playback of a video file shows no thumbnail on the UC3 player widget, even when a real sidecar thumbnail file (`<basename>-thumb.jpg`, `<basename>.tbn`, folder-level `poster.jpg`, etc.) sits right next to the video on disk. Kodi-UI-initiated playback of the same file *does* show the thumbnail. The difference:

- Kodi's own skin scans for sidecar files at browse time and primes in-memory `item` state before `Player.Open` fires. `Player.GetItem` then returns a rich `art` dict.
- JSON-RPC-initiated `Player.Open({"file": path})` skips that skin-side scan. `Player.GetItem` returns `art = {"icon": "image://DefaultVideo.png/"}` and empty `thumbnail`, even though the sidecar is right there.

Confirmed via direct probes against Kodi 21.3: `Files.GetDirectory` on a Sonarr-formatted folder returns empty `art: {}` and `thumbnail: ""` for every entry — including the sidecar JPEGs themselves. `Files.GetFileDetails` on the .mkv leaf returns the same useless `icon: DefaultVideo.png`. The sidecar detection is a skin-UI behavior, not a JSON-RPC contract.

But: Kodi's `/image/` endpoint *does* serve any sidecar image path directly. `http://kodi:8080/image/image%3A%2F%2F%2Fhome%2F...%2Fepisode-thumb.jpg%2F` returns 200 + the thumbnail. So the fix is to replicate Kodi's skin-side sidecar scan in the integration.

**Solution — two places the scan needs to run:**

**30a — Browse-time (`src/media_browser.py`).** The Files.GetDirectory response already lists every file in the directory, including the sidecar JPEGs. Two module-level helpers (`_find_sidecar_for_file`, `_build_sidecar_map`) scan that listing and produce a `{video_file_path: sidecar_art_path}` map with **zero extra round-trips**. `get_item_from_file` has its `extract_thumbnail` bool replaced with an explicit `thumbnail_url: str | None` kwarg; all three callers (root `FILE` output at ~line 688, playlist at ~line 752, source sub-directory at ~line 823) pre-compute the URL using the sidecar map and pass it in. Picture-source browsing keeps its existing `get_thumbnail_from_file` path (the file itself IS the image). Playlist items stay thumbnail-less.

**30b — Play-time (`src/kodi_device.py`).** After the patch 28/29 art resolution chain exhausts, check `self._item["file"]`. If it's a local/SMB/NFS path (not `plugin://`, `pvr://`, `http(s)://`, `upnp://`), do one `Files.GetDirectory` on the parent folder and run `media_browser._find_sidecar_for_file(candidate_file, dir_files)`. If it returns a sidecar path, synthesize the `image://<sidecar>/` URI and feed it into the existing `_kodi.thumbnail_url()` → `_media_image_url` path. One extra JSON-RPC round-trip at play-start, only when the primary art dict has nothing useful.

**Sidecar conventions recognized** (priority order in `_find_sidecar_for_file`):

Per-video (`<base>` = video path without extension):
1. `<base>-thumb.jpg` (Sonarr/Radarr episode thumb)
2. `<base>-poster.jpg`
3. `<base>-landscape.jpg`
4. `<base>.tbn` (Kodi native, legacy)
5. `<base>.jpg` (plain basename match)

Also `.jpeg`, `.png`, `.webp` accepted. Folder-level fallback (any of these in the same directory):
- `poster.jpg`, `folder.jpg`, `cover.jpg`, `banner.jpg`, `thumb.jpg`, `fanart.jpg` — serves as the art for every video in the folder when no per-video sidecar exists.

**Why this approach over ffmpeg frame extraction (`image://video@<path>/`):** Kodi *can* extract a frame from any readable video file via the `video@` prefix (verified — 200 OK with real JPEG). That was considered and rejected because users who deploy Sonarr/Radarr already have canonical, human-curated artwork sitting next to the files; a random extracted frame is strictly worse. If a file *doesn't* have a sidecar, the ffmpeg path could still be added as a last-resort fallback in a future patch without breaking this one.

**Regressions considered (none triggered):**
- Patch 28 fallback chain: runs BEFORE patch 30 at play time, so library items with proper `art` dict still resolve via the configured `artwork_type` first. Sidecar lookup only fires when the entire prior chain produced nothing.
- Patch 29a placeholder filter: unaffected. `image://<sidecar-path>/` never starts with `image://Default`.
- Patch 29b status check: applies as-is. If a candidate sidecar URL 404s somehow (race condition, file moved mid-session), the download path discards cleanly.
- Playlist items (`.m3u` etc): no sidecar logic — they stay thumbnail-less as before.
- Picture-source browsing: unchanged (pictures use `get_thumbnail_from_file(file_path)` directly because the file IS the image).

---

## CI Hygiene (commit `63535d6`, on top of `.12`)

Not a numbered behavioral patch — the `Check Python code formatting` GitHub Actions workflow (pylint / flake8 / isort / black) had been red on `v1.18.7-patched` since the `.4` cherry-pick (2026-04-12), and the `.5`, `.11`, `.12` commits inherited the red status. This commit lands all the lint debt in one pass so CI is green from `.12` onward. Zero behavioral change — the `.12` binary already installed on the Remote is unchanged.

**Pylint fixes** (`src/kodi_device.py`):

- `retry_call_command`: dropped the unused `bufferize: bool` parameter (dead since patch 10 removed the buffered-callback path). Both call sites in the `retry()` decorator updated.
- `retry()` decorator inner except: dropped `TransportError` / `ProtocolError` / `ServerTimeoutError` from the fallback except (W0705 duplicate-except — already caught by the primary except above). Kept `OSError`.
- `init_connection()` session close: narrowed from bare `except Exception` to `(OSError, TransportError, AttributeError)`.
- `connect()` outer except: dropped duplicate `TransportError` / `CannotConnectError` (W0705), kept `(OSError, InvalidAuthError)`.
- `connect()` finally block: `websocket_task.cancel()` except narrowed from `Exception` to `(RuntimeError, AttributeError)`.
- `__init__` `suppress_volume_overlay` tuple wrapped over multiple lines (the one-liner was 121/120 chars). Added a `pylint: disable=duplicate-code` comment because R0801 flagged the wrapped block as structurally similar to the master feature list in `const.py`.
- `power_off()` inner except: renamed `ex` to `inner_ex` to stop shadowing the outer except variable (W0621).

**Formatter fixes:**

- flake8 E305: second blank line added between `_log_task_exception` helper and `_KODI_MARKUP_RE` constant.
- isort: `from kodi_device import _log_task_exception` in `src/driver.py` moved to the correct alphabetical slot in the `from ... import` block.
- black: three multi-line expressions (watchdog `create_task`, `audio_changed` comparison, deferred-artwork `create_task`) collapsed onto single lines now that they fit under the 120-char limit.

**Verification:** all four checks (pylint, flake8, isort, black `--target-version py311 --line-length 120`) run clean locally against the same `requirements.txt` the CI installs. GitHub Actions run `24341903111` confirms green on push.

---

## Upstream Rebase to v1.18.13 (2026-04-22)

Rebased `v1.18.7-patched` onto upstream `main` at tag `v1.18.13` — 6 unique upstream commits picked up (the 7th, `0589714 Fixed warnings…`, was already cherry-picked into our chain as `c647d97` and dropped here as a duplicate).

**Upstream changes pulled in:**
- `9cf5b1c` Fixed media search
- `9fbf60f` Small fixes on search media and refactoring (adds search filter categories — large `media_browser.py` rewrite)
- `0d60918` Fixed broken search with updated library
- `4608950` Updated dependencies (ucapi 0.5.3-dev → 0.6.0, jsonrpc-async pin loosened to `>=`, `MediaContentType` import path moved from `ucapi.api_definitions` to `ucapi.media_player`)
- `bf786b2` Updated ucapi (driver.json + requirements.txt)
- `fae059f` updated ucapi (wheel removal)

**Commits dropped during rebase (both no-ops post-rebase):**
- `c647d97 Fixed warnings with unknown and initialization of entities attributes.` — duplicate of upstream `0589714`
- `451b7d9 [fix] isort: alphabetize imports in setup_fields.py` — upstream now has the import sorted (single-line `from const import KODI_POWEROFF_COMMANDS, KodiObjectType`), our reorder is no longer needed

**Dependency switch (Option A — adopted upstream's set):**
- Removed local wheel `src/ucapi-0.5.3.dev12+gd11cfea3f.d20260321-py3-none-any.whl`
- `requirements.txt` now matches upstream verbatim:
  - `ucapi~=0.6.0` (from PyPI, no more local wheel)
  - `httpx~=0.28.1` (new)
  - `defusedxml~=0.7.1` (new)
  - `jsonrpc-async>=2.1.3`, `jsonrpc-websocket>=3.2.0`, `jsonrpc_base>=2.2.0` (loosened from `~=`)
  - `aiohttp~=3.13.5` (bumped from `~=3.13.3`)

**ucapi 0.6.0 breaking-change audit:**
1. `MediaType` → `MediaContentType` rename: we already used `MediaContentType` (from old `api_definitions` path); upstream commit `4608950` moves the import to `ucapi.media_player` and that change is inherited via the rebase.
2. `(str, Enum)` → `StrEnum` for ucapi enums: only affects ucapi's own enums. Our local `class KodiMediaTypes(str, Enum)` in `const.py` is independent; no change required.
3. Entity constructors require kwargs for optional fields: verified upstream v1.18.13 uses identical `super().__init__()` patterns to our patched files (required fields positional: `entity_id`, `name`, `features`, `attributes`; optional fields already kwarg-only: `device_class=`, `options=`, `simple_commands=`, `button_mapping=`, `ui_pages=`). No change required.

**Conflict resolution during rebase:** 8 git conflicts, all trivially auto-resolved by taking upstream's side:
- 6× `driver.json` (version-string bumps in our chore commits — final version set to `1.18.13-madalone.1` here)
- 1× `requirements.txt` (the dep-set divergence above)
- 1× iter-4 multi-file (`driver.json`, `src/const.py`, `src/media_player.py` — the duplicate-commit collision against upstream's `0589714`; equivalent change, upstream's wins)

**Final patch chain:** 18 commits on top of upstream `main` (down from 20 on `v1.18.7-patched`).

**Version:** `1.18.13-madalone.1` (resets the `madalone` suffix counter for the new base; previously `1.18.7-madalone.12`).

**Branch policy:** `v1.18.7-patched` retained as a safety net (matches the binary currently installed on the Remote). New work lives on `v1.18.13-patched`.

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
