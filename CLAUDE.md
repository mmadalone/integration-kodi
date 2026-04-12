# CLAUDE.md -- Kodi Integration for UC Remote 3 (Patched Fork)

## Project Identity

Patched fork of [albaintor/integration-kodi](https://github.com/albaintor/integration-kodi) (v1.18.7) for the **Unfolded Circle Remote 3**. Python 3.11 async integration driver using the `ucapi` library.

**Owner:** madalone
**Device:** UC Remote 3 at `192.168.2.204`, PIN `6984`
**Upstream:** `albaintor/integration-kodi` tag `v1.18.7`
**Language:** Python 3.11 (async/await, `ucapi`, `aiohttp`, Kodi JSON-RPC)
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

## Build & Deploy

### Build (cross-compile for ARM64)

```bash
cd "/Users/madalone/_Claude Projects/integration-kodi-patch"
docker run --rm --user=$(id -u):$(id -g) \
  -v "$(pwd)":/sources -w /sources \
  docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0 \
  bash -c "pip install --user -r requirements.txt && pyinstaller --collect-submodules zeroconf --clean -y --onedir --name driver src/driver.py"
```

**IMPORTANT:** Must run `pip install` before PyInstaller inside the container. PyInstaller bundles installed packages -- without `pip install` first, the binary will be missing dependencies (`ucapi`, `websockets`, `httpx`, etc.) and crash on the remote with "Connection refused (os error 111)".

Output: `dist/driver/` (binary + `_internal/`)

### Package

```bash
rm -rf /tmp/kodi-pkg && mkdir -p /tmp/kodi-pkg/bin
cp dist/driver/driver /tmp/kodi-pkg/bin/
cp -r dist/driver/_internal /tmp/kodi-pkg/bin/
cp driver.json /tmp/kodi-pkg/
cp kodi.png /tmp/kodi-pkg/
cd /tmp/kodi-pkg
tar czf "/Users/madalone/_Claude Projects/integration-kodi-patch/kodi-integration-v<VERSION>.tar.gz" .
```

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

All patches documented in detail in `KODI-INTEGRATION-PATCHES.md`.

| # | Name | Files | Summary |
|---|------|-------|---------|
| 1 | Label Formatting Tag Stripping | `kodi_device.py` | Strips Kodi BBCode markup from media titles |
| 2 | Deferred Artwork Re-poll | `kodi_device.py` | +3s deferred re-poll on connect for artwork |
| 3 | Stop Handler Cleanup | `kodi_device.py` | Clears stale media info on playback stop |
| 4 | Artwork Subscribe Fix | `kodi_device.py` | Uses `media_artwork` in `attributes` property |
| 5 | None Power Off Option | `const.py`, `kodi_device.py` | Adds "None (disabled)" to power-off dropdown |
| 6 | Suppress Volume Overlay | `config.py`, `kodi_device.py`, `setup_fields.py`, `setup_flow.py` | Opt-in: hides remote volume popup, uses TV OSD |
| 7 | eval() Security Fix | `media_player.py` | Replaces `eval()` with `ast.literal_eval()` |
| 8 | Missing await Fix | `remote.py` | Adds `await` to command sequence path |
| 9 | Media Position Fix | `kodi_device.py` | `elapsed_time.seconds` → `total_seconds()` |

### Patch 6 Details (Suppress Volume Overlay)

Configurable option `suppress_volume_overlay` (default `False`). When enabled:
- Removes `Features.VOLUME` from advertised features (keeps `VOLUME_UP_DOWN`, `MUTE_TOGGLE`)
- Stops emitting `MediaAttr.VOLUME`/`MediaAttr.MUTED` to the media player entity
- Sensor entities (`KodiSensorVolume`, `KodiSensorMuted`) still update via separate keys
- Internal state tracking preserved (needed for mute toggle logic)
- Also fixes upstream bug: `on_volume_changed` comparison was always False (line 469)

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

Documented in `KODI-INTEGRATION-PATCHES.md` under "Companion Firmware Fixes". These live in the separate [UC-Remote-UI project](/Users/madalone/_Claude Projects/UC-Remote-UI/), not here:
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
