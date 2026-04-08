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
