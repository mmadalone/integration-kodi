# Kodi Integration Patches — Implementation Notes

## Base Version

Built from tag `v1.18.13` of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) on branch `v1.18.13-patched`. Rebased from the prior `v1.18.7-patched` base on 2026-04-22 — see "Upstream Rebase to v1.18.13" section below.

**Builder image:** `docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0`
**Build command:** `pyinstaller --collect-submodules zeroconf --clean -y --onedir --name driver src/driver.py`
**Output:** `dist/driver/` (binary + `_internal/` with Python 3.11 runtime)

---

## Patch Design Discipline (scan before drafting patch N+1)

| ID    | Sev | Trigger                                                                                  | Action |
|-------|-----|------------------------------------------------------------------------------------------|--------|
| AP-K1 | ❌  | Hiding a UI element by removing entity `Features.*`                                      | Stop. UI hiding belongs in remote-ui `Config.show*`, not integration features. |
| AP-K2 | ❌  | Mutating artwork-block state without auditing all 3+ guard predicates                    | Map gating, walk 2-3 watchdog ticks; prefer state machine or eliminate shared state. |
| AP-K3 | ⚠️  | Symptom is rendering (blank/stale), not data                                             | Wire capture + `GET /api/entities/<id>` BEFORE patching. Firmware first. |
| AP-K4 | ⚠️  | Defaulting a Kodi-shape-dependent config from one PVR/source                             | Validate on ≥3 source classes (library + real PVR + plugin) first. |
| AP-K5 | ℹ️  | 3+ targeted patches on one subsystem in one release window (Divergent Change)            | Stop. Refactor before patch #4. |

Full prose + patch references in `CLAUDE.md` § Fork Design Discipline. See also `STYLE_GUIDE.md` §5 (broader anti-patterns), §9 (patch anatomy template).

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

> **⚠️ Reworked in v1.18.13-madalone.2 — see Patch 27.** The feature-removal approach below conflates entity capability with UI preference; post remote-ui v1.4.1, removing `Features.VOLUME` to hide the OSD also broke Kodi volume control entirely. Patch 27 deprecates the toggle (no functional replacement in vanilla UC3 firmware — OSD hiding requires the `Madalones-Defolded-Circle-3` firmware fork's `Config.showVolumeOverlay` toggle, which is NOT in upstream remote-ui as of this writing). The config key is retained for backwards compat; the feature-removal + attribute-suppression behavior below is **no longer active**.

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
- **Same architectural mistake as patch 6** (`suppress_volume_overlay`). Hiding UI by removing entity capabilities conflates "what the entity can do" with "what the user wants to see in the UI". The right fix is moving the concern to a `Config.show*` toggle on the remote-ui side. We did this for volume in our private firmware fork (`Madalones-Defolded-Circle-3`) via `Config.showVolumeOverlay`; the same pattern would work upstream for shuffle/repeat/media-browser (`Config.showShuffleButton`, `Config.showRepeatButton`, `Config.showMediaBrowserButton` — single QML `visible:` binding each, ~20 lines, no entity-feature games). None of these `show*` toggles are in upstream UC firmware as of this writing.
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

**Solution:** Deprecate the toggle outright. There is no functional replacement in vanilla UC Remote 3 firmware — the OSD always fires on volume events. Hiding the OSD requires running the `Madalones-Defolded-Circle-3` firmware fork (commit `08e193e`, 2026-04-24), which adds a `Config.showVolumeOverlay` toggle controlled via **Settings → UI → Show volume indicator**. Users on stock UC firmware live with the OSD.

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
        "[%s] suppress_volume_overlay is deprecated and no longer has any effect; "
        "volume features are now advertised regardless. The setting is retained "
        "only for config backward compatibility.",
        device_config.address,
    )
