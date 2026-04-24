# Contributing

Thanks for taking an interest. This is a **personal patched fork** of [`albaintor/integration-kodi`](https://github.com/albaintor/integration-kodi) — targeted bug fixes and enhancements applied on top of upstream without altering upstream logic. All credit for the underlying integration goes to [Albaintor](https://github.com/albaintor).

Before opening an issue or PR here, please check whether the concern is about a fork-specific patch or the integration as a whole — they go to different places.

### Upstream vs Fork — where to file what

**File against upstream** ([`albaintor/integration-kodi`](https://github.com/albaintor/integration-kodi/issues)) if the problem exists in vanilla upstream and would benefit all users of the integration:

- General Kodi connection issues, protocol bugs, missing features in the core integration.
- Requests for new Kodi commands, new browse sources, new playback behaviors.
- Questions about the Unfolded Circle Remote Two/3 integration API surface in general.

**File here** ([`mmadalone/integration-kodi`](https://github.com/mmadalone/integration-kodi/issues)) if the issue is specific to a patch this fork applies:

- Regressions in any of the patches documented in [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md).
- Behavior differences between the fork and upstream (intentional or otherwise).
- Edge cases in fork-added features (`video_only_browse_filter`, `suppress_unsupported_command_errors`, sidecar thumbnail detection, the `MODE_*` simple commands, etc).
- Build or packaging issues specific to this fork's layout.

If you're not sure, it's fine to file here and I can redirect.

### Bug Reports :bug:

1. Check [this fork's issues](https://github.com/mmadalone/integration-kodi/issues) and [the UC common feature/bug tracker](https://github.com/unfoldedcircle/feature-and-bug-tracker/issues) for duplicates.
2. Include: the fork version (see `driver.json` or the tag you're running), UC Remote 3 firmware version, Kodi version, a brief reproduction, and — if possible — the relevant integration log lines (UC Remote 3 web UI → Integrations → Kodi → Logs).
3. [Open an issue](https://github.com/mmadalone/integration-kodi/issues/new).

### Pull Requests

Contributions welcome. A few notes specific to a fork of this shape:

- **For changes that should ultimately live in upstream**, please consider submitting upstream first. The fork picks up upstream improvements via periodic rebases. If you're unsure whether a change belongs here or upstream, open a draft PR here and we can decide.
- **For fork-specific patches**, please add a corresponding section to [`KODI-INTEGRATION-PATCHES.md`](KODI-INTEGRATION-PATCHES.md) describing the problem, solution, and any non-obvious trade-offs. That file is the source of truth for the fork's patch history.
- Don't modify upstream logic unnecessarily — patches are additive when possible. Rebases become painful fast otherwise.
- Licensing: contributed code must be under [Mozilla Public License 2.0](https://choosealicense.com/licenses/mpl-2.0/) (unchanged from upstream). Please include the standard boilerplate at the top of any new file:

  ```python
  """
  {file description}

  :copyright: (c) {year} {contributor}
  :license: MPL-2.0, see LICENSE for more details.
  """
  ```

- Lint must pass locally before pushing — the CI runs `black`, `isort`, `flake8`, and `pylint` on `src/` via `.github/workflows/python-code-format.yml`. See [`docs/code_guidelines.md`](docs/code_guidelines.md) for the style rules.

### Contribution Flow

1. Fork this repo.
2. Branch off the current `v1.18.13-patched` tip (or whatever branch matches the current base version — check the branch name is `vX.Y.Z-patched` where `X.Y.Z` is the upstream tag we last rebased to).
3. Make your changes (preferably on a feature branch).
4. Add a patch section to `KODI-INTEGRATION-PATCHES.md` if your change is fork-specific. Bump the patch number sequentially.
5. Run the lint sweep locally — the docker builder image `docker.io/unfoldedcircle/r2-pyinstaller:3.11.13-0.4.0` is the reference environment; see [`CLAUDE.md`](CLAUDE.md)'s "Build & Deploy" section for the invocation.
6. Push to your fork and submit a PR.

### Build & Deploy

See [`CLAUDE.md`](CLAUDE.md) for the full Docker build + UC Remote 3 deploy procedure (it also covers the Windows Git Bash-specific `MSYS_NO_PATHCONV=1` requirement and the `tar` colon-path workaround for packaging).

### Feedback & Community

Beyond this repo, the Unfolded Circle community channels are the right place for general discussion:

- [UC feature & bug tracker](https://github.com/unfoldedcircle/feature-and-bug-tracker/issues) — cross-integration UC issues.
- [Unfolded Circle community forum](http://unfolded.community/)
- [Unfolded Circle Discord](http://unfolded.chat/)
- [Unfolded Circle contact](https://unfoldedcircle.com/contact)

For questions specific to this fork, open an issue here or ping in the UC community channels referencing `mmadalone/integration-kodi`.
