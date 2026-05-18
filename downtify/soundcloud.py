"""Soundcloud metadata client for downtify organizer."""
from __future__ import annotations
import logging
import os
import re
from typing import Optional

import requests

log = logging.getLogger("downtify.organizer")

# Env-Var als Startwert; wird zur Laufzeit via discover_client_id() überschrieben
_client_id: str = os.getenv("SOUNDCLOUD_CLIENT_ID", "")


def get_client_id() -> str:
    return _client_id


def set_client_id(cid: str) -> None:
    global _client_id
    _client_id = cid


def discover_client_id() -> str:
    """Scrapt soundcloud.com und extrahiert die eingebettete client_id aus den JS-Bundles."""
    try:
        r = requests.get(
            "https://soundcloud.com",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        # Alle JS-Bundle-URLs aus dem HTML sammeln
        script_urls = re.findall(
            r'https://[a-z0-9\-]+\.sndcdn\.com/assets/[^"\'>\s]+\.js',
            r.text,
        )
        if not script_urls:
            # Fallback: alle sndcdn-Scripts
            script_urls = re.findall(r'src="(https://[^"]+\.sndcdn\.com/[^"]+\.js)"', r.text)

        for url in script_urls[:8]:
            try:
                js = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                m = re.search(r'["\']client_id["\']\s*:\s*["\']([a-zA-Z0-9]{20,})["\']', js.text)
                if not m:
                    m = re.search(r'client_id=([a-zA-Z0-9]{20,})', js.text)
                if m:
                    found = m.group(1)
                    log.info(f"  SoundCloud client_id gefunden: {found[:6]}…")
                    return found
            except Exception:
                continue
    except Exception as e:
        log.warning(f"  SoundCloud discover fehlgeschlagen: {e}")
    return ""


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
    cid = get_client_id()
    if not cid:
        return {}
    try:
        r = requests.get(
            "https://api.soundcloud.com/tracks",
            params={"q": f"{artist} {title}", "client_id": cid, "limit": 5},
            timeout=8,
        )
        if r.status_code == 401:
            log.warning("  SoundCloud 401 — client_id abgelaufen")
            return {}
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