```

4. `src/setup_fields.py`: rewrite the checkbox label to indicate deprecation:

```
en: "(Deprecated — no longer has any effect; setting retained for config backward compatibility) Suppress volume overlay on remote"
fr: "(Obsolète — sans effet ; paramètre conservé pour compatibilité ascendante) Masquer l'indicateur de volume sur la telecommande"
```

**Why no upstream-firmware redirect?** Earlier drafts of this section referred users to `remote-ui v1.4.2+ Config.showVolumeOverlay` — that was wrong. `Config.showVolumeOverlay` exists only in the private `Madalones-Defolded-Circle-3` firmware fork, NOT in upstream UC Remote 3 firmware. Users running this integration on stock UC firmware have no way to hide the OSD; the fix lives entirely on the firmware side.

**Retained from patch 6:** the `on_volume_changed()` bug fix at line 477 (`volume != int(self._app_properties["volume"])`, replacing the always-false `volume != self._volume`) is orthogonal to the OSD concern and stays.

**Config key retained:** `suppress_volume_overlay: bool = field(default=False)` remains in `KodiConfigDevice`. Migrated configs with `True` are silently accepted (no migration step needed) — the `__post_init__` boolean coercion still fires, the value is read once in `__init__` solely to drive the deprecation log, and has no other runtime effect.

**User impact on upgrade from `v1.18.13-madalone.1`:**
- Users who had `suppress_volume_overlay=True` will see one WARNING log per device on start.
- Volume +/- buttons now correctly change Kodi volume (was broken in `.1` after remote-ui v1.4.1).
- The OSD fires on volume events. For OSD hiding, the `Madalones-Defolded-Circle-3` firmware fork is required (set `Config.showVolumeOverlay=false` via **Settings → UI → Show volume indicator**). Vanilla UC firmware has no equivalent; the OSD will always appear on volume change.

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

**v1.21.0 update (2026-08-28):** the browse-time half now shares one fallback chain owned by `get_item_from_file`: `thumbnail_url` (sidecar, still first) → Kodi `art` dict via `get_artwork()` → Kodi-reported `thumbnail` → derive-from-file **only for `image/*` mimetypes** (upstream's guard). Both sidecar call sites pass `thumbnail_url=<sidecar or None>` + `extract_thumbnail=True`; the separate pictures branch at the `kodi://sources` loop is gone (pictures hit the same chain — the mimetype gate does the discrimination). See "Upstream Merge to v1.21.0". Known gap (pre-existing, not introduced there): the `smb://`/`nfs://`/`multipath://`/`special://` branch in `browse_media` runs *before* the `kodi://sources` branch and has no sidecar map, so browse-time sidecars currently work only for local-path / `upnp://` / `http://` sources. Candidate follow-up "patch 30c": add `_build_sidecar_map` + the #4c filter there.

---

## Patch 31: `MODE_CONTEXT_MENU` Simple Command (Harmony parity)

**File:** `src/const.py`

**Problem:** The integration's existing `Commands.CONTEXT_MENU` (mapped to the UC3 MENU button) runs through `kodi_device.context_menu()`, which **branches on fullscreen video**: `Input.ShowOSD` while video is playing, `Input.ContextMenu` otherwise. This diverges from Kodi's default keyboard `c` / Logitech Harmony MENU button (keycode `61507` / `0xF043`), which send `Input.ContextMenu` **unconditionally** regardless of fullscreen state.

User report: migrating from a Harmony remote, pressing the UC3 MENU button during fullscreen playback opens the transport OSD instead of the video context menu (subtitle/audio/bookmark options). Functional delta, not a bug per se — just a choice made by the original fork that doesn't match Harmony users' muscle memory.

**Solution:** Add a new entry to `KODI_ADVANCED_SIMPLE_COMMANDS`:

```python
"MODE_CONTEXT_MENU": {"method": "Input.ContextMenu", "params": {}, "holdtime": None},
```

Users who want the Harmony-style behavior map **`MODE_CONTEXT_MENU`** to any button they want (via UC3's per-button command mapping, or on a custom page). The existing `Commands.CONTEXT_MENU` fullscreen-branching behavior is **untouched** — fully backward-compatible for users who rely on the current OSD-in-fullscreen default.

No additional plumbing needed: `media_player.py:154-161` already dispatches `KODI_ADVANCED_SIMPLE_COMMANDS` MethodCall-shaped entries via `device.call_command(method, **params)`.

**Background:**
- Harmony keycode `61507` = `0xF043` is the MENU button, mapped by Kodi's default `system/keymaps/remote.xml` to the `contextmenu` action (= `Input.ContextMenu` via JSON-RPC).
- See the [Kodi Keymap wiki](https://kodi.wiki/view/Keymap) for per-remote keycode conventions.

---

## Patch 32: `MODE_PLAY_SELECTED` Simple Command (context-sensitive Kodi play)

**File:** `src/const.py`

**Problem:** The integration exposes `Commands.PLAY_PAUSE` on the UC3 hardware PLAY button, which routes through `Player.PlayPause` JSON-RPC — this is an **explicit toggle** on the currently-active player. It has no effect when the user has browsed to a folder or playlist in Kodi's UI and wants to start playback; pressing UC3 PLAY there does nothing (no active player to toggle).

Kodi's default `remote.xml` maps the remote PLAY button to the `play` action (not `playpause`). The `play` action is **context-sensitive**:
- No player active + browsing folder → play the focused folder's contents
- Playlist view + item focused → play from that item
- Already playing → toggle play/pause (same effect as `playpause`)

User migrating from a Logitech Harmony remote expected this behavior — "highlight a folder, press PLAY, contents play."

**Solution:** One-line addition to `KODI_SIMPLE_COMMANDS`:

```python
"MODE_PLAY_SELECTED": "play",
```

Exposed in the UC3 Remote entity's simple-command picker. User binds it to any button (or puts it on a custom page). Dispatches via `Input.ExecuteAction(action="play")`.

**No change to the hardware PLAY button behavior** — `Buttons.PLAY` still sends `Commands.PLAY_PAUSE` → `Player.PlayPause` as before, which is appropriate for the "I'm already playing, I want to pause" use case and the most predictable toggle behavior. Users who want Harmony-style context-sensitive play on the hardware PLAY button can remap it to `MODE_PLAY_SELECTED` via UC3's per-button mapping.

---

## Patch 33: `MODE_KEYPRESS_C` Simple Command (context-aware via Input.ButtonEvent) — ⚠️ RETIRED in v1.20.1-madalone.2 (2026-05-05)

> **⚠️ Retired in v1.20.1-madalone.2.** This dedicated simple command sent the exact same `Input.ButtonEvent(button="c", keymap="KB")` that the existing `custom_command "key c"` syntax sends. Pure alias for discoverability. Removed from `KODI_ADVANCED_SIMPLE_COMMANDS` to keep the simple-commands list focused. Users wanting this behavior type `key c` in the activity-button "Send command" field. Keeping the section here for historical context — design intent unchanged, only the registration was removed.

**File:** `src/const.py` (entry removed in v1.20.1-madalone.2)

**Problem:** Patch 31's `MODE_CONTEXT_MENU` always triggers the Kodi `contextmenu` action regardless of which Kodi window is focused. A Logitech Harmony remote's MENU button, however, sends keycode `61507` (= `0xF043` = virtual key `C`) to Kodi, which Kodi then routes through `system/keymaps/keyboard.xml`'s per-window hierarchy:

- `<global>` default: `c` → `contextmenu`
- `<FullscreenVideo>` override: `c` → `queue` (shows the current playlist/queue)
- `<FullscreenLiveTV>` override: `c` → `queue` (same)
- User custom keymap can override any of the above.

So on a Harmony-driven setup, pressing MENU during fullscreen video shows the queue, whereas pressing MENU when browsing the library shows the context menu — from a single physical button. Patch 31's direct JSON-RPC `Input.ContextMenu` call bypasses this routing and always produces the same behavior.

**Solution:** Add a new entry to `KODI_ADVANCED_SIMPLE_COMMANDS` that uses `Input.ButtonEvent` — Kodi's JSON-RPC equivalent of a real button press, which IS routed through the keymap:

```python
"MODE_KEYPRESS_C": {
    "method": "Input.ButtonEvent",
    "params": {"button": "c", "keymap": "KB"},
    "holdtime": None,
},
```

`keymap: "KB"` selects Kodi's keyboard keymap namespace; `button: "c"` is the keyname entry that Kodi looks up in `keyboard.xml`. Whatever action ends up mapped to `c` in the current window's scope fires — identical to a physical keyboard `c` press or a Harmony MENU button sending keycode 61507.

Naming convention (`MODE_KEYPRESS_<KEY>`) leaves room for additions — e.g. `MODE_KEYPRESS_M` for `m` (OSD) or `MODE_KEYPRESS_O` for codec info, should users ask for them.

**When to use which:**
- **`MODE_CONTEXT_MENU`** (patch 31) — always opens the context menu overlay. Predictable, explicit, bypass keymap. Use when you want "context menu" specifically and no surprises across windows.
- **`MODE_KEYPRESS_C`** (patch 33) — context-sensitive per Kodi keymap. Matches Harmony MENU button muscle memory. Use when you want the same button to behave differently during playback vs browse.

No conflict between the two — users can bind each to a different UC3 button.

**Reference:** [Kodi JSON-RPC Input.ButtonEvent PR #16858](https://github.com/xbmc/xbmc/pull/16858) which added this method specifically so JSON-RPC clients could reproduce keyboard/remote input without re-implementing the keymap routing client-side.

---

## Patch 34: Codec Info / Player Debug / System Menu Simple Commands

**File:** `src/const.py`

**Problem:** Three more commonly-requested Kodi actions had no bindable simple command — users needing them had to hand-craft `custom_command` invocations or map through `Input.ExecuteAction` manually.

**Solution:** Three entries in `KODI_ADVANCED_SIMPLE_COMMANDS`:

```python
"MODE_CODEC_INFO":   "codecinfo",      # Input.ExecuteAction(action="codecinfo")
"MODE_PLAYER_DEBUG": "playerdebug",    # Input.ExecuteAction(action="playerdebug")
"MODE_SYSTEM_MENU":  {"method": "GUI.ActivateWindow", "params": {"window": "settings"}, "holdtime": None},
```

**What each triggers in Kodi:**

- **`MODE_CODEC_INFO`** — toggles the codec-info overlay during playback (resolution, codec, bitrate, container). Default Kodi keyboard: `o` key.
- **`MODE_PLAYER_DEBUG`** — toggles the player debug overlay (CPU / GPU / FPS / dropped frames / buffer stats). Matches the user's existing Harmony keymap entry `<key id="61589">playerdebug</key>` (keycode 61589 = virtual key `U`).
- **`MODE_SYSTEM_MENU`** — opens Kodi's **Shutdown menu** (`GUI.ActivateWindow(shutdownmenu)`) which contains Exit, Power off system, Reboot, Hibernate, Suspend, Custom shutdown timer, Minimize, and Inhibit idle shutdown entries. If you want the general-purpose Kodi Settings window instead, change the `window` param to `"settings"`.

No new plumbing; all three dispatch through the existing `KODI_ADVANCED_SIMPLE_COMMANDS` handler in `media_player.py:154-161` (strings → `Input.ExecuteAction`, dicts → method call).

---

## Patch 35: `MODE_KEYPRESS_ESC` Simple Command (Esc-key simulation) — ⚠️ RETIRED in v1.20.1-madalone.2 (2026-05-05)

> **⚠️ Retired in v1.20.1-madalone.2.** Same reasoning as patch 33: equivalent to `custom_command "key escape"`, which the existing keymap-routing path supports. Removed from `KODI_ADVANCED_SIMPLE_COMMANDS`. Users type `key escape` instead.

**File:** `src/const.py` (entry removed in v1.20.1-madalone.2)

**Problem:** Users coming from keyboard-centric or Harmony-centric Kodi setups expected an "Exit" button that behaves like the physical Esc key — which, crucially, is **context-sensitive** in Kodi's default keymap:

- Global: `escape` → `previousmenu`
- `<FullscreenVideo>`: `escape` → `stop`
- `<Home>`: `escape` → `activatewindow(shutdownmenu)` (power menu)
- Dialog windows: `escape` → `close`

No single direct-action call reproduces all of those. `Input.ExecuteAction(action="back")` is closest but bypasses per-window overrides.

**Solution:** Same shape as patch 33 — use `Input.ButtonEvent` to route through the keymap:

```python
"MODE_KEYPRESS_ESC": {
    "method": "Input.ButtonEvent",
    "params": {"button": "escape", "keymap": "KB"},
    "holdtime": None,
},
```

Kodi's `button="escape"` keyname in the keyboard (`KB`) keymap namespace matches `<escape>` entries in `system/keymaps/keyboard.xml`, so per-window overrides apply.

Naming convention `MODE_KEYPRESS_<KEY>` continues from patch 33's `MODE_KEYPRESS_C`. Both commands follow the same pattern: emulate a keyboard keypress so Kodi handles context-aware routing.

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

## Patch 36: Partial-Update Emit Semantic on Artwork-Fetch Failure

**File:** `src/kodi_device.py`, `_update_states()` artwork-emit block + `__init__()` + removal of `_reset_media_artwork()` and the `is_starting_media`/`current_artwork` snapshots that supported it.

**Problem:** When the artwork download path (`download_artwork=true`) failed, the integration emitted `MEDIA_IMAGE_URL=""` to the remote. Diagnosed against UC Remote 3 firmware `0.38.4-32-g1266974` (pre-v1.4.9): the firmware's QML `Image` element interprets empty `source` as "clear the rendered image" — so a single transient HTTP fetch failure (timeout, transient 5xx, brief network blip) blanks the artwork on screen. Subsequent watchdog polls hit `thumbnail == self._thumbnail` and skip the entire artwork block, so the empty state is sticky until the playing media item changes.

The ucapi protocol semantics confirmed via `core-api/integration-api` AsyncAPI spec and the `integration-python-library` log-masker (which filters `data:` prefixes, confirming first-class data URI support): the `entity_change` message is a partial state delta. **Omitting an attribute is the canonical "no change" signal.** Emitting `""` is destructive — it actively replaces the previous value.

The integration was therefore fighting the protocol's natural retention semantic: a failed fetch should be invisible to the remote (omit), not destructive (emit empty).

Compounding this: the prior code path also pre-cleared `self._media_image_data = ""` before attempting the download, so even a momentary glance at the state mid-download would have shown empty data. And it called `_reset_media_artwork()` from the `is_starting_media + same-art` branch — a workaround for an old remote-firmware bug that re-emitted the *current* `media_artwork` value (a no-op given ucapi's deduplication). With the omit-on-failure semantic in place, the workaround is both unnecessary (the failure case it tried to recover from no longer exists) and harmful (it would re-emit on a transient empty state).

**Fix:**

1. **Replace emit-empty with omit on failure.** When `_fetch_artwork_with_retry()` (patch 37) returns `None`, do *not* add `MEDIA_IMAGE_URL` to `updated_data`. The remote retains its previously-loaded image. Schedule a deferred `_update_states(deferred=4)` retry so a longer-term recovery still happens.
2. **Don't pre-clear `_media_image_data`.** The download branch now owns the entire write decision: success → overwrite, failure → retain prior, genuine no-art → explicit clear.
3. **Remove `_reset_media_artwork()` entirely** along with its sole call site and the `current_artwork` / `is_starting_media` setup that supported it. Verified no external callers via grep.
4. **Genuine no-art paths preserved.** `on_stop()` (`kodi_device.py:471`) and the no-players branch (`kodi_device.py:1417-1453` of v1.18.13-madalone.3) still explicitly emit `""` because those are deliberate clears, not failure paths. This is correct — playback genuinely ended, the remote should blank.

**Why not pyscript-style "send empty to clear"?** Because ucapi's protocol doesn't distinguish "clear" from "no update" semantically — there's no special sentinel. The convention is: emit a real value when state changes, omit when it doesn't, emit `""` only when the actual *intended* state is empty (no media playing). Patch 36 aligns with the protocol; the prior code violated it.

**Behavioural impact:**
- Sticky-blank dropout (the user-facing symptom logged on 2026-04-26) eliminated.
- Subscribe-time staleness reduced as a side effect — with `_media_image_data` no longer being cleared on transient failure, the cache held by the integration is more likely to be accurate when the remote re-subscribes.
- No behaviour change for genuine no-media states.

**Breaking changes flagged:** none observable. Empty-string emission was always destructive; omit semantics is the protocol-correct path.

---

## Patch 37: Exponential-Backoff Retry on Artwork Fetch

**File:** `src/kodi_device.py`, new method `_fetch_artwork_with_retry()`.

**Problem:** Pre-v1.18.13-madalone.4, the `download_artwork=true` path made a *single* HTTP attempt with a hardcoded 5 s timeout. Any transient failure — timeout (often hit on slow Kodi instances serving thumbnails to their own UI under load), brief 5xx, network jitter — produced a blank emission with no recovery until the playing media item changed. UC Remote 3 firmware `0.38.4-32-g1266974` provides **zero retry budget for the base64 path** — the 3-retry budget at `mediaPlayer.cpp:850-856` (3 × 15 s) only fires for HTTP-URL mode (`download_artwork=false`). The integration is therefore the sole resilience layer for download-mode users until firmware reaches v1.4.9.

Combined with patch 36's omit-on-failure: a permanent fetch failure now correctly retains the prior good image, but a *transient* failure should still recover quickly without waiting for the next item change.

**Fix:** New async method `_fetch_artwork_with_retry(url) -> str | None` that:

- Makes 3 attempts at delays `0.0 / 0.5 / 1.5` seconds (constant `ARTWORK_FETCH_RETRY_DELAYS = (0.0, 0.5, 1.5)` at module level). Up to ±20 % jitter on the non-zero delays so concurrent failures against the same Kodi instance don't synchronise.
- Each attempt subject to the per-device timeout from `KodiConfigDevice.artwork_timeout_seconds` (patch 40), applied via `aiohttp.ClientTimeout(total=…)`.
- Patch 29b's HTTP 200 status check retained. Non-200 responses (Kodi 404 + HTML body for unresolvable `image://` URIs, etc.) are skipped with a debug log; the retry loop tries again, but a stable 404 will simply consume all 3 attempts and return `None`.
- Retains exception types from the prior code (`ClientError`, `asyncio.TimeoutError`, `OSError`) — wider than the original `Exception` catch, narrower than the lint trigger.
- On exhaustion: warn-level log including the last exception, return `None`.

**Worst-case lock hold:** `3 × ARTWORK_TIMEOUT + sum(delays) ≈ 38 s` with the default 12 s timeout — handled by patch 40's `UPDATE_LOCK_TIMEOUT` raise (10 → 30 s).

**Idempotent under cancellation:** aiohttp respects asyncio cancellation cleanly; a watchdog-cancelled fetch leaves no resource leak. Caller (patch 36) schedules a deferred re-poll on `None` return so that beyond-budget failures still recover eventually.

**Why inline backoff instead of `aiohttp-retry` or `backoff`?** PyInstaller bundles every dependency. Adding a library for ~30 lines of well-bounded retry logic doubled the code's transitive dep surface for no benefit. The fork's existing `random.uniform()` + `asyncio.sleep()` patterns (e.g. patch 17's reconnect jitter) cover the same ground without dependency growth. Officially: aiohttp's docs and Anthropic-style backoff guidance both say either approach is acceptable; the deciding factor is bundle weight.

**Breaking changes flagged:** none. The retry budget is additive on top of the existing single-attempt fetch.

---

## Patch 38: Item-Identity Guard Against Transient `art={}` from Kodi

**File:** `src/kodi_device.py`, `_update_states()` (replaces the unconditional `if thumbnail != self._thumbnail:` reset block) + `__init__()` (`_last_item_identity`).

**Problem:** Each watchdog tick (~10 s ±25 %) calls `Player.GetItem` and re-extracts `art`. Kodi sometimes returns an empty / partial `art={}` mid-playback for the *same* playing item — particularly visible on:

- PVR live channel transitions (EPG cycles on the hour/half-hour),
- Plugin sources still scraping (Netflix/YouTube/Movistar+ lazy-fetch art async),
- Library items mid-scrape after a fresh import,
- Buffer hiccups during demanding I/O.

When `art` is empty, patch 28's fallback chain finds nothing and `thumbnail` resolves to `None`. Pre-patch-38, that triggered the unconditional reset block (`thumbnail != self._thumbnail` was True because `None ≠ "previous URL"`), nuking `_media_image_url`, `_media_image_data`, and emitting an empty `MEDIA_IMAGE_URL` — observed as a flicker on the remote. The next poll usually got real `art` back and re-emitted the URL, restoring the image, but the visible flicker is the symptom.

**Fix:** Track item-identity tuple `(self._item.get("id"), self._item.get("file") or "")` in `self._last_item_identity` (initialised to `(None, "")`). Compare each poll:

```python
_item_identity = (self._item.get("id"), self._item.get("file") or "")
_item_changed = _item_identity != self._last_item_identity
self._last_item_identity = _item_identity

# Only treat thumbnail change as real if the new value is non-None OR the item shifted
_thumbnail_real_change = thumbnail != self._thumbnail and (
    thumbnail is not None or _item_changed
)
```

The reset block now fires only when `_thumbnail_real_change` is True. Concretely:

| State change | Before patch 38 | After patch 38 |
|---|---|---|
| Same item, art={} → None | reset (flicker) | ignore (retain prior) |
| Same item, real new URL | reset (correct) | reset (correct) |
| New item (id/file shift), art={} → None | reset | reset (genuine clear) |
| New item, real new URL | reset (correct) | reset (correct) |
| Same item, same URL | no-op | no-op |

**Why `(id, file)` and not just `id`?** Some Kodi content types (PVR EPG entries, plugin sources without scraped IDs) return `id=0` repeatedly; the `file` URL distinguishes them. Conversely, library items have a stable `id` but Kodi may transiently return `file=""`; the `id` distinguishes those. Tuple comparison handles both correctly.

**Edge cases verified:**
- First-ever poll: `_last_item_identity = (None, "")` initial value vs. real item's `(id, file)` produces a real change (correct: integration just connected, full state needed).
- Stop event clears `self._item={}` via `on_stop()` (`kodi_device.py:445-472`), then the next play repopulates it; `_last_item_identity` correctly tracks that as an item change.
- Item field rename (e.g. Kodi normalises path separators on a re-mount): `(id, file)` may produce a false-positive item-change. Acceptable — that's a real metadata mutation worth resetting for.

**Breaking changes flagged:** transient `art={}` mid-playback no longer blanks artwork. This is the *intended* behaviour (no user-facing regression — the previous flicker was a bug, not a feature).

---

## Patch 39: Magic-Byte MIME Sniff for `download_artwork` Data URIs

**File:** `src/kodi_device.py`, new static method `_sniff_mime()`. Called from `_fetch_artwork_with_retry()` (patch 37).

**Problem:** Kodi's HTTP server omits the `Content-Type` header on thumbnail responses. Pre-patch-39, the integration constructed the data URI as:

```python
"data:" + response.content_type + ";base64," + base64.b64encode(buffer).decode("utf-8")
```

`aiohttp.response.content_type` defaults to `"application/octet-stream"` when the upstream omits the header. The resulting data URI looks like `data:application/octet-stream;base64,<JPEG bytes>`. Qt's QML `Image` element + data: URI loader dispatch on the *declared* MIME type (per `QImageReader` docs and Qt forum threads), not on byte sniffing. So a `data:application/octet-stream` URI is silently rejected by the remote regardless of the actual content.

This explains why `download_artwork=true` artwork sometimes "doesn't render" on the installed firmware even when the fetch succeeds — the bytes are correct, the MIME declaration kills the image.

(The patch 29b commentary in v1.18.13-madalone.2 noted this: *"Kodi omits the [Content-Type] header entirely for real images, so aiohttp defaults to `application/octet-stream`."* That commentary correctly identified the cause but the fix was deferred.)

**Fix:** Sniff the buffer's magic bytes before constructing the data URI:

```python
@staticmethod
def _sniff_mime(buffer: bytes) -> str:
    if buffer[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if buffer[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(buffer) >= 12 and buffer[:4] == b"RIFF" and buffer[8:12] == b"WEBP":
        return "image/webp"
    if buffer[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"
```

**Why default to `image/jpeg` for unknown bytes?** Qt is forgiving of declared-MIME mismatch — if you declare `image/jpeg` but ship PNG bytes, `QImageReader` falls back to autodetection at decode time. But Qt outright rejects unknown declared types. So `image/jpeg` is the safest "I don't know" default. (Patch 29b's 200-status check still filters non-image responses upstream, so we shouldn't actually get here with non-image bytes.)

**Why not call `imghdr` / `filetype` / `Pillow`?** Three reasons:
1. `imghdr` was removed from Python 3.13 stdlib; relying on it is technical debt.
2. `filetype` is a 200 KB dep for what is genuinely 4 magic-byte comparisons.
3. `Pillow` is multi-megabyte and overkill.

This is exactly the "tried-and-tested approach" line: 4 magic-byte signatures cover >99 % of realistic web image formats; defaults handle the rest.

**Breaking changes flagged:** images that previously failed to render on the remote firmware due to the `application/octet-stream` MIME now render. No regression possible — the new declared MIME is *more* correct than the old one.

---

## Patch 40: Shared `aiohttp.ClientSession` + Configurable Artwork Timeout

**Files:** `src/kodi_device.py` (`__init__` / `connect` / `_clear_connection`); `src/config.py` (`artwork_timeout_seconds` field + `__post_init__` coercion); `src/setup_fields.py` (number field); `src/setup_flow.py` (5 touch-points per the documented config pattern).

**Problem (a) — per-call session construction:** the prior code used `async with ClientSession() as session:` inside `_update_states()` for every artwork fetch. aiohttp's official guidance is one `ClientSession` per app/device — per-call construction loses connection pooling, pays TLS/connect overhead each time, and makes `keepalive` ineffective. On a busy device polling every ~10 s, this is meaningful.

**Problem (b) — hardcoded 5 s timeout:** `ARTWORK_TIMEOUT = 5.0` was the only knob, and it was a module-level constant. Slow Kodi instances (RPi3-class hardware, NAS-served thumbnails, busy CPUs) hit the timeout legitimately under load. Users had no recourse.

**Problem (c) — patch 37's retry budget:** the worst-case lock hold (`3 × timeout + 2 s backoff`) needs to be accommodated by `UPDATE_LOCK_TIMEOUT` so that the watchdog doesn't abandon legitimate just-slow fetches.

**Fix:**

1. **Shared session.** `self._artwork_session: ClientSession | None` initialised in `__init__()`, created lazily in `connect()` after `self._kodi_connection.connect()` (so the event loop is guaranteed to be running), closed in `_clear_connection()` with a guarded try/except. Lifecycle matches the existing `_kodi_connection` pattern.

2. **Configurable timeout.** New `KodiConfigDevice.artwork_timeout_seconds: int = field(default=12)` with range validation (5-60 s) in `__post_init__`. Backward-compatible: configs without the field receive the default via the existing MISSING-default coercion loop.

3. **Setup-flow integration.** Number field added in `setup_fields.py` (positioned after the `download_artwork` checkbox — logical adjacency since it's only used in download mode). Five touch-points wired in `setup_flow.py` per the established pattern: initial parse, device creation, reconfig parse, reconfig assign, reconfig pre-populate. All handle the type-coercion failure gracefully (default fallback for new setup, retain previous value for reconfig).

4. **`UPDATE_LOCK_TIMEOUT` 10 s → 30 s.** Sized to accommodate worst-case retry budget without abandoning legitimate just-slow Kodi instances. The existing warning log line at `kodi_device.py:939` ("Update states lock acquisition timed out, skipping") still fires for genuinely-stuck polls — just at a more permissive threshold.

5. **`ARTWORK_TIMEOUT` constant retained as fallback.** Bumped to `12.0` to match the new default. Used as a sensible default by any future code path that needs an artwork-fetch budget without a device handle, but the live fetch path now uses the per-device value via `aiohttp.ClientTimeout`.

**Lifecycle robustness:**
- `connect()` checks `is None or closed` before creating; idempotent across reconnects.
- `_clear_connection()` close is guarded against `ClientError`/`OSError` so a session-close failure never prevents the rest of the reset.
- `_artwork_session = None` after close, so a subsequent re-`connect()` recreates cleanly.
- `_fetch_artwork_with_retry()` checks `is None or closed` defensively and returns `None` (which patch 36 handles as "omit"); shouldn't normally happen but guards against partially-torn-down state.

**Breaking changes flagged:**
- Existing configs missing `artwork_timeout_seconds` get the default 12 s on next load via dataclass coercion. No setup re-run required.
- Lock-timeout doubled — longer max hold of `_update_lock`. Acceptable trade-off; users who notice missing watchdog ticks can lower their `artwork_timeout_seconds` or disable `download_artwork`.
- New setup field; additive only. No existing field renamed or removed.

---

## Patch 41: Subscribe-Time Refresh (post-`v1.18.13-madalone.4` hotfix)

**File:** `src/driver.py`, new helper `_post_subscribe_refresh()` + one extra task spawn in `on_subscribe_entities`.

**Problem reported by user (after deploying `v1.18.13-madalone.4`):**

> at first we get no artwork on the remote display. but if i close the activity card and open it again i get it. … this seems to only happen after reinstalling the integration

The "after reinstall" qualifier is the smoking gun. Live websocket capture against `ws://192.168.2.204/ws` (subscribed to channel `all`, 90 s during steady-state playback of an episode with artwork) confirmed:

- `media_title` (re-flush of unchanged value) and `media_position` (rolling) were emitted every ~5 s.
- `media_image_url` was **never** re-emitted at steady state — which is the correct patch-36 omit-on-no-change behavior.

So the bug isn't in steady-state emission. It's the subscribe path during initial connect:

1. After reinstall, `_configure_new_device` (`driver.py:315-348`) creates the `KodiDevice` instance, registers `Events.UPDATE` listener, stores in `_configured_kodis`, and fires `device.connect()` as a background task.
2. User opens activity card. `on_subscribe_entities` finds the device in `_configured_kodis` and synchronously calls `device.attributes`. The `attributes` property (`kodi_device.py:1665+`) reads `self.media_artwork`, which in download mode returns `self._media_image_data` — `""` at this point (initial state from `__init__`).
3. Empty `MEDIA_IMAGE_URL` is shipped to the new subscriber.
4. The first `_update_states()` eventually completes (worst case ~38 s with patch 37's retry budget), `_thumbnail_real_change` is True, the artwork block fetches and emits `Events.UPDATE` with the populated `MEDIA_IMAGE_URL`.
5. `on_device_update` (`driver.py:255-288`) receives that, calls `filter_attributes(update, ucapi.media_player.Attributes)`, and pushes via `api.configured_entities.update_attributes`.

Step 5 *should* unstick the new subscriber. The firmware session (UC-Remote-UI commit `1266974`) confirmed the late `entity_change` is processed correctly at the C++/QML layer (no preview-preserve-eats-the-update issue). But the user observed the symptom persisting until close+reopen, which means the late propagation isn't reliably overwriting the empty value the synchronous push set into ucapi's internal store. Whether that's a ucapi-internal cache, a delivery-ordering quirk on the wire, or something else, it's outside this fork's reach to fix at the source.

**Fix:** add a belt-and-braces second push that runs only on subscribe, bounded by a single `Events.UPDATE` wait or a 30 s timeout. New helper:

```python
async def _post_subscribe_refresh(device_id: str, entity_id: str, timeout: float = 30.0) -> None:
    if device_id not in _configured_kodis:
        return
    device = _configured_kodis[device_id]

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _on_next_update(*_args, **_kwargs):
        if not fut.done():
            fut.set_result(None)

    device.events.once(kodi_device.Events.UPDATE, _on_next_update)

    try:
        await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        try:
            device.events.remove_listener(kodi_device.Events.UPDATE, _on_next_update)
        except (KeyError, ValueError):
            pass
        return

    configured_entity = api.configured_entities.get(entity_id)
    if configured_entity is None:
        return
    if isinstance(configured_entity, media_player.KodiMediaPlayer):
        api.configured_entities.update_attributes(
            entity_id, filter_attributes(device.attributes, ucapi.media_player.Attributes)
        )
```

In `on_subscribe_entities`, after the synchronous push for media_player entities:

```python
asyncio.create_task(
    _post_subscribe_refresh(device_id, entity_id)
).add_done_callback(_log_task_exception)
```

**Why `events.once` instead of polling:** the `pyee.AsyncIOEventEmitter` `once` registration self-removes after first fire (zero overhead in the common case). The `asyncio.wait_for` + 30 s timeout bounds the listener so a permanently-idle integration (no playback, no events) doesn't leak it. On timeout we explicitly remove the listener as a defensive cleanup — `pyee` raises `KeyError`/`ValueError` if the listener was already removed, which is fine.

**Why the second push is safe:** ucapi's `update_attributes` is idempotent for unchanged values (partial-update protocol). If the first poll's emission via `on_device_update` already updated the new subscriber correctly, the second push is a no-op. If it didn't, the second push overwrites with the current snapshot — which by then includes the populated `MEDIA_IMAGE_URL`. Worst case: one extra micro-message per subscribe.

**Breaking changes flagged:** none. The push happens at most once per subscribe, bounded by 30 s; the wire protocol shape is identical to existing pushes; no new attribute fields, no schema changes.

---

## Patch 42: Deferred-Retry Actually Retries (post-`v1.18.13-madalone.4` hotfix)

**File:** `src/kodi_device.py`, new `_artwork_pending_retry` flag in `__init__`, gating term on the artwork block, set/clear arms in the fetch-outcome branches.

**Problem (found while tracing patch 41):**

Patch 36's `_artwork_fetch_failed` branch scheduled a deferred re-poll at +4 s:

```python
if _artwork_fetch_failed:
    asyncio.create_task(self._update_states(deferred=4)).add_done_callback(...)
```

But the entry guard for the artwork block was just `_thumbnail_real_change` (patch 38), which evaluates to *False* on the deferred re-poll because:

1. The first attempt (the one that just failed) executed `self._thumbnail = thumbnail` and `self._media_image_url = self._kodi.thumbnail_url(thumbnail) or ""` at the top of the block, before the fetch was attempted.
2. The deferred re-poll runs 4 s later, reads the same `_item` from Kodi, computes the same `thumbnail`, and finds `thumbnail == self._thumbnail`. So `_thumbnail_real_change == False` and the artwork block is *skipped entirely* — no retry attempt happens.
3. `_media_image_data` stays `""` (omit-on-failure semantic from patch 36) until the playing item id/file actually shifts, by which point a new `thumbnail` triggers the block again from scratch.

The natural watchdog cadence (every ~10 s) hits the same skip path. So patch 36's omit-on-failure was retain-empty-forever in practice for any URL that failed all 3 inline retries on first attempt.

This isn't the cause of the user's reinstall symptom (different mechanism, addressed by patch 41), but it weakens patch 37's stated resilience claim and would manifest as sticky-blank artwork for any genuinely-flaky Kodi.

**Fix:** track a separate "fetch failed and needs retry" flag, and widen the artwork block's entry condition.

```python
# __init__
self._artwork_pending_retry: bool = False

# _update_states artwork block
_retry_pending = (
    self._artwork_pending_retry
    and self._device_config.download_artwork
    and bool(self._media_image_url)
)
_should_run_artwork_block = _thumbnail_real_change or _retry_pending

if _should_run_artwork_block:
    if _thumbnail_real_change:
        self._thumbnail = thumbnail
        self._media_image_url = self._kodi.thumbnail_url(thumbnail) or ""
    # ... SMB special case unchanged ...
    if self._device_config.download_artwork:
        if self._media_image_url:
            _new_data = await self._fetch_artwork_with_retry(self._media_image_url)
            if _new_data is None:
                _artwork_fetch_failed = True
                self._artwork_pending_retry = True   # arm flag
            else:
                self._media_image_data = _new_data
                self._artwork_pending_retry = False  # success clears
                updated_data[MediaAttr.MEDIA_IMAGE_URL] = self.media_artwork
        else:
            self._media_image_data = ""
            self._artwork_pending_retry = False      # genuine no-art clears
            updated_data[MediaAttr.MEDIA_IMAGE_URL] = ""
    else:
        self._artwork_pending_retry = False          # URL mode clears
        updated_data[MediaAttr.MEDIA_IMAGE_URL] = self.media_artwork
```

**Why a flag and not just `_media_image_data == ""`:** in URL mode the data field is always empty (the integration ships URLs, not data URIs), so checking emptiness would falsely arm the retry on every URL-mode poll. The flag is download-mode-specific and only set on actual fetch failure.

**Why retain `_thumbnail` mutation in the `_thumbnail_real_change` branch only:** during a retry the URL hasn't changed, only the data fetch needs to be re-attempted. We don't want to re-run the SMB special-case URL-massaging or thumbnail bookkeeping for the same URL.

**Recovery cadence:**
- The existing patch-37 deferred re-poll at +4 s now works (block actually runs).
- Watchdog ticks (every ~10 s ±25%) also retry naturally while the flag is set.
- Each entry runs the full inline 3-attempt budget (delays 0/0.5/1.5 s + per-attempt timeout from `artwork_timeout_seconds`), so a permanently-broken URL stabilizes at `_artwork_pending_retry=True` and consumes ~38 s of fetch time per watchdog tick. That's noisy but bounded; if it becomes a problem, future work could add a max-retry counter.
- Cleared on genuine media change (item id/file shifts → `_thumbnail_real_change=True`, the block re-enters from a clean state).

**Breaking changes flagged:** none observable in the success path. The failure path now retries instead of silently giving up — strictly an improvement.

---

## Patch 43: Clear Artwork in No-Players Branch (post-`v1.18.13-madalone.5` hotfix)

**File:** `src/kodi_device.py`, `_update_states()` no-players else-branch (around line 1617).

**Problem:** Surfaced when checking the UC Remote 3 entity state mid-redeploy and noticing the activity card was showing artwork from a previous Kodi session even though Kodi had been idle. The no-players else-branch in `_update_states` (the path that fires when `kodi.get_players()` returns empty — i.e., Kodi is connected but has no active player) was clearing most state correctly:

```python
# Pre-patch-43 no-players branch:
self._media_position = 0
self._media_duration = 0
self._media_title = ""
self._media_album = ""
self._media_artist = ""
self._media_id = ""
updated_data[MediaAttr.MEDIA_POSITION] = 0
updated_data[MediaAttr.MEDIA_DURATION] = 0
updated_data[MediaAttr.MEDIA_TITLE] = ""
updated_data[MediaAttr.MEDIA_ALBUM] = ""
updated_data[MediaAttr.MEDIA_ARTIST] = ""
updated_data[MediaAttr.SOURCE] = ""
# ... (more explicit clears)
# NOTE: media_image_url is conspicuously absent.
```

`media_image_url` was conspicuously absent. Combined with patch 36's omit-on-no-change semantic — which correctly retains prior artwork on transient fetch failures — the no-players watchdog ticks were ucapi no-ops for the artwork field. The remote kept rendering whatever it last received from a successful playback emit, indefinitely, even though Kodi had been idle for minutes/hours.

The on-stop handler (`kodi_device.py:445-472`) already does this correctly when Kodi sends a clean `OnStop`:

```python
self._thumbnail = None
self._media_image_url = ""
self._media_image_data = ""
updated_data[MediaAttr.MEDIA_IMAGE_URL] = ""
```

But Kodi doesn't always send `OnStop`. Observed (or plausible) cases that bypass it:

- Kodi crashes mid-playback (process killed; no `OnStop` emitted before death)
- WebSocket connection drops; integration reconnects later, finds Kodi idle, no `OnStop` was queued for relay
- User navigates away inside Kodi (back to home menu without explicit stop) — depending on Kodi version + skin behavior, `OnStop` may or may not fire
- Some Kodi addons (especially streaming plugins) close their player without firing `OnStop` if the user backs out

When any of those happens, the watchdog's no-players branch is the fallback. Pre-patch-43 it didn't clear the artwork.

**Fix:** mirror what `on_stop` already does, in the no-players branch:

```python
# Patch 43:
self._thumbnail = None
self._media_image_url = ""
self._media_image_data = ""
self._artwork_pending_retry = False
updated_data[MediaAttr.MEDIA_IMAGE_URL] = ""
```

Inserted just after `self._media_id = ""` and before the existing `updated_data[MediaAttr.MEDIA_POSITION] = 0` line, so the field-clear and the explicit-emit happen in the same place as the rest of the no-players branch (consistency with the existing code pattern).

**Why also clear `_artwork_pending_retry`:** patch 42's flag drives retry-on-next-poll for failed artwork fetches. Once we're in the no-players state, no playback exists to retry the fetch for, so the flag should be reset to avoid a stale retry firing if Kodi resumes playback with a different item (which would set its own `_thumbnail_real_change` and re-arm the flag fresh).

**Behavioral impact:**
- Kodi goes idle → next watchdog tick → artwork clears on remote (previously: persisted indefinitely).
- Kodi resumes playback → fresh `_thumbnail_real_change=True` on next poll → artwork re-fetched and emitted (unchanged from prior behavior).
- ucapi de-dupes if `MEDIA_IMAGE_URL` was already empty from a prior tick — so no log spam from emitting `""` repeatedly while idle.

**Why this doesn't conflict with other patches:**

- **Patch 36 (omit on transient failure):** patch 36's "omit" applies inside the artwork block (when `_thumbnail_real_change` or `_retry_pending` was true). The no-players branch is a different code path entirely — it's the genuinely-no-playback state where clearing IS the correct behavior, equivalent to on-stop.
- **Patch 38 (item-identity guard):** sits in the artwork block and prevents transient `art={}` mid-playback from clobbering state. The no-players branch is invoked when there's no active player at all — distinct from "playing item with momentarily-empty art."
- **Patch 41 (`_post_subscribe_refresh`):** unaffected. Its listener fires on the next `Events.UPDATE` regardless of which branch produced it.
- **Patch 42 (`_artwork_pending_retry` flag):** explicitly reset here so a stale retry doesn't carry across the playback→idle transition.

**Breaking changes flagged:** none observable. Adds clear behavior to a path that previously left state stale; doesn't alter `on_stop` or any other already-correct code path. The wire shape doesn't change beyond emitting `MEDIA_IMAGE_URL=""` on the watchdog tick that first observes "no players" — same as `MEDIA_TITLE=""` already does.

---

## Patch 44: Channel-Type Artwork Selection (`v1.18.13-madalone.7`)

**Files:**
- `src/config.py` — `KodiConfigDevice` dataclass at line 60.
- `src/setup_fields.py` — labels list, default const, `SETUP_FIELDS` entry.
- `src/kodi_device.py` — `_update_states()` artwork-type selection at lines 1209-1227.

**Problem:** Watching PseudoTV channels on Kodi (`plugin.video.pseudotv.live` — addon that synthesizes PVR channels from local library content) showed the **currently-airing show's season poster** on the UC Remote 3 instead of the **PseudoTV channel logo**. Live capture via Logdy WS (`ws://192.168.2.204/log/ws`) on 2026-04-29 with PseudoTV channel "Club Super 3" airing *Capità Harlock (1978) S01E01*:

```
DEBUG:kodi_device:[madteevee.local] Kodi extracted properties:
{
  'art': {
    'icon':           'image://special%3a%2f%2fprofile%2faddon_data%2fplugin.video.pseudotv.live%2fcache%2flogos%2fClub%20Super%203.png/',
    'thumb':          'image://%2fmnt%2fDEEPEE%2fTV%2fCapita%cc%80%20Harlock%20(1978)%2fseason01-poster.jpg/',
    'tvshow.poster':  'image://%2fmnt%2fDEEPEE%2fTV%2fCapita%cc%80%20Harlock%20(1978)%2fposter.jpg/',
    'tvshow.clearlogo': '...clearlogo.png/',
    ...
  },
  'thumbnail': 'special://profile/addon_data/plugin.video.pseudotv.live/cache/logos/Club Super 3.png',
  'type': 'channel',
  'showtitle': 'Capità Harlock', 'season': 1, 'episode': 1
}
```

The PseudoTV channel logo (`Club Super 3.png`) is delivered in **two** clean fields:
1. Top-level `item['thumbnail']` as a bare `special://...` path
2. `art['icon']` as an `image://`-wrapped `special://...` path

Everything else in `art` (`thumb`, `tvshow.*`, `season.*`) refers to the **embedded currently-airing show**, not the channel.

The pre-patch code at `src/kodi_device.py:1210-1213` was a 3-way branch:

```python
if self.media_type in [MediaContentType.TV_SHOW, MediaContentType.SEASON, MediaContentType.EPISODE]:
    artwork_type = self._device_config.artwork_type_tvshows   # default: "tvshow.poster"
else:
    artwork_type = self._device_config.artwork_type           # default: "thumb"  ← CHANNEL falls here
```

`KODI_MEDIA_TYPES` (`src/const.py:175`) maps `"channel" → MediaContentType.CHANNEL`, which falls into the `else` arm — so PVR channels were inheriting the movie/music/everything-else default `"thumb"`. `art["thumb"]` was non-empty (it's where PseudoTV embeds the show poster), so the existing fallback to `item['thumbnail']` at line 1227 never ran. Result: every PVR channel showed the embedded show's poster on the remote.

Latent secondary issue: `pykodi.kodi.thumbnail_url()` at `src/pykodi/kodi.py:78-86` only handles `image://...`-wrapped thumbnails. Bare `special://profile/...` paths return `None` from this method, so even if the existing fallback at line 1227 had reached, the bare `item['thumbnail']` for PseudoTV would silently fail to resolve into an HTTP URL.

**Solution:** Add a third media-type branch and a `"thumbnail"` sentinel that reads the top-level field directly with `image://`-wrap-on-bare-path handling.

`src/config.py:60` — new field:

```python
artwork_type_channels: str = field(default="thumbnail")
```

`src/setup_fields.py` — new dropdown labels list, new default const, new `SETUP_FIELDS` entry between the TV-show and browsing dropdowns:

```python
KODI_ARTWORK_CHANNELS_LABELS = [
    {"id": "thumbnail", "label": {"en": "Channel logo", ...}},
    {"id": "icon", "label": {"en": "Icon (art.icon)", ...}},
    {"id": "thumb", "label": {"en": "Currently-airing show poster", ...}},
    {"id": "poster", ...}, {"id": "fanart", ...}, {"id": "clearlogo", ...},
    {"id": "clearart", ...}, {"id": "banner", ...}, {"id": "landscape", ...},
]

KODI_DEFAULT_CHANNELS_ARTWORK = "thumbnail"  # internal sentinel — selects top-level item['thumbnail']
```

`src/kodi_device.py:1209-1227` — 3-way → 4-way branch + sentinel handling:

```python
if self.media_type in [MediaContentType.TV_SHOW, MediaContentType.SEASON, MediaContentType.EPISODE]:
    artwork_type = self._device_config.artwork_type_tvshows
elif self.media_type == MediaContentType.CHANNEL:
    # Patch 44: PVR / PseudoTV channels — separate config knob ...
    artwork_type = self._device_config.artwork_type_channels
else:
    artwork_type = self._device_config.artwork_type

# Patch 44: "thumbnail" sentinel — read top-level item['thumbnail'] directly.
# PVR channel logos arrive as bare `special://...` paths (no image:// wrapping),
# which pykodi.thumbnail_url() refuses to resolve. Wrap bare paths into the
# image:// scheme using the same encoding pattern as get_thumbnail_from_file()
# (pykodi/kodi.py:88-93) so the downstream fetch pipeline works unchanged.
if artwork_type == "thumbnail":
    _raw_thumb = self._item.get("thumbnail", None)
    if _raw_thumb and not _raw_thumb.startswith("image://"):
        thumbnail = f"image://{urllib.parse.quote(_raw_thumb, safe='')}/"
    else:
        thumbnail = _raw_thumb
else:
    thumbnail = art.get(artwork_type, None)
    if thumbnail is None and artwork_type == "fanart":
        thumbnail = self._item.get("fanart")

if thumbnail is None or thumbnail == "":
    thumbnail = self._item.get("thumbnail", None)
```

The bare-`special://`-wrap step turns `special://profile/.../Club Super 3.png` into `image://special%3A%2F%2Fprofile%2F.../Club%20Super%203.png/`, which `pykodi.thumbnail_url()` then resolves to `http://kodi:hehehe@madteevee.local:8080/image/image%3A%2F%2Fspecial%253A%252F%252F.../...png` — fetchable HTTP URL, identical handling to the rest of the pipeline.

**Why inline-wrap in `kodi_device.py` instead of fixing `pykodi.thumbnail_url()`:** the latter would touch the public pykodi surface and affect movie/music/album/plugin paths globally. Sentinel-handle inline keeps the blast radius small (one branch, one sentinel string, easy to revert).

**Why the new field defaults to `"thumbnail"` (not `"thumb"`):** PseudoTV is the canonical case where users notice the difference, and on PseudoTV (and most PVR-like sources) the top-level `item['thumbnail']` is consistently the channel logo. Users who want the prior behavior (show poster on PVR) can set it to `"thumb"` — that route still works through the original `art.get("thumb")` path. Users on integrations whose channel logo lives at `art["icon"]` (Netflix-plugin-style metadata) can pick `"icon"`.

**Behavioral impact:**
- PVR / PseudoTV channels → channel logo (via top-level `item['thumbnail']` → wrapped → fetched as HTTP).
- Movies / TV shows / music / files / everything-non-channel → unchanged (still uses `artwork_type` / `artwork_type_tvshows` as before).
- Existing fallback chain at lines 1229-1247 (Patch 28 — `("poster", "thumb", "landscape", "banner", "fanart", "clearart", "icon")`) still runs if the configured `artwork_type_channels` resolves to None, so non-PseudoTV `type=channel` items (e.g., real DVB-T tuners with sparse art) still get a usable visual.

**Why this doesn't conflict with other patches:**
- **Patch 28 (broader fallback chain):** unchanged. It runs after the configured-artwork-type lookup, including after the new sentinel returns None.
- **Patch 29a (Default*.png placeholder skip):** unchanged. Operates on the resolved `thumbnail` value regardless of which branch produced it.
- **Patch 30 (sidecar thumbnail recovery):** unchanged. Operates further down, after the `thumbnail` value is finalized.
- **Patch 36 (omit-on-no-change):** unchanged. The `_thumbnail_real_change` calculation at line 1310 sees the new resolved URL just like any other resolved URL.
- **Patches 37/38/39/40 (retry/MIME/timeout/session pipeline):** unchanged. Same fetch path runs on the new URL.
- **Patches 41/42/43 (subscribe-refresh / deferred-retry / no-players-clear):** orthogonal. Operate on different code paths.

**Breaking changes flagged:** none. Existing devices auto-populate the new field with the default on next config-load via `KodiConfigDevice.__post_init__` MISSING-default loop (`src/config.py:86-92`). The wire shape changes only for `_item['type']='channel'` items, where prior behavior of "embedded show poster" is replaceable with the prior-default `"thumb"` choice in the new dropdown. ucapi `entity_change` payload structure is unchanged.

**Verification:**
- Build: PyInstaller per fork's documented build pipeline (`docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0`).
- Deploy: upload to UC3 via REST `/api/intg/instances/...` (existing fork install path).
- Confirm via Logdy: `Kodi update` events emitting `MEDIA_IMAGE_URL` resolve to the channel-logo URL (`...Club Super 3.png`), not the show-poster URL (`...season01-poster.jpg`).
- Confirm via setup wizard reconfigure: new dropdown "Artwork type to display for PVR/Channels" appears between the TV-show dropdown and the browsing dropdowns, with "Channel logo (default)" pre-selected.

---

## Patch 44b: Default-Choice Hotfix (`v1.18.13-madalone.8`)

**Files:** `src/config.py:61`, `src/setup_fields.py` (default const + label order).

**Problem:** Patch 44 defaulted `artwork_type_channels` to `"thumbnail"` — read top-level `item['thumbnail']`. That worked correctly on PseudoTV (the test target during patch 44 design) where top-level `thumbnail` is `special://...pseudotv.../<channel>.png` (channel logo). But real PVR (Kodi's PVR client connected to a Movistar+ tuner — verified via Logdy capture 2026-04-29 04:07Z) has the inverted shape:

```
'art': {
  'icon':  'image://pvrchannel_tv@https%3a%2f%2festatico.emisiondof6.com%2f...%2fTVE/',  ← TVE channel logo
  'thumb': 'image://pvrchannel_tv@https%3a%2f%2festatico.emisiondof6.com%2f...%2fTVE/',
},
'thumbnail': 'https://www.movistarplus.es/recorte/n/ficha/M24HF518404',  ← EPG program-art (NOT channel logo)
'title': 'Telediario Matinal',
'type': 'channel'
```

Top-level `thumbnail` for real PVR is the **EPG program image** (poster of the currently-airing show), not the channel logo. Defaulting to `"thumbnail"` showed users program posters instead of TVE/Antena 3/whatever channel branding.

**Solution:** Flip the default from `"thumbnail"` to `"icon"`. `art['icon']` is consistently the channel logo on **both** integrations:

- PseudoTV: `art['icon'] = image://special://...pseudotv.../logos/Club Super 3.png/`
- Real PVR (Kodi PVR client): `art['icon'] = image://pvrchannel_tv@<encoded url>/`

Both are `image://`-wrapped, both resolve correctly via `pykodi.thumbnail_url()` → Kodi's `/image/` endpoint. Kodi's image dispatcher knows about both `special://` (addon paths) and `pvrchannel_tv@` (PVR client). No new code path.

```python
# src/config.py:61
- artwork_type_channels: str = field(default="thumbnail")
+ artwork_type_channels: str = field(default="icon")

# src/setup_fields.py
- KODI_DEFAULT_CHANNELS_ARTWORK = "thumbnail"
+ KODI_DEFAULT_CHANNELS_ARTWORK = "icon"
```

`KODI_ARTWORK_CHANNELS_LABELS` reordered so "Channel logo (default)" (id=`icon`) is the first option in the dropdown. The `"thumbnail"` option label clarified to "Top-level thumbnail (PseudoTV addon path / EPG image)" — accurately describing what users get on both integration shapes.

**Sentinel logic at `kodi_device.py:1233-1238` is retained unchanged.** Users who explicitly select the `"thumbnail"` option (e.g., on a quirky integration where the channel logo lives at top-level) still get the bare-`special://`-wrap behavior from patch 44. Only the default changed.

**Migration note:** existing devices that completed setup under madalone.7 already have `"thumbnail"` persisted in their stored config JSON. The dataclass MISSING-default loop at `KodiConfigDevice.__post_init__` only fills fields that are absent — it doesn't migrate existing values. So madalone.7 → madalone.8 upgraders need either to:
1. Open setup, reconfigure (just confirm the new "Channel logo" default), and save; OR
2. Manually delete the `artwork_type_channels` line from `/data/config.json` and reload the integration.

Fresh installs and users who skipped madalone.7 get `"icon"` automatically.

**Why not auto-migrate the value:** writing migration logic for a 1-day-old default change adds runtime complexity for a single user-segment that needs a one-line config touch. The existing dataclass MISSING-default pattern is the documented migration mechanism; explicit re-setup is the documented workaround when defaults change.

**Breaking changes flagged:** none in code paths. The user-visible default change is the bug fix itself. The `"thumbnail"` option remains available — just not pre-selected.

---

## Patch 44c: `artwork_type_channels` setup-flow wiring fix (`v1.20.2-madalone.1`, 2026-07-23)

**Problem (surfaced by the v1.20.2 merge verification):** Patch 44 added `artwork_type_channels` to `config.py` (dataclass field) and `setup_fields.py` (the "Artwork type to display for PVR/Channels" dropdown) but **never wired it into `setup_flow.py`** — it was absent from all 5 config touch-points (initial-setup parse, `KodiConfigDevice` construction, reconfigure parse, reconfigure assign, reconfigure pre-populate). Effect: the setup wizard showed the dropdown but the chosen value was **never read or persisted** — `artwork_type_channels` stayed at the dataclass default (`"icon"`) no matter what the user picked. This also silently broke patch 44b's documented madalone.7→.8 migration **option 1** ("reconfigure and save") — saving never wrote the field, so only the hand-edit (option 2) actually changed it. Confirmed pre-existing (absent in the pre-merge tip `72a7835`) — **not** a v1.20.2 merge regression; the merge faithfully preserved the gap, and the 3-agent merge verification flagged it.

**Fix:** wired `artwork_type_channels` through all 5 `setup_flow.py` touch-points, mirroring the sibling `artwork_type_tvshows` exactly, plus the `KODI_DEFAULT_CHANNELS_ARTWORK` import (default `"icon"`, already defined in `setup_fields.py`). The dropdown now persists; "Channel logo" (`"icon"`) remains the default (patch 44b). No breaking changes — the field, its default, and the dropdown options are unchanged; only the previously-missing read/write path is completed. `ruff check` / `ruff format --check` / `py_compile` clean.

---

## Post-mortem: Patch 41 root cause (UC-Remote-UI v1.4.10, 2026-04-27)

The user-visible symptom that motivated patch 41 — "blank artwork on first activity-card open after integration reinstall, fixed by close+reopen" — turned out to be three layered bugs on the firmware side, all on UC-Remote-UI commit `1266974` and earlier (i.e. all pre-v1.4.10). Triangulation chain:

1. Integration emits `media_image_url=<data URI mime='image/jpeg' len=17211>` — confirmed via live ws capture against `/ws` channel `all`.
2. UC core configured-entity store has the populated value — confirmed via `GET /api/entities/kodi_driver.main.media_player.madteevee.local`.
3. Remote screen renders blank for 8+ minutes of kept-open card. Same data URI value the firmware had been ignoring is rendered correctly the moment the card is closed and reopened (synchronous subscribe-time push).

The asymmetry — *subscribe push works, post-subscribe `entity_change` doesn't* — landed the bug firmware-side. The firmware-side root cause (per parallel UC-Remote-UI session, 2026-04-27):

1. **Orphan `entityAdded` core-API signal**: `core.h:360` declared, `core.cpp:2142` emitted, `entityController.cpp` constructor never `QObject::connect`-ed it. Integration `NEW` events arrived but `m_entities` map stayed empty, so no future `CHANGE` event could find a target.
2. **Silent early-return on unknown-entity CHANGE**: `entityController.cpp:430` dropped any `CHANGE` for an entity not yet in `m_entities`. Combined with (1), every late `entity_change` was silently dropped after a fresh integration install.
3. **MediaComponent.qml missing `entityLoaded` listener**: when the QML mounted with `entityObj=null` (because `EntityController.load` was still in flight), nothing re-acquired the entity once load completed.

Close+reopen worked because closing tore down the QML state and reopening re-ran `Activity.qml`'s `includedEntityItem` delegate, which calls `EntityController.load()` — by that time UC core had the populated state.

**Fix shipped firmware-side: UC-Remote-UI v1.4.10** — reconnects the orphan signal, replaces the silent early-return with `load()` fallback, adds the missing `entityLoaded` listener to `MediaComponent.qml`. User-verified end-to-end on the UC Remote 3.

### Status of integration patches 41/42 after v1.4.10

- **Patch 41** (`_post_subscribe_refresh`): redundant on v1.4.10 firmware (which fixes the underlying delivery path correctly). Harmless no-op there because ucapi dedupes the second push when values are unchanged. Retained for users still on pre-v1.4.10 firmware.
- **Patch 42** (`_artwork_pending_retry` flag): independent integration-side bug fix (the deferred-retry-doesn't-actually-retry issue). Load-bearing on any firmware. Retained.

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

---

## Upstream Merge to v1.20.0 (2026-05-02)

Merged upstream `main` (tag `v1.20.0`, commit `d3ec217`) into `v1.18.13-patched` via `git merge --no-ff`. 50 upstream commits picked up; all 44 fork patches preserved through the merge.

**Strategy: merge, not rebase.** With 44 fork patches, rebasing would force per-commit conflict resolution against upstream's restructured `media_browser.py` for any patch touching that file. Merge consolidates the conflict resolution into one human-reviewed pass at the join point. Trade-off: history shows the Y-shape join instead of staying linear; rollback is a `git reset` to the backup branch (`backup/pre-v1.20.0-merge`).

**Upstream changes pulled in (the headline features):**
- **PR #20 (Serph91P)** — PVR / Addons browsing. New browse roots `kodi://pvr`, `kodi://pvr/tv`, `kodi://pvr/radio`, `kodi://addons`, `kodi://addons/video`, `kodi://addons/audio`. New `KodiObjectType` enums (`CHANNEL_GROUP`, `CHANNEL`, `ADDON`, `BROADCAST`). EPG `Now/Next` info as channel subtitles.
- **PR #21 (Serph91P)** — Favourites support. New `src/favorites.py` (104 LOC), new `kodi://favorites` browse root, `favorites_in_root` setup-flow checkbox, pinned-shortcuts handling in browse menu.
- Misc fixes: `media_browser.py` BBCode strip helper, 255-char `media_id` guard, two crash fixes in browse listings, `play_media` return value fix in `kodi_device.py`, connection-check `None`-safety, `reset_feature_cache` on new connection.

**Auto-merged cleanly (Git resolved both sides):** `CHANGELOG.md`, `src/config.py`, `src/const.py`, `src/kodi_device.py`, `src/media_player.py`, `src/pykodi/kodi.py`, `src/setup_fields.py`, `src/setup_flow.py`, `src/translations.py`, `test_connection.py`, `test_driver.py`. Upstream's edits all landed in regions our patches don't touch.

**Manually resolved (4 files):**
- `README.md` — kept ours verbatim (we'd already rewritten it for the fork; upstream's expansion can be selectively pulled in later if needed)
- `driver.json` — kept ours; bumped version to `1.20.0-madalone.1`, release_date to `2026-05-02`
- `.github/workflows/build.yml` — hybrid: kept our `PYTHON_VER: 3.11.13-0.4.0` + `permissions: contents: write` block; dropped upstream's `REGISTRY` / `IMAGE_NAME` env vars (no Docker job in the fork)
- `src/media_browser.py` — the hard one. 9 conflict regions, all merged in place (not via `--theirs` rebuild). See "Patches reworked against upstream's restructured browse code" below.

**Patches reworked against upstream's restructured browse code:**
- **Patch 16** (narrowed `except` clauses at 3 per-item iteration sites in `media_browser.py`) — kept ours verbatim, no upstream collision
- **Patch 25** (`video_only_browse_filter`) — kept ours' filter logic; the call sites at the FILE-output and source-subdirectory loops both adapted to upstream's new `BrowseMediaItem | None` return type from `get_item_from_file` (added `if sub is not None` guards)
- **Patch 30** (sidecar thumbnail detection) — `get_item_from_file` signature merged: now accepts BOTH upstream's `extract_thumbnail: bool` AND our `thumbnail_url: str | None` kwargs. New body logic: explicit `thumbnail_url` (sidecar) wins; otherwise fall back to upstream's internal extraction when `extract_thumbnail=True` (used for picture-source browsing). Module-level `_build_sidecar_map()` and `_find_sidecar_for_file()` helpers survived the merge intact.

**Lint:** black applied 1 trivial reformat (line that fit in 120 chars after Patch 25/30 merge); pylint 10/10, flake8 0 errors, isort clean.

**Smoke-tested on UC Remote 3 against Kodi 21.x (madteevee):** PVR Live TV browse, Addons browse + launch, Favourites browse, sidecar thumbnails on Sonarr-formatted folders, channel-art `"icon"` default on PseudoTV — all confirmed working on first deploy of `v1.20.0-madalone.1`.

**Branch:** `v1.18.13-patched` renamed to `v1.20.0-patched` to match new base.

**Rollback path:** backup branch `backup/pre-v1.20.0-merge` retained on both local and `origin` (= `mmadalone/integration-kodi`). To revert: `git reset --hard backup/pre-v1.20.0-merge` + delete the `v1.20.0-madalone.1` tag. Restoring the old tarball (`uc-intg-kodi-v1.18.13-madalone.8-aarch64.tar.gz`, retained at project root) is the deploy-side rollback.

---

## Patch 45: `MODE_TVGUIDE` Simple Command (`v1.20.0-madalone.3`) — ⚠️ RETIRED in v1.20.1-madalone.2 (2026-05-05)

> **⚠️ Retired one day after merge into v1.20.1-madalone.1, in v1.20.1-madalone.2.** The dedicated `MODE_TVGUIDE` simple command was a pure alias for `custom_command "key r"` — the user (and any other Harmony-style keymap user) can type `key r` in the activity-button "Send command" field and get the same `Input.ButtonEvent(button="r", keymap="KB")` routed through `<keyboard>` keymap, including the bidirectional toggle behavior from `<tvguide>` context. Same reasoning as patches 33 + 35: pure alias, no functional uniqueness. Removed from `KODI_ADVANCED_SIMPLE_COMMANDS`. The full design notes below are kept for historical context — they document the three-iteration arc (`GUI.ActivateWindow` → numeric `Input.ButtonEvent("61522")` → integration-side toggle → letter-name `Input.ButtonEvent("r")`) that led to discovering Kodi's keyboard-string translator behavior.

**File:** `src/const.py` (entry removed in v1.20.1-madalone.2)

**Problem:** The standard ucapi `Commands.GUIDE` is mapped at `const.py:304` as `ButtonKeymap("guide", "R1")` — it sends Kodi an `Input.ButtonEvent(button="guide", keymap="R1")`, which routes through Kodi's `<remote>` keymap. This works only if the user's Kodi has a `<remote>` keymap entry mapping the `guide` button to `activatewindow(tvguide)`.

Users running Kodi with a custom `<keyboard>` keymap (typical Harmony setup — Harmony emits a keyboard letter, e.g. `r`, when its Guide button is pressed; the user maps that letter in `keymap.xml` `<keyboard>` context to `activatewindow(tvguide)`) have a working keyboard mapping but no `<remote>` mapping. `Commands.GUIDE` does nothing for them. They also want the **bidirectional toggle behavior** their keymap defines:

```xml
<global>          <key id="61522">activatewindow(tvguide)</key>
<fullscreenvideo> <key id="61522">activatewindow(tvguide)</key>
<tvguide>         <key id="61522">activatewindow(fullscreenvideo)</key>
```

(Where `id="61522"` decodes as `KEY_VKEY | 'R'` = `0xF000 | 0x52` = `0xF052` — Kodi's internal code for keyboard letter `R` when received as a virtual-key event. Single letter "r" or "R" both produce this code through Kodi's keyboard string translator, which uppercase-normalizes and ORs `KEY_VKEY`.)

**Approaches considered (in order tested):**

1. **`GUI.ActivateWindow(window="tvguide")`** — "always opens, never closes." No toggle. Rejected.
2. **`Input.ButtonEvent(button="61522", keymap="KB")`** — pass the raw VK code as a numeric string. Kodi's `TranslateKeyboardString` should accept numeric strings via the `IsNaturalNumber` path, but on Kodi 21.x the resulting `CKey` event doesn't reach the same keymap dispatch as a physical keypress (likely the construction path differs from the kernel-keypress path). Empirically: no-op. Rejected.
3. **Integration-side toggle** — query Kodi for `currentwindow` via `GUI.GetProperties`, branch on the result, call the appropriate `GUI.ActivateWindow`. Built and tested as an interim. Works, but has 50ms extra latency and doesn't honor the user's keymap (so any custom keymap edits the user makes are bypassed). Rejected once approach 4 became viable.
4. **`Input.ButtonEvent(button="r", keymap="KB")`** — single-letter input goes through the letter-normalization + `KEY_VKEY`-OR path of Kodi's keyboard string translator, producing the right internal code (`0xF052` = 61522) to match the user's `<key id="61522">` binding directly. **Adopted.** Same shape as patch 33's `MODE_KEYPRESS_C` and patch 35's `MODE_KEYPRESS_ESC`.

**Implementation (final):**

```python
"MODE_TVGUIDE": {
    "method": "Input.ButtonEvent",
    "params": {"button": "r", "keymap": "KB"},
    "holdtime": None,
},
```

The user's `<keyboard>` keymap now controls behavior:
- From `<global>` or `<fullscreenvideo>` → opens guide
- From `<tvguide>` → exits to fullscreen video (the keymap's reverse-mapping handles the toggle)

Pure registry change; no new methods on `KodiDevice` or special cases in `media_player.py`.

**Why a new simple command and not just rebinding `Commands.GUIDE`:** `Commands.GUIDE` follows the upstream / ucapi-spec convention (route through Kodi's `<remote>` keymap, which is the canonical path). Rebinding it would deviate from that convention and surprise users whose `<remote>` keymap is correctly configured. The new `MODE_TVGUIDE` is additive.

**User impact:** works for users with a `<keyboard>` keymap binding the `r` key (or `<key id="61522">`) to a tvguide-related action. No-op for users without that binding — Kodi receives the keypress but has no action to route. Consistent with the rest of the keypress simple-command family (`MODE_KEYPRESS_C`, `MODE_KEYPRESS_ESC`).

**Naming:** `MODE_*` prefix matches the existing fork convention for additional simple commands (patches 31-35). Per UC's [command name patterns spec](https://github.com/unfoldedcircle/core-api/blob/main/doc/entities/entity_media_player.md#command-name-patterns), `KEYPRESS_*` would be more accurate (this is functionally `MODE_KEYPRESS_R`); flagged for future renaming when patches 31-35+ are eventually unified.

**Anti-pattern check:** does not trigger AP-K1 (no `Features.*` removal), AP-K2 (no artwork-block state mutation), AP-K3 (not a rendering symptom), AP-K4 (no PVR-shape config defaulting), or AP-K5 (single targeted addition, not 3+ patches in a release window).

**Regressions considered:** the new entry is additive in a dict; existing call sites for `Commands.GUIDE` and other advanced simple commands are unaffected.

---

## Upstream Merge to v1.20.1 (2026-05-04)

Merged upstream `main` (tag `v1.20.1`, commit `26692c4`) into `v1.20.0-patched` via `git merge --no-ff`. 8 upstream commits picked up, all from PR #23 (Serph91P, "kodi-favorites-and-livetv-improvements"). All 45 fork patches preserved through the merge.

**Upstream changes pulled in:**
- **`8ae31ff` `fix(favorites): rewrite Kodi PVR favourite URLs to internal media ids`** — favourites with PVR URLs were unusable for browsing; now rewritten to internal media ids.
- **`9ffd0cd` `feat(livetv): add show_channel_groups setup toggle (default on)`** — when off, the channel-groups level is skipped and channels are listed directly via the `allTV`/`allRadio` group. New checkbox in setup flow.
- **`4b9ac3c` `chore(ui): strip Kodi BBCode formatting from titles, subtitles and metadata`** — extends upstream's `strip_kodi_formatting` to subtitles + metadata. **Triggered our patch 1 deduplication** — see "Patch 1 deduplication" below.
- **`89de749` `fix(audit): guard against None label in os.path.splitext`**
- **`cadf7c8` `fix(lint): remove extra arg in get_item_from_channel call and apply black formatting`**

**Auto-merged cleanly (Git resolved both sides):** `src/config.py` (new `show_channel_groups` field at end of dataclass — clean append), `src/setup_fields.py` (new checkbox added to SETUP_FIELDS list — different field id from ours, no collision), `src/setup_flow.py` (5 touch-points for `show_channel_groups` — different field id, no collision), `src/media_browser.py` (upstream's BBCode-strip extension + favourite URL rewrite landed in regions our patches don't touch — clean), `src/favorites.py` (upstream-only file, took upstream's changes), `CHANGELOG.md` (auto-merged upstream's bullet additions into our preserved doc).

**Manually resolved (2 files):**
- `README.md` — kept ours verbatim (current-build line bumped to `v1.20.1-madalone.1` in subsequent doc-audit pass)
- `driver.json` — kept ours; bumped version to `v1.20.1-madalone.1`, release_date already `2026-05-04`

**Patch 1 deduplication (the big follow-up of this merge):** upstream's expanded `strip_kodi_formatting` covers titles + subtitles + metadata; our local `_strip_kodi_formatting` in `kodi_device.py` covered only `media_title` in real-time updates. Two functions doing equivalent work with slightly different regex coverage. Resolved by:
- Deleting `_KODI_MARKUP_RE` and `_strip_kodi_formatting` from `src/kodi_device.py`.
- Removing the now-unused `import re` (only the deleted regex used it).
- Switching the use site at `_update_states` to call `media_browser.strip_kodi_formatting(...)` directly (`media_browser` was already imported at module level).

Net result: –12 LOC in `kodi_device.py`, broader regex coverage at the playback-update site (handles `U`/`S`/`FONT` tags + whitespace-collapse that our local regex didn't), no local maintenance burden going forward. Phase 0 PR triage flagged this specific dedup as the "REWORK — drop our helper, reuse upstream's" recommendation for any future upstream PR — done as part of this merge instead.

**Lint:** black clean (no reformats); pylint 10/10, flake8 0 errors, isort clean.

**Smoke-tested on UC Remote 3 against Kodi 21.x (madteevee):** patch 45 `MODE_TVGUIDE` still toggles correctly (key 'r' keypress routed through user's `<keyboard>` keymap); upstream's new `show_channel_groups` setup toggle visible in reconfigure flow; favourites list with PVR URLs renders without errors.

**Branch:** `v1.20.0-patched` renamed to `v1.20.1-patched` to match new base.

**Rollback path:** backup branch `backup/pre-v1.20.1-merge` retained on both local and `origin`. To revert: `git reset --hard backup/pre-v1.20.1-merge` + delete the `v1.20.1-madalone.1` tag. The previous release tarball (`uc-intg-kodi-v1.20.0-madalone.2-aarch64.tar.gz`, retained at project root) is the deploy-side rollback.

---

## Upstream Merge to v1.20.2 (2026-07-23)

Merged upstream `main` (tag `v1.20.2`, commit `229d0b2`) into a new `v1.20.2-patched` branch (off `v1.20.1-patched` tip `72a7835`) via `git merge --no-ff`. 6 upstream commits picked up: one `ad758b9 "Fixes"` + five `"Linting"` commits (`4915018`, `ea75dc5`, `aa44b3b`, `bbd7791`, `229d0b2`). `min_core_api` unchanged (`0.20.0`) — no firmware floor raised. All 45 fork patches preserved.

**Decision context:** upstream v1.20.2 is a maintenance release (dependency refresh + a ruff/pyright tooling migration + one real fix + a browse-thumbnail tweak). Adopted as a **full merge** (not cherry-pick) to keep our files upstream-shaped for the ongoing outbound-PR track (`PHASE0-UPSTREAM-PR-TRIAGE.md`) — our patches must pass upstream's new ruff CI. Preceded by a 5-agent adopt analysis and followed by a 3-agent adversarial merge verification (both archived in session scratch).

### Dependency bumps (`requirements.txt` — adopted verbatim)
- `ucapi ~=0.6.0 → ~=0.7.0` — proactive pin refresh; upstream code uses no 0.7-only API, **no breaking changes** (all breaking changes were in 0.6.0, already behind us — see the 0.5.3→0.6.0 audit above). 0.7.0's one real feature (entity-type filtering of `get_available_entities`) is internal to `IntegrationAPI` and backward-compatible (falls back to unfiltered when the remote reports no supported types). **NOTE:** 0.7.0 internally rewrote WS message processing (asyncio consumer/producer/router queues) → on-device ws-capture required (patches 36-43 artwork timing / patch 41 subscribe).
- `aiohttp ~=3.13.5 → ~=3.14.1` — no API our patches use changed; 3.14 deprecates `BasicAuth` but removal is 4.0 (outside the pin). 3.14.1/.2 point releases *harden* patch-40's long-lived pooled session. Bumped together with jsonrpc-websocket.
- `zeroconf ~=0.148.0 → ~=0.150.0` — security hardening (LAN-driven OOM bounds) + additive `async_update_interfaces`; our `discover.py` sync path unaffected (NSEC-skip only touches `update_service`, our no-op).
- `jsonrpc-websocket >=3.2.0 → >=3.2.1` — switches to `asyncio.get_running_loop()`; the fix that keeps it working under aiohttp 3.14's loop-access deprecation. (We were likely already resolving 3.2.1 via the `>=3.2.0` floor.)

### Adopted upstream fix — Kodi credential URL-encoding (`ad758b9`, `pykodi/kodi.py`)
`image_auth_string = f"{username}:{password}@"` → `f"{quote(str(username), safe='')}:{quote(str(password), safe='')}@"`. **Real correctness fix:** a Kodi password containing `@ : / #` etc. previously produced a malformed `http://user:pass@host/image` authority → every artwork BasicAuth fetch 401'd → exhausted patch-37 retry budget + patch-42 deferred retry → art never loaded. `quote(safe="")` is byte-identical for alnum creds (zero regression) and only fixes the special-char case. `quote` already imported; kept upstream's `# pylint: disable=W1405` comment. Directly hardens the patch 28-44 artwork pipeline. (This is upstream's own fix, now part of the base — not a fork patch number.)

### `media_browser.py` — 3-way merge (upstream `ad758b9` × patches 25 + 30)
Upstream's browse change was three parts; resolved as:
- **(a) `KODI_WINDOWS_MAPPING`** dict replacing the favorites `match window` block — **adopted** (cosmetic; the favorites body auto-merged to `KODI_WINDOWS_MAPPING.get(window, ...)`, so the dict definition is required — kept alongside our patch-25/30 helper block).
- **(b) Kodi-reported `file['thumbnail']` preference** in `get_item_from_file` — **re-implemented on top of patch 30** as a 3-tier priority: `thumbnail_url` (patch-30 sidecar) → Kodi `file['thumbnail']` via `get_artwork_url()` → derive-from-file via `get_thumbnail_from_file()`. Patch-30's `thumbnail_url` param + directory-branch `thumbnail=thumbnail_url` preserved (upstream's directory branch has no thumbnail).
- **Video enhancement (fork-original, extends patch 30):** added `"thumbnail"` to the sources-block `Files.GetDirectory` `properties` and gave both sidecar call sites a `sidecar → Kodi-thumbnail → None` fallback (`extract_thumbnail=False` kept, so **no ffmpeg frame-extraction** — the heavy path patch 30 deliberately avoids). *Superseded by the v1.21.0 merge below: all call sites now pass `extract_thumbnail=True` and the derive-from-file step is gated by mimetype instead.* **AP-K4 caveat:** Kodi only populates `file['thumbnail']` for videos when `media=video` triggers its thumb extraction (i.e. when `video_only_browse_filter` is ON, patch 25); with it OFF the sources block uses default `media=files` → `file['thumbnail']` empty → sidecar-only (pre-merge behavior). Strictly additive, no regression. **Needs cross-source on-device test (library / real PVR / plugin).**
- **(c) smb-block `media='files'` + `thumbnail` property** — **taken as upstream's** (auto-merged; runtime no-op since `media=files` is Kodi's default and `extract_thumbnail` resolves False there). Harmless.

### Conflict resolutions (5 files)
- **`driver.json`** — kept fork version → `1.20.2-madalone.1`, release_date `2026-07-23`, `min_core_api` `0.20.0`.
- **`discover.py`** — **kept patches 11/16** narrow-except (`except (KeyError, AttributeError, UnicodeDecodeError)`) + debug log; adopted upstream's None-safe `.get()` idiom for the body (hybrid). Did NOT take upstream's broad `except Exception: pass`.
- **`kodi_device.py`** — kept patch-10 `retry(*, timeout=5)` signature (NO `bufferize`); took upstream's cosmetic line-wrap + `thumbnail is not None` narrowing in the movie-@smb poster branch.
- **`remote.py`** — took upstream's `command = str(command)` in the sequence loop (our patch-8 await already converged with upstream).
- **`media_browser.py`** — the 3-way merge above.

### Tooling migration — ruff + pyright (adopted from upstream)
Replaced `pylint`/`flake8`/`flake8-docstrings`/`black`/`isort`/`rich` with `ruff==0.15.21` + `pyright==1.1.411` + `pytest==9.1.1` + `pytest-asyncio==1.4.0` (`test-requirements.txt`), upstream's ruff/pyright `pyproject.toml`, and upstream's `python-code-format.yml` (ruff check + ruff format --check + pyright). Our `build.yml` untouched (upstream didn't change it).
- Our black@120 output was already ruff-shaped: `ruff format` touched only `kodi_device.py` (2 trivial hunks — `retry()` signature wrap + f-string spacing).
- `ruff check src/` net-new violations from our patches, all **suppressed inline** (keeping `pyproject.toml` byte-identical to upstream for merge cleanliness + so the suppressions travel with the patch in an upstream PR): `# noqa: S311` on the patch-17/37 `random.uniform` jitter lines; `# noqa: PTH122` on the patch-25/30 `os.path.splitext` sidecar helpers; patch-37's ambiguous `×`/`≈` comment chars replaced with `x`/`~=` (RUF002/003).
- **Real merge regression fixed:** upstream's linting removed `import os` from `media_browser.py` (it migrated its own code to `PurePath`), but our patch-25/30 helpers still use `os.path.splitext` → restored `import os` (was surfacing as `F821 Undefined name os`).
- **pyright is non-blocking in CI** (`continue-on-error: true`) until the ~22 strict errors (pre-existing `reportOperatorIssue` + patch-40/44 multi-language-string `reportImplicitStringConcatenation`) are triaged in a deps-installed venv. Flip the flag off to re-gate.

**Pre-push (updated):** `ruff check src/` + `ruff format --check src/` replaces the old four-tool pylint/flake8/isort/black pass. Both clean on this merge; `py_compile` clean.

**Skipped from upstream:** `test_connection.py` (upstream committed personal dev scratch — hardcoded `smb://jedi/Videos/`, French comments, a mid-function `exit(0)` — restored our version); `driver.json` version (fork carries `-madalone.N`).

**Corrected stale note:** the CLAUDE.md "Key Dependencies" line claiming a local ucapi wheel (`src/ucapi-*.whl`) — there is none; ucapi is pulled from PyPI.

**Rollback path:** the whole merge lives on the fresh `v1.20.2-patched` branch; `v1.20.1-patched` (tip `72a7835`, tag `v1.20.1-madalone.2`) is untouched. To abandon: `git checkout v1.20.1-patched && git branch -D v1.20.2-patched`. The previous release tarball is the deploy-side rollback.

**On-device validation — ✅ DONE 2026-07-24, tagged `v1.20.2-madalone.1` at `62a61de`.** The checklist that was run: (1) 60s `tools/diag_ws_capture.py` post-deploy focused on artwork (patches 36-43) + subscribe (patch 41) to confirm ucapi 0.7.0's WS-queue rewrite didn't shift Events.UPDATE timing; (2) Kodi WS connect + BasicAuth still authenticate (jsonrpc-websocket 3.2.1 over aiohttp 3.14); (3) special-char Kodi password → artwork loads (validates the cred fix); (4) video/picture browse thumbnails with `video_only_browse_filter` ON and OFF (validates the media_browser 3-way merge, AP-K4).

---

## Upstream Merge to v1.21.0 (2026-08-28)

Merged upstream `main` (tag `v1.21.0`, commit `2ecd63b`, released 2026-08-28) into a new `v1.21.0-patched` branch (off `v1.20.2-patched` tip `62a61de` = tag `v1.20.2-madalone.1`) via `git merge --no-ff` → merge commit `b019648`. One upstream commit: *"Added support for upcoming improved Kodi browsing (artwork extraction from sources and favorites)"*, +47/−40 across `driver.json`, `src/media_browser.py`, `test_connection.py`, `test_driver.py`. `min_core_api` unchanged (`0.20.0`). No `kodi_device.py` / `pykodi/` / config / setup / dependency / CI changes — playback artwork (patches 36-44) is untouched and shares no state with `media_browser`. `favorites.py` is untouched despite the commit title; the "favorites" benefit is indirect (favourite paths that land in the `smb://` branch). All 42 active fork patches preserved (3-lens adversarial verification, each reported problem independently refuted or confirmed — it caught one real regression in the first cut, the directory-art case below, fixed before tagging).

**Decision context:** assessed by a 42-agent adversarial workflow before merging (3 lenses × per-finding refuters). Verdict: merge-worthy, low urgency — small, clean, no breaking changes, and deferring would only keep three duplicated thumbnail chains alive (AP-K5) while growing the outbound-PR divergence. The headline feature is **gated on Kodi 22** (below), so the merge is mostly forward-compatibility plus two modest improvements that apply on Kodi 21 today.

### What upstream changed (`src/media_browser.py`, 5 hunks)
- **`get_item_from_file`:** new tier — `file["art"]` → `get_artwork()` (poster > fanart > album.thumb > thumb; `icon` deliberately not walked) → `get_artwork_url()`; then Kodi's reported `thumbnail`; then derive-from-file via `get_thumbnail_from_file()` **only when `mimetype` starts with `image/`**. Upstream's comment: a video-backed `image://` URL makes Kodi decode the media when the remote fetches it, which can exhaust Kodi on large network files.
- `extract_thumbnail=True` at all three `Files.GetDirectory` / `Files.GetSources` call sites (was `False`, a constant-False `kodi_type != "files"`, and `media == pictures` respectively).
- `"art"` added to the `smb://`/`nfs://`/`multipath://`/`special://` branch `properties`.
- `test_driver.py`: `get_locale()` `None` guard (+2 lines). `driver.json`: version bump only.

### Kodi dependency — the feature is inert until Kodi 22
Release note: *"requires an upcoming Kodi 22 release, once my PR will be merged and released"* → [xbmc/xbmc#28244](https://github.com/xbmc/xbmc/pull/28244) ("Handle extraction of library metadata for JSON RPC Files.GetDirectory": when `media=files` and a non-basic property such as `art`/`thumbnail` is requested, Kodi runs the video/music-library lookup; JSONRPC schema 13.16 → 13.17). Status at merge time: **open / unmerged**, milestone *Piers 22.0 RC 1*, approved by one reviewer (reardonia, 2026-08-24) on head `81e8e3c`, Jenkins red on that head (author attributes it to a stale merge ref — unverified), other reviews pending, four design iterations so far (response shape may still move). Kodi 22 was at beta1 (2026-06-21); final realistically Nov 2026 – Jan 2027; the 21.x JSON-RPC schema is frozen at 13.5.0, so this can never reach Omega. On Kodi 21.3 (madteevee) requesting `art` on `media=files` is **schema-valid and harmless** — `List.Fields.Files` already lists `art`, Kodi returns `art: {}`, and the `plugin://` addondir branch was already sending it in production. Things to re-check when #28244 ships: its stacked-path `file` rewrite, multi-episode files returned as `episodes://<path>?show=N` directories (browsable, but bad back-navigation), long percent-encoded SMB paths vs `MAX_MEDIA_ID_LEN`. Note the fork's `smb://` branch (`media=files` + `thumbnail`) will trigger that library lookup on 22+ regardless of this merge.

### `media_browser.py` — 3-way merge (upstream `2ecd63b` × patches 25 + 30)
Three conflict blocks, all inside patch 25/30 regions; the `smb://` branch hunks (`properties` + call) and `test_driver.py` auto-merged.
- **`get_item_from_file` (~L469-486):** kept the fork signature (`extract_thumbnail` + `thumbnail_url`), docstring, 255-char `media_id` guard and directory branch (`thumbnail=thumbnail_url`). Upstream's chain was inserted *under* the patch-30 guard `if thumbnail_url is None and extract_thumbnail:` using `thumbnail_url` as the accumulator (no new annotated local), and placed **ahead of the directory early-return** so folders keep Kodi-supplied art (videodb:// nodes, upnp:// containers). Resulting precedence for files *and* folders: **sidecar (patch 30) > art-dict > Kodi thumbnail > derive-iff-image**; derive does not fire for a folder because no mimetype Kodi assigns to one is `image/*` (`x-directory/normal`, or an archive/playlist type for file-folders — verified against `CFileItem::FillInMimeType` / `CMime`). Small behaviour note: a folder whose art dict has `fanart` but no `poster` now resolves at the art tier (16:9 fanart) instead of Kodi's square `thumb` — upstream's verbatim ordering, same as movies; eyeball a videodb/upnp folder on device so it is not mistaken for a bug. **Regression caught by verification:** the first cut left the walk *after* the directory `return`; combined with the sidecar-only pre-compute (the sidecar map skips folders), directory entries at the `kodi://sources` loop lost the Kodi-reported thumbnail they had in `v1.20.2-madalone.1` (plain filesystem folders were never affected — JSON-RPC `Files.GetDirectory` does no folder.jpg lookup; only Kodi-supplied container art was). Fixed in the follow-up commit before tagging.
- **`Files.GetSources` loop (~L1082-1100) and `kodi://sources` loop (~L1355-1372):** kept `_video_only`, `_build_sidecar_map` pre-scan and the #4c companion-file `continue` verbatim. Collapsed the two duplicated `sidecar → thumbnail → None` pre-computes from the v1.20.2 merge — and the `if media == PICTURES: extract_thumbnail=True / else: sidecar` split at the sources loop — into `_thumb_url = get_thumbnail_from_file(_sidecar) if _sidecar else None` + `get_item_from_file(..., extract_thumbnail=True, thumbnail_url=_thumb_url)`. `get_item_from_file` now owns the fallback chain (AP-K5 cleanup: three chains → one). The pre-compute had to drop its `elif file.get("thumbnail")` arm, otherwise thumbnail would beat art. Calls kept in multi-line keyword form (the one-liner is 121 columns → ruff E501).
- **Fork companion edit upstream did not make:** `"art"` also added to the `kodi://sources` `Files.GetDirectory` `properties` (~L1330; upstream left that block at `["mimetype", "thumbnail"]`). Rationale: with `video_only_browse_filter` ON (patch 25 #4a) that request already sends `media=video`, so Kodi 21 returns a populated `art` dict for library-matched files → **library movies now show their poster while browsing instead of an extracted frame / nothing**; episodes are unchanged (`get_artwork` returns `thumb`). This is the only fork-decided behaviour change in the merge; without that one word the art tier is dead at that site and behaviour is byte-for-byte pre-merge. **Revert = delete `"art"` from that list.**

### Conflict resolutions (3 files)
- **`driver.json`** — fork version → `1.21.0-madalone.1`, `release_date` `2026-08-28`, `min_core_api` `0.20.0`; fork description (3 locales) + developer blocks kept.
- **`media_browser.py`** — the 3-way merge above.
- **`test_connection.py`** — keep-ours (upstream hunk is again the author's dev scratch — Shield IP, `smb://jedi/Videos/Download` probe; it does not even apply to our tree). Not imported by `src/`, not bundled.

### Runtime effect on Kodi 21.3 (today)
- `smb://`/`nfs://` listings: image-mimetype files (pictures, and sidecar `.jpg` / `poster.jpg` inside video folders) gain derived thumbnails (+1 `/image/` GET per image file per page). Videos unchanged (`art: {}`, `thumbnail: ""` on Omega; the mimetype gate blocks derive).
- `kodi://sources` sub-directories with `video_only_browse_filter` ON: library-matched movies show poster art (see companion edit). OFF: sidecar-or-nothing, as before.
- Derive-from-file for non-image mimetypes is now structurally impossible — closes one reachable fork edge (a favourite created from Kodi's Pictures window pointing at a local folder with videos, `video_only` ON → previously emitted `image://<video>/` URLs).
- 0 added JSON-RPC calls; `plugin://` (addondir branch) and playlist listings untouched; no entity feature / attribute / stored-config changes → **no breaking-change flags**.

### Refuted during review (for the record)
- "Patch 30 already avoided the ffmpeg path" — no: the pictures-only gate (`2ec8ebc`) and the constant-False `kodi_type != "files"` (`ad758b9`) are upstream's; patch 30 rejected `image://video@` on artwork-*quality* grounds.
- "`get_artwork` on an episode returns the show poster" — it returns the episode `thumb` (`tvshow.*`/`season.*` keys are not read).
- "`plugin://` listings gain artwork" — no: the addondir branch intercepts before the `smb://` branch.
- "the `smb://` hunk is redundant with patch 30" — it is the only thumbnail logic that branch has (see the patch-30c gap note in the Patch 30 section).

### Tooling
`ruff check src/` + `ruff format --check src/` clean. `pyright src/` byte-identical to the pre-merge baseline (6 pre-existing errors: `reportImplicitStringConcatenation` ×4, `reportUnusedFunction` ×2 on `_is_blocked_video_only_extension` / `_build_sidecar_map` — with `reportGeneralTypeIssues = false` pyright silently bails out of the whole ~920-line `browse_media` with *"Code is too complex to analyze"* (and of `kodi_device.py:1074`) — so the two `reportUnusedFunction` errors are false positives (both helpers ARE called, from inside the skipped body) and **none of the five `get_item_from_file(` call sites is type-checked**; only ruff and the interpreter validate the keyword wiring there. The "6 pre-existing" baseline is really 4 real + 2 artifacts of that bailout — worth a note in the pyright-triage item). Line endings kept LF (a Windows text-mode rewrite briefly flipped `media_browser.py` and `driver.json` to CRLF — caught by the whole-file diff and normalized before commit). Built with the standard PyInstaller container command; tarball `kodi-integration-v1.21.0-madalone.1.tar.gz`.

**Rollback path:** the merge lives on the fresh `v1.21.0-patched` branch; `v1.20.2-patched` (tip `62a61de`, tag `v1.20.2-madalone.1`) is untouched. To abandon: `git checkout v1.20.2-patched && git branch -D v1.21.0-patched`. The previous release tarball is the deploy-side rollback.

**Pending on-device validation (BEFORE tagging `v1.21.0-madalone.1`):**
- **V0** Deploy per CLAUDE.md (uninstall via web UI → upload tarball → setup against madteevee by IP); 60 s `tools/diag_ws_capture.py` post-deploy.
- **V1** `kodi://sources/videos`: source list renders, back item present (`GetSources` loop — expected no-op, no thumbnails).
- **V2** `smb://` Sonarr video folder: videos show **no** thumbnail (unchanged); `-thumb.jpg` / `poster.jpg` entries now show derived thumbnails; Kodi log shows no `image://video@` requests.
- **V3** `smb://` picture folder: pictures gain thumbnails; page twice to confirm pagination + fetch load.
- **V4** Local-path source, `video_only` OFF: Sonarr folder → `<base>-thumb.jpg` sidecar wins; video without sidecar → none; pictures source → derived; `.nfo`/`.srt` visible.
- **V5** Local-path source, `video_only` ON: library-matched movie shows **poster** (the companion edit); episodes show episode thumb; `.nfo`/`.srt`/`.sub` hidden (#4c); pictures root hidden (#4b). If the poster is unwanted, delete `"art"` at that one site.
- **V6** Mimetype-gate edge: favourite created from the Pictures window → local folder containing videos, `video_only` ON, browse from UC3 → videos get no thumbnail.
- **V7** `plugin://` addon listing and a playlist listing unchanged.
- **V8** A favourite whose window maps to `kodi://sources/*` (videos/music/pictures — `KODI_WINDOWS_MAPPING`) renders with folder art where Kodi supplies it. Note: a `pvr://recordings` / `tvrecordings`-window favourite keeps its raw URL media_type and hits the pre-existing unsupported-type warning — not reachable by this code path; unchanged from madalone.1.
- **V9** Playback artwork regression: library movie, real PVR channel, PseudoTV channel, Sonarr file (play-time sidecar 30b) → identical to `v1.20.2-madalone.1`; no flicker over 5 min.
- **V10** Integration logs (`http://192.168.2.204:8088/api/integration-logs/entries?service=core`, filter `kodi_driver`): no new WARNING/ERROR from `media_browser`; reconfigure flow opens and saves with the existing config.
- **V11** Only then: `git tag -a v1.21.0-madalone.1` + push branch and tag.

---
