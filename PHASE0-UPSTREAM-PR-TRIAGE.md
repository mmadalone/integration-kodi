# Phase 0 — Upstream PR triage

> **Status (2026-05-02):** Pre-merge analysis. The fork has since been **merged with upstream `v1.20.0`** (commit `d3ec217`); see `KODI-INTEGRATION-PATCHES.md` "Upstream Merge to v1.20.0" section. The conflict assessments and rebase-difficulty notes below were written against `08b2a2c` and are now historical. The per-patch *upstream-PR* recommendations (which patches to send albaintor as PRs, in what order) remain valid — they were the planning work that needs revisiting before any actual upstream PRs are opened.

Pre-flight inventory of fork patches against `upstream/main` (at the time of writing: `08b2a2c`, 6 commits past `v1.18.13`). Output: a per-patch decision on whether to drop / rebase mechanically / rework / hold.

## Upstream divergence summary

Files upstream changed since `v1.18.13` (8 files):

| File | Upstream Δ | Our Δ | Conflict |
|---|---|---|---|
| `src/media_browser.py` | +340 (PVR/Addons + BBCode strip + plugin:// nav) | +182 (filter + sidecar) | **HIGH** |
| `src/setup_fields.py` | +6 (PVR/Addons categories) | +27 (4 new fields) | LOW (no field-id collisions) |
| `src/const.py` | +4 enum values | +44 (simple commands + None power-off) | LOW (different sections) |
| `src/pykodi/kodi.py` | +35 (PVR/Addons RPC methods) | +10 (narrowed excepts + `limits=` arg) | LOW–MEDIUM |
| `src/translations.py` | +8 | unchanged | none |
| `CHANGELOG.md` | trivial | rewritten | trivial |
| `README.md` | trivial | rewritten | trivial — README isn't part of upstream PRs |
| `driver.json` | bumped | bumped further | trivial |

Files only we changed (clean for upstream-PR purposes): `kodi_device.py`, `driver.py`, `config.py`, `setup_flow.py`, `sensor.py`, `selector.py`, `remote.py`, `media_player.py`, `discover.py`.

## Per-patch decisions

### Tier A — Critical correctness / security

| Patch | Decision | Notes |
|---|---|---|
| 7. `eval` → `literal_eval` | **APPLY** | `media_player.py` only; clean apply |
| 8. Missing `await` | **APPLY** | `kodi_device.py`; clean |
| 9. Media position fix | **APPLY** | `kodi_device.py`; clean |
| 12. Async lock race fix | **APPLY** | `kodi_device.py`; clean |
| 14. Sensor `raise` → `return` | **APPLY** | `sensor.py`; clean (one line) |
| 15. `custom_command` BAD_REQUEST | **APPLY** | `media_player.py`; clean |
| 22. Kodi <22 chapter compat | **APPLY** | `kodi_device.py`; clean |
| 23. `any()` not `all()` filter | **APPLY** | `kodi_device.py`; clean |

Tier A target PR: `upstream-prs/critical-fixes`. All 8 patches in files upstream didn't touch. Should rebase mechanically with zero conflicts.

### Tier B — Reliability

| Patch | Decision | Notes |
|---|---|---|
| 17. Reconnect delay jitter | **APPLY** | `kodi_device.py`; clean |
| 18. `KodiConfigDevice.__post_init__` validation | **APPLY** | `config.py`; clean |
| 19. Empty select/sensor attrs on subscribe | **APPLY** | `selector.py` + `sensor.py`; clean |
| 20. Select push robustness | **APPLY** | `selector.py`; clean |
| 21. Gate `OPTIONS` push | **APPLY** | `selector.py`; clean |
| 24. Watchdog state-refresh safety net | **APPLY** | `kodi_device.py`; clean |

Tier B target PR: `upstream-prs/reliability-fixes`. Same files as Tier A; should rebase mechanically.

### Tier C — Title / artwork base

| Patch | Decision | Notes |
|---|---|---|
| 1. BBCode stripping | **REWORK — drop our helper, reuse upstream's** | Upstream `444e9b6` added `strip_kodi_formatting()` in `media_browser.py` for browse labels. Their regex is strictly broader (covers `U`/`S`/`FONT`, plus whitespace-collapse). Our use site (media_title in `_update_states`) is different but equivalent enough that we should `from media_browser import strip_kodi_formatting` and drop our local `_KODI_MARKUP_RE`/`_strip_kodi_formatting`. PR title: "refactor: reuse `strip_kodi_formatting` for media_title". |
| 2. Deferred artwork re-poll (+3s on connect) | **APPLY** | `kodi_device.py`; clean |
| 3. Stop handler cleanup | **APPLY** | `kodi_device.py`; clean |
| 4. Artwork subscribe fix (`media_artwork` in `attributes`) | **APPLY** | `kodi_device.py`; clean |

Tier C target PR: `upstream-prs/title-artwork-base`. Patch 1 is the refactor angle (deduplicate); 2/3/4 are independent bug fixes.

### Tier D — Artwork resolution

| Patch | Decision | Notes |
|---|---|---|
| 28. Broader artwork fallback chain | **APPLY** | `kodi_device.py` only; clean |
| 29. Placeholder filter + HTTP status validation | **APPLY** | `kodi_device.py`; clean |
| 30. Sidecar thumbnail detection | **REWORK — extend `get_item_from_file` signature carefully** | Our patch 30 changed `get_item_from_file(file, media_type, thumbnail_url=None)` — adds an explicit override. Upstream changed the same method to add `extract_thumbnail=True` param + apply `strip_kodi_formatting` on labels. Merge both: `get_item_from_file(file, media_type, extract_thumbnail=True, thumbnail_url=None)` where `thumbnail_url` overrides if provided, else `extract_thumbnail` dictates. Module-level `find_sidecar_for_file()` and `_build_sidecar_map()` helpers add cleanly. The use-site at our line 688 in browse_media has to be reapplied against upstream's restructured browse method (now uses `Paging` not `PaginationOptions` + has `_filter_optional_roots`). Mechanical hand-rebase, ~20 LOC of careful merge. |
| 44. `artwork_type_channels` config field | **APPLY** | New 4-way `media_type` branch in `kodi_device.py:1209-1218` adds the `MediaContentType.CHANNEL` arm — separate config knob (default `"icon"`, set in madalone.8) so PVR / PseudoTV channels get the channel logo (`art.icon`) instead of inheriting the generic `artwork_type` (default `"thumb"` → resolves to embedded show poster on PseudoTV). Adds a `"thumbnail"` sentinel that reads top-level `item['thumbnail']` directly with bare-`special://`-wrap into `image://...` for the addon-path opt-in case. **Critical for the upstream PR:** ship the `.8` default (`"icon"`), not the `.7` default (`"thumbnail"`). The `"thumbnail"` default was wrong for real PVR — `art.icon` is the channel logo on both PseudoTV (`image://special://...pseudotv.../logos/<channel>.png/`) and real PVR (`image://pvrchannel_tv@<encoded>/`), while top-level `thumbnail` is structurally inverted (channel logo on PseudoTV; EPG program-art on real PVR). New `setup_fields.py` dropdown + new `KodiConfigDevice.artwork_type_channels` field. Conflict risk: LOW–MEDIUM (`setup_fields.py` upstream Δ is +6 lines for PVR/Addons categories, no field-id collisions). |

Tier D target PR: `upstream-prs/artwork-resolution`. Patch 30 is the rebase risk in this whole effort.

### Tier E — Artwork download path hardening

| Patch | Decision | Notes |
|---|---|---|
| 36. Partial-update emit semantic | **APPLY** | `kodi_device.py`; clean |
| 37. Inline 3-attempt retry budget | **APPLY** | `kodi_device.py`; clean |
| 38. Item-identity guard | **APPLY** | `kodi_device.py`; clean |
| 39. Magic-byte MIME sniff | **APPLY** | `kodi_device.py`; clean |
| 40. Shared `aiohttp.ClientSession` + `artwork_timeout_seconds` field | **APPLY w/ rebase of `setup_fields.py` + `setup_flow.py`** | `kodi_device.py` clean; `config.py` clean; `setup_fields.py` adds a number field with no id collision (insert near upstream's existing `download_artwork` checkbox); `setup_flow.py` 5 touch-points clean. |
| 42. `_artwork_pending_retry` flag | **APPLY** | `kodi_device.py`; clean |

Tier E target PR: `upstream-prs/artwork-download-hardening`. The whole tier coheres into one PR — patches 36/37/38/39 are interdependent; 40 brings the config knob; 42 fixes the deferred-retry bug introduced by 36. Bundle as one. ~250 LOC + setup field + setup flow wiring.

### Tier F — New user-facing options

| Patch | Decision | Notes |
|---|---|---|
| 5. "None" power-off command | **APPLY** | `const.py` (one line in `KODI_POWEROFF_COMMANDS`) + `setup_fields.py` already lists it via the dropdown. Clean. |
| 25. `video_only_browse_filter` | **REWORK — integrate with upstream's `_filter_optional_roots`** | Our static `_VIDEO_ONLY_BLOCKED_PREFIXES` filter doesn't know about `kodi://addons/audio` (added by upstream PR #20). Two options: (a) extend our prefix list to include `kodi://addons/audio` and accept that we statically hide it whenever the toggle is on; (b) integrate with upstream's existing `_filter_optional_roots()` so the filter is one method. (b) is cleaner. ~40 LOC of careful merge. |
| 26. `suppress_unsupported_command_errors` | **APPLY** | `kodi_device.py` + `config.py` + `setup_fields.py`/`setup_flow.py`; clean. |

Tier F target PR(s): one option per PR is fine, or bundle as `upstream-prs/setup-options`. Patch 25 is the rebase work; 5 and 26 are mechanical.

### Tier G — Code quality

| Patch | Decision | Notes |
|---|---|---|
| 10. Dead code + dependency cleanup | **APPLY (cautiously)** | `kodi_device.py`; some changes may already be obsolete given upstream's evolution. Re-review before submitting. |
| 11. Exception handling hardening | **APPLY** | `pykodi/kodi.py` + `kodi_device.py`; **upstream still has bare `except Exception: pass` at the same locations** — confirmed via diff. Our patch supersedes those directly; clean apply. |
| 13. Fire-and-forget task observability | **APPLY** | `kodi_device.py`; clean |
| 16. Narrow remaining bare excepts | **APPLY** | `kodi_device.py`; same as 11, supersedes upstream's bare excepts |

Tier G target PR: `upstream-prs/exception-hardening` (bundles 11+16 as one focused PR; can include 13 for task observability). Patch 10 separately (`upstream-prs/dead-code-cleanup`) since cleanup is more cautious.

### Tier H — Simple commands

| Patch | Decision | Notes |
|---|---|---|
| 31. `MODE_CONTEXT_MENU` | **HOLD** | Upstream `Unreleased` CHANGELOG: "Rename the predefined simple commands to match expected UC name patterns" — so they're planning a rename pass. Our `MODE_*` prefix may not match their target convention. **Open an issue first** with the maintainer asking for the target naming convention before committing the upstream-rebase work for these. |
| 32. `MODE_PLAY_SELECTED` | **HOLD** | Same as 31 |
| 33. `MODE_KEYPRESS_C` | **HOLD** | Same as 31 |
| 34. `MODE_CODEC_INFO` / `MODE_PLAYER_DEBUG` / `MODE_SYSTEM_MENU` | **HOLD** | Same as 31 |
| 35. `MODE_KEYPRESS_ESC` | **HOLD** | Same as 31 |

Tier H is on hold pending maintainer input.

### Skip (don't submit upstream)

| Patch | Decision | Reason |
|---|---|---|
| 6. Suppress volume overlay (original) | **SKIP** | Reverted by patch 27; net no-op vs upstream |
| 27. Deprecate `suppress_volume_overlay` | **SKIP** | Reverts patch 6; submitting either is noise |
| 41. `_post_subscribe_refresh` | **SKIP** | Was a workaround for a firmware bug fixed in **UC-Remote-UI v1.4.10** (2026-04-27). On modern firmware it's a harmless no-op. Marginal value upstream; the maintainer would reasonably ask "what does this do?" and we'd have to explain a firmware bug they'd consider out of scope. |

## PR sequencing recommendation

| # | Branch | Tiers | Patches | Conflict risk | Effort |
|---|---|---|---|---|---|
| 1 | `upstream-prs/critical-fixes` | A | 7, 8, 9, 12, 14, 15, 22, 23 | NONE | ~1 hour |
| 2 | `upstream-prs/reliability-fixes` | B | 17, 18, 19, 20, 21, 24 | NONE | ~1 hour |
| 3 | `upstream-prs/exception-hardening` | G (subset) | 11, 13, 16 | LOW (supersedes upstream's bare excepts) | ~30 min |
| 4 | `upstream-prs/title-artwork-base` | C | 2, 3, 4 + Patch 1 refactor | LOW (refactor for 1) | ~1 hour |
| 5 | `upstream-prs/artwork-resolution` | D | 28, 29, 30, 44 | **MEDIUM-HIGH** (patch 30) | ~2-3 hours |
| 6 | `upstream-prs/artwork-download-hardening` | E | 36, 37, 38, 39, 40, 42 | LOW (kodi_device clean) + MEDIUM (setup_fields rebase) | ~2 hours |
| 7 | `upstream-prs/setup-options` | F | 5, 26 | LOW | ~30 min |
| 8 | `upstream-prs/video-only-browse` | F | 25 (reworked) | MEDIUM | ~1-2 hours |
| 9 | `upstream-prs/dead-code-cleanup` | G | 10 | LOW (after re-review) | ~30 min |
| H | (held) | H | 31-35 | depends on maintainer's rename plan | TBD |

Total upstream-applicable patches: **31** (out of 44). Skipped/held: **5 SKIP + 5 HOLD = 10**.

## Pre-PR-1 actions

1. **Open a GitHub issue** on `albaintor/integration-kodi` describing intent ("series of bug-fix PRs from a fork that's been live-debugging the integration on a UC Remote 3"). Sets expectations and gives maintainer a chance to nudge scope.
2. **Verify the PR-3 (exception hardening) supersedes upstream cleanly** — confirmed via diff that upstream's `pykodi/kodi.py` still has bare `except Exception: pass` at the same locations our patches narrow.
3. **Re-test patch 1 mechanics on a local branch** — confirm `from media_browser import strip_kodi_formatting` works in `kodi_device.py` and produces the same media_title behavior.

## Risk register (open items)

- **Patch 30 sidecar detection** is the highest-risk rebase due to upstream's `media_browser.py` rewrite. Plan for ~3 hours of careful re-merge. May need to ask maintainer if they'd accept it as a follow-up.
- **Patch 25 video_only_browse_filter** also touches `media_browser.py`; the `_filter_optional_roots` integration needs careful design.
- **Tier H simple commands** are blocked on maintainer's naming-convention plan. Don't burn rebase effort on them speculatively.
- **PR-1 cadence** — if maintainer takes >2 weeks to review PR-1, hold PR-2 onward to avoid stale work.

## Phase 0 outcome

Most of the fork's work transfers cleanly. The artwork pipeline (Tiers C+D+E) is the most valuable thing to upstream — those patches address real bugs that would benefit any user. The setup-flow additions need mechanical rebase but no design changes. The simple-command tier is held pending coordination.

Ready to proceed to **Phase 1 (Tier A first PR)** when approved.

## Future upstream issues to file (not in our patches)

Pre-existing upstream behaviors noticed during fork-side debugging that are worth flagging to the maintainer when/if we open a coordination issue. These are NOT in our patch series — listing them here so they're not lost.

- **No-players branch in `_update_states` re-emits empty values every watchdog tick (~10 s) without dirty-checking.** Touched and observed during patch 43 work (2026-04-27). The else-branch unconditionally pushes `MEDIA_TITLE=""`, `MEDIA_ALBUM=""`, `MEDIA_ARTIST=""`, `MEDIA_POSITION=0`, etc. plus 4 select/sensor entities of the same shape — ~5 wire `entity_change` events per tick during idle, all duplicates of the previous tick. ucapi propagates them all. Fix would be tracking per-attribute "previously emitted value" and dirty-checking before adding to `updated_data`. Predates v1.18.13. Bandwidth/log noise only; not user-visible. Belongs upstream rather than as a fork patch since it would refactor pristine upstream code in a way that complicates future rebases.
