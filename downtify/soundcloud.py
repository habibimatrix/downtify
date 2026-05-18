"""Soundcloud metadata client for downtify organizer."""
from __future__ import annotations
import logging
import os
import re
from typing import Optional

import requests

log = logging.getLogger("downtify.organizer")

SOUNDCLOUD_CLIENT_ID = os.getenv("SOUNDCLOUD_CLIENT_ID", "")


def _norm_sc(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _best_match(tracks: list[dict], artist: str, title: str) -> Optional[dict]:
    if not tracks:
        return None
    target = _norm_sc(f"{artist} {title}")
    scored = []
    for t in tracks:
        t_str = _norm_sc(f"{t.get('user', {}).get('username', '')} {t.get('title', '')}")
        overlap = sum(1 for c in target if c in t_str)
        scored.append((overlap, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def search_soundcloud_track(artist: str, title: str) -> dict:
    """Search Soundcloud API for track. Returns {genre, artist, album, title} or {}."""
    if not SOUNDCLOUD_CLIENT_ID:
        return {}
    try:
        r = requests.get(
            "https://api.soundcloud.com/tracks",
            params={"q": f"{artist} {title}", "client_id": SOUNDCLOUD_CLIENT_ID, "limit": 5},
            timeout=8,
        )
        if r.status_code != 200:
            return {}
        tracks = r.json()
        if not tracks or not isinstance(tracks, list):
            return {}
        best = _best_match(tracks, artist, title)
        if not best:
            return {}
        return {
            "genre": best.get("genre", ""),
            "artist": best.get("user", {}).get("username", ""),
            "album": "",
            "title": best.get("title", ""),
        }
    except Exception as e:
        log.debug(f"  Soundcloud-Fehler: {e}")
        return {}
