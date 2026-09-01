#!/usr/bin/env python3
"""Regression harness for the ucapi ``min_len=1`` listing-abort bug class.

``ucapi.entity.validate_str(name, value, min_len=1, max_len=255)`` raises
``ValueError`` when a validated ``BrowseMediaItem`` field is the empty string.
``MediaBrowser.browse_media`` catches ``ValueError`` and answers with the Kodi
library root, so ONE bad row silently collapses an entire listing with no error
shown on the remote. Kodi routinely returns ``""`` for art it knows of but has
not cached, for an addon with no icon, and for a blank album artist.

This script builds each affected item directly, against a real ucapi wheel, so
the class can be re-checked without a device. It needs no Kodi and no remote.

Usage::

    python -m pip download ucapi==0.7.0 --no-deps -d /tmp/w
    python -c "import zipfile,glob;zipfile.ZipFile(glob.glob('/tmp/w/ucapi-0.7.0*.whl')[0]).extractall('/tmp/ucapi070')"
    python tools/repro_ucapi_minlen.py src --ucapi /tmp/ucapi070

Exit code is the number of cases that raised (0 = clean). Run it against an old
tree to see the failures::

    git archive v1.21.0-madalone.1 src | tar x -C /tmp/old --strip-components=1
    python tools/repro_ucapi_minlen.py /tmp/old --ucapi /tmp/ucapi070   # 9 raised
"""

# The deferred imports and prints below are deliberate: ucapi must be placed on
# sys.path before media_browser is imported, and stdout IS this tool's output.
# ruff: noqa: T201, PLC0415

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse


def _build_browser(src: Path, ucapi_dir: Path | None):
    """Import the fork's media_browser with the requested ucapi on sys.path."""
    sys.path.insert(0, str(src.resolve()))
    if ucapi_dir is not None:
        sys.path.insert(0, str(ucapi_dir.resolve()))

    import ucapi

    print(f"  ucapi under test: {ucapi.__file__}")

    import media_browser as mb

    class _Cfg:
        video_only_browse_filter = False
        address = "1.2.3.4"
        download_artwork = False
        artwork_type = "thumb"
        artwork_type_channels = "icon"

    class _Client:
        @staticmethod
        def thumbnail_url(url: str) -> str | None:
            # Mirrors pykodi.thumbnail_url: a value with no URL scheme yields None.
            return f"http://kodi/image/{url}" if urlparse(url).scheme else None

    class _Dev:
        device_config = _Cfg()
        client = _Client()

    return mb.MediaBrowser(_Dev())


def _cases(b):
    """Return (label, thunk) pairs. Each thunk builds one BrowseMediaItem."""
    return [
        (
            "episode: unwatched, unrated, no resume point (upstream v1.21.1)",
            lambda: b.get_item_from_episode({"episodeid": 1, "label": "Ep", "file": "smb://nas/TV/S01E01.mkv"}),
        ),
        (
            "movie: art dict has an empty 'poster'",
            lambda: b.get_item_from_movie({"movieid": 1, "label": "Dune", "year": 2021, "art": {"poster": ""}}, ""),
        ),
        (
            "movie: empty 'poster' but usable 'fanart' (must fall through to fanart)",
            lambda: b.get_item_from_movie(
                {"movieid": 1, "label": "Dune", "year": 2021, "art": {"poster": "", "fanart": "image://f/"}},
                "",
            ),
        ),
        (
            "tvshow: art dict has an empty 'poster'",
            lambda: b.get_item_from_tvshow({"tvshowid": 1, "label": "Show", "art": {"poster": ""}}, ""),
        ),
        (
            "album: blank album artist (get_element returns '')",
            lambda: b.get_item_from_album(
                {"albumid": 7, "label": "Greatest Hits", "artist": [""], "art": {}}, "kodi://music/albums"
            ),
        ),
        (
            "album: art dict has an empty 'poster'",
            lambda: b.get_item_from_album({"albumid": 7, "label": "A", "artist": ["X"], "art": {"poster": ""}}, ""),
        ),
        (
            "song: art dict has an empty 'poster'",
            lambda: b.get_item_from_song(
                {"songid": 1, "label": "T", "artist": ["A"], "album": "B", "art": {"poster": ""}}
            ),
        ),
        (
            "addon: no icon -> thumbnail '' (collapses the whole kodi://addons listing)",
            lambda: b.get_item_from_addon({"addonid": "plugin.x", "name": "Netflix", "thumbnail": ""}),
        ),
        (
            "channel: both 'thumbnail' and 'icon' empty",
            lambda: b.get_item_from_channel({"channelid": 3, "label": "C1", "thumbnail": "", "icon": ""}),
        ),
        (
            "SANITY: movie with a real subtitle must keep its year",
            lambda: b.get_item_from_movie({"movieid": 2, "label": "M", "year": 1999, "art": {}}, ""),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", type=Path, help="path to the src/ directory to test")
    parser.add_argument("--ucapi", type=Path, default=None, help="directory holding an extracted ucapi wheel")
    args = parser.parse_args()

    browser = _build_browser(args.src, args.ucapi)
    raised = 0

    for label, thunk in _cases(browser):
        try:
            item = thunk()
        except Exception as exc:  # noqa: BLE001 - the point is to catch everything
            raised += 1
            print(f"  RAISED  {label}\n            -> {type(exc).__name__}: {exc}")
            continue
        detail = ""
        if item is not None:
            detail = f"  [subtitle={item.subtitle!r} thumbnail={item.thumbnail!r} artist={item.artist!r}]"
        print(f"  ok      {label}{detail}")

    print(f"\n  {raised} raised / {len(_cases(browser))} cases")
    return raised


if __name__ == "__main__":
    sys.exit(main())
