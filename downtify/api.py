"""FastAPI router exposed by Downtify.

The endpoints intentionally mirror the surface that the previous
``spotdl``-powered backend exposed so the existing Vue frontend keeps
working without changes:

* ``GET  /api/version``
* ``GET  /api/songs/search``
* ``GET  /api/song/url`` and ``GET /api/url`` (alias)
* ``POST /api/download/url`` (optional JSON body: resolved Spotify row so
  ``track_number`` / ``album_track_total`` survive re-fetch by URL)
* ``POST /api/playlist/m3u``
* ``GET  /api/settings``
* ``POST /api/settings/update``
* ``WS   /api/ws``
* ``GET  /api/check_update``
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from loguru import logger

from . import m3u, providers, spotify
from .downloader import Downloader
from .monitor import PlaylistMonitorDB, check_playlist
from .organizer_service import (
    DEFAULT_COUNTRY_TO_FOLDER,
    DEFAULT_GENRE_RULES,
    DEFAULT_SEPARATORS,
    get_organizer,
)

# ── Auth ──────────────────────────────────────────────────────────────────────

_AUTH_PASSWORD = os.getenv('DOWNTIFY_PASSWORD', '')
_SESSION_SECRET = secrets.token_hex(32)
_SESSION_COOKIE = 'downtiplx_session'
_SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days


def _make_token() -> str:
    return hmac.new(_SESSION_SECRET.encode(), _AUTH_PASSWORD.encode(), hashlib.sha256).hexdigest()


def _token_valid(token: str) -> bool:
    if not _AUTH_PASSWORD:
        return True
    return hmac.compare_digest(token, _make_token())


def _is_authenticated(request: Request) -> bool:
    if not _AUTH_PASSWORD:
        return True
    return _token_valid(request.cookies.get(_SESSION_COOKIE, ''))


# ── Settings ───────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS: dict[str, Any] = {
    'audio_providers': ['youtube-music'],
    'lyrics_providers': ['lrclib'],
    'download_lyrics': False,
    'format': 'mp3',
    'bitrate': '320',
    'output': '{artists} - {title}.{output-ext}',
    'generate_m3u': False,
    'max_parallel_downloads': 1,
    'genre_rules': None,        # None = use hardcoded defaults
    'artist_rules': [],
    'artist_genre_rules': [],   # [{pattern, genre}] — highest-priority override
    'country_to_folder': None,  # None = use hardcoded defaults
}


def _effective_lyrics_providers(settings: dict[str, Any]) -> list[str]:
    if not settings.get('download_lyrics', True):
        return []
    return [
        p
        for p in (settings.get('lyrics_providers') or [])
        if isinstance(p, str) and p
    ]


class ConnectionManager:
    """Tracks the active WebSocket clients keyed by ``client_id``."""

    def __init__(self) -> None:
        self._clients: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._clients[client_id] = ws

    def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        ws = self._clients.get(client_id)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            self._clients.pop(client_id, None)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[str] = []
        for client_id, ws in list(self._clients.items()):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(client_id)
        for client_id in dead:
            self._clients.pop(client_id, None)


class AppState:
    version: str = '0.0.0'
    downloader: Optional[Downloader] = None
    connections: ConnectionManager = ConnectionManager()
    settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
    settings_path: Optional[Path] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    monitor_db: Optional[PlaylistMonitorDB] = None
    download_jobs: dict[str, dict[str, Any]] = {}
    download_semaphore: Optional[asyncio.Semaphore] = None


state = AppState()
router = APIRouter()


def _load_settings(path: Path) -> dict[str, Any]:
    """Load saved settings from *path*, merging with DEFAULT_SETTINGS as base."""
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(saved, dict):
            merged = dict(DEFAULT_SETTINGS)
            for k, v in saved.items():
                if k in DEFAULT_SETTINGS:
                    merged[k] = v
            return merged
    except Exception:
        pass
    return dict(DEFAULT_SETTINGS)


def _save_settings_full(path: Path, settings: dict[str, Any]) -> None:
    """Save all settings keys (including organizer config) to disk."""
    try:
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as exc:
        logger.warning('Could not persist settings: {}', exc)


def _save_settings(path: Path, settings: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    except Exception as exc:
        logger.warning('Could not persist settings: {}', exc)


@router.get('/api/version')
def get_version() -> str:
    return state.version


@router.get('/api/check_update')
def check_update() -> Optional[dict[str, Any]]:
    return None


@router.get('/api/songs/search')
def search_endpoint(query: str = Query('')) -> list[dict[str, Any]]:
    return providers.search_songs(query, limit=20)


@router.get('/api/song/url')
def song_url_endpoint(url: str = Query(...)):
    return _resolve_url(url)


@router.get('/api/url')
def url_endpoint(url: str = Query(...)):
    return _resolve_url(url)


def _resolve_url(url: str):
    parsed = spotify.parse_spotify_url(url)
    if parsed is None:
        raise HTTPException(status_code=400, detail='Invalid Spotify URL')
    kind, sid = parsed
    try:
        if kind == 'track':
            return spotify.track_from_id(sid)
        if kind == 'album':
            return spotify.album_tracks_from_id(sid)
        if kind == 'playlist':
            return spotify.playlist_tracks_from_id(sid)
    except Exception as exc:
        logger.exception('Failed to resolve Spotify URL {}', url)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise HTTPException(
        status_code=400, detail=f'Unsupported entity type: {kind}'
    )


def _merge_client_track_hints(
    base: dict[str, Any],
    hints: Optional[dict[str, Any]],
) -> None:
    """Copy tagging fields from the client-resolved Spotify row.

    ``POST /api/download/url`` re-fetches metadata from the URL only, which loses
    ``track_number`` for rows that came from an album/playlist browse.
    """

    if not isinstance(hints, dict) or not hints:
        return
    tn = hints.get('track_number')
    if tn is not None:
        try:
            iv = int(tn)
        except (TypeError, ValueError):
            pass
        else:
            if iv > 0:
                base['track_number'] = iv
    tt = hints.get('album_track_total')
    if tt is not None:
        try:
            tv = int(tt)
        except (TypeError, ValueError):
            pass
        else:
            if tv > 0:
                base['album_track_total'] = tv
    rd = hints.get('release_date')
    if isinstance(rd, str) and rd.strip():
        base['release_date'] = rd.strip()
    yr = hints.get('year')
    if isinstance(yr, str) and yr.strip():
        base['year'] = yr.strip()


def _song_for_download(url: str) -> dict[str, Any]:
    parsed = spotify.parse_spotify_url(url)
    if parsed is not None:
        kind, sid = parsed
        if kind == 'track':
            return spotify.track_from_id(sid)
        raise HTTPException(
            status_code=400,
            detail='Only Spotify track URLs are supported here',
        )
    if 'youtube.com' in url or 'youtu.be' in url or 'music.youtube' in url:
        match = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})', url)
        if not match:
            raise HTTPException(status_code=400, detail='Invalid YouTube URL')
        return providers.song_from_video_id(match.group(1))
    if 'soundcloud.com/' in url:
        # yt-dlp handles SoundCloud natively; return a minimal song dict
        return {'title': url, 'song_id': url, 'name': url, 'source': 'soundcloud', 'url': url}
    raise HTTPException(status_code=400, detail='Unsupported URL')


def _register_job(song: dict[str, Any], status: str = 'queued') -> str:
    song_id = str(song.get('song_id') or song.get('url') or id(song))
    state.download_jobs[song_id] = {
        'song': song,
        'status': status,
        'progress': 0,
        'message': '',
        'filename': None,
    }
    return song_id


async def _run_download(
    song: dict[str, Any],
    song_id: str,
    subdir: Optional[str] = None,
) -> Optional[str]:
    """Run a single download to completion, updating jobs state and broadcasting WS events."""

    if state.downloader is None:
        raise RuntimeError('Downloader not ready')

    loop = state.loop or asyncio.get_running_loop()
    job = state.download_jobs.get(song_id)
    if job is None:
        song_id = _register_job(song, status='downloading')
        job = state.download_jobs[song_id]
    else:
        job['status'] = 'downloading'

    await state.connections.broadcast({
        'song': song,
        'progress': 0,
        'message': '',
        'status': 'downloading',
    })

    def progress(pct: float, message: str) -> None:
        j = state.download_jobs.get(song_id)
        if j:
            j['progress'] = pct
            j['message'] = message
        asyncio.run_coroutine_threadsafe(
            state.connections.broadcast({
                'song': song,
                'progress': pct,
                'message': message,
                'status': 'downloading',
            }),
            loop,
        )

    sem = state.download_semaphore
    try:
        async with sem if sem is not None else contextlib.nullcontext():
            filename = await loop.run_in_executor(
                None,
                lambda: state.downloader.download(
                    song, progress, subdir=subdir
                ),
            )
    except Exception as exc:
        logger.exception('Download failed for {}', song_id)
        job['status'] = 'error'
        job['message'] = f'Error: {exc}'
        await state.connections.broadcast({
            'song': song,
            'progress': 0,
            'message': f'Error: {exc}',
            'status': 'error',
        })
        raise

    job['status'] = 'done'
    job['filename'] = filename
    job['progress'] = 100
    await state.connections.broadcast({
        'song': song,
        'progress': 100,
        'message': 'Done',
        'status': 'done',
        'filename': filename,
    })

    # Track in the List of Truth (monitor DB) for direct downloads
    if state.monitor_db is not None and filename:
        spotify_id = song.get('song_id') or song.get('spotify_id') or ''
        if spotify_id:
            display_name = (
                song.get('name')
                or song.get('title')
                or ''
            )
            await asyncio.to_thread(
                state.monitor_db.mark_direct_download,
                spotify_id,
                filename,
                display_name or None,
            )

    return filename


@router.post('/api/download/url')
async def download_endpoint(
    url: str = Query(...),
    client_id: str = Query(''),
    client_hints: Optional[dict[str, Any]] = Body(None),
):
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    song = _song_for_download(url)
    tn_before = song.get('track_number')
    yr_before = song.get('year') or song.get('release_date')
    _merge_client_track_hints(song, client_hints)
    logger.debug(
        'download/url: url={} body={} tn_before={!r} tn_after={!r} '
        'date_before={!r} date_after_year={!r} date_after_rd={!r}',
        url[:140],
        'json' if isinstance(client_hints, dict) else 'none',
        tn_before,
        song.get('track_number'),
        yr_before,
        song.get('year'),
        song.get('release_date'),
    )

    # Re-download guard: reject if already in List of Truth
    spotify_id = song.get('song_id') or song.get('spotify_id') or ''
    if spotify_id and state.monitor_db is not None:
        already = await asyncio.to_thread(
            state.monitor_db.is_track_downloaded, spotify_id
        )
        if already:
            raise HTTPException(
                status_code=409,
                detail='already_downloaded',
            )

    song_id = _register_job(song, status='downloading')

    try:
        filename = await _run_download(song, song_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return filename


async def _process_batch(
    songs: list[dict[str, Any]],
    job_ids: list[str],
    playlist_url: str,
    generate_m3u: bool,
) -> None:
    # Resolve the playlist name up-front so all tracks land in a single,
    # per-playlist sub-folder. Loose batches (e.g. albums or unrelated
    # tracks) keep the legacy flat layout under download_dir.
    playlist_subdir: Optional[str] = None
    playlist_name: Optional[str] = None
    parsed = spotify.parse_spotify_url(playlist_url) if playlist_url else None
    if parsed is not None and parsed[0] == 'playlist':
        try:
            playlist_name, _ = await asyncio.to_thread(
                spotify.playlist_info_and_tracks, parsed[1]
            )
            playlist_subdir = m3u.sanitize_playlist_name(playlist_name)
        except Exception:
            logger.exception(
                'Failed to resolve playlist name for {}', playlist_url
            )

    async def _bounded(song: dict[str, Any], song_id: str) -> dict[str, Any]:
        try:
            filename = await _run_download(
                song, song_id, subdir=playlist_subdir
            )
        except Exception as exc:
            logger.exception('Batch download failed for song_id={}', song_id)
            # _run_download broadcasts errors itself, but early failures (e.g.
            # "Downloader not ready") raise before the broadcast — cover them.
            job = state.download_jobs.get(song_id)
            if job and job.get('status') != 'error':
                job['status'] = 'error'
                job['message'] = f'Error: {exc}'
                await state.connections.broadcast({
                    'song': song,
                    'progress': 0,
                    'message': f'Error: {exc}',
                    'status': 'error',
                })
            filename = None
        return {'song': song, 'filename': filename}

    results = await asyncio.gather(
        *[_bounded(s, sid) for s, sid in zip(songs, job_ids)],
        return_exceptions=False,
    )

    if not (generate_m3u and playlist_subdir and playlist_name):
        return

    entries: list[dict[str, Any]] = []
    for r in results:
        if not r or not r.get('filename'):
            continue
        s = r['song']
        entries.append({
            'filename': r['filename'],
            'title': s.get('name') or '',
            'artist': ', '.join(s.get('artists') or []),
            'duration': s.get('duration') or 0,
        })
    if not entries:
        return

    try:
        await asyncio.to_thread(
            m3u.write_m3u,
            state.downloader.download_dir,
            playlist_name,
            entries,
            playlist_subdir=playlist_subdir,
        )
    except Exception:
        logger.exception('Failed to write M3U for {}', playlist_url)


@router.post('/api/download/batch')
async def download_batch_endpoint(request: Request) -> dict[str, Any]:
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc

    songs = payload.get('songs') or []
    if not isinstance(songs, list) or not songs:
        raise HTTPException(
            status_code=400, detail='songs must be a non-empty list'
        )
    playlist_url = str(payload.get('playlist_url') or '')
    generate_m3u = bool(payload.get('generate_m3u', True))

    valid_songs: list[dict[str, Any]] = []
    job_ids: list[str] = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        song_id = _register_job(song, status='queued')
        valid_songs.append(song)
        job_ids.append(song_id)
        await state.connections.broadcast({
            'song': song,
            'progress': 0,
            'message': '',
            'status': 'queued',
        })

    if not valid_songs:
        raise HTTPException(status_code=400, detail='No valid songs in batch')

    task = asyncio.create_task(
        _process_batch(valid_songs, job_ids, playlist_url, generate_m3u)
    )

    def _log_batch_failure(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.opt(exception=exc).error('Batch processing crashed')

    task.add_done_callback(_log_batch_failure)
    return {'job_ids': job_ids, 'count': len(job_ids)}


@router.get('/api/queue')
def get_queue() -> list[dict[str, Any]]:
    return list(state.download_jobs.values())


@router.delete('/api/queue')
def clear_queue() -> dict:
    state.download_jobs.clear()
    return {'cleared': True}


@router.delete('/api/queue/item')
def remove_queue_item(song_id: str = Query(...)) -> dict:
    if song_id in state.download_jobs:
        del state.download_jobs[song_id]
        return {'removed': True}
    return {'removed': False}


@router.post('/api/playlist/m3u')
async def write_playlist_m3u_endpoint(request: Request) -> dict[str, Any]:
    """Write an M3U for the playlist after the per-track downloads.

    The frontend POSTs ``{playlist_url, tracks: [{filename, title,
    artist, duration}, ...]}``. The playlist name is resolved
    server-side via :func:`spotify.playlist_info_and_tracks` so the
    existing ``/api/song/url`` shape stays untouched.
    """

    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Invalid payload')

    playlist_url = str(payload.get('playlist_url') or '').strip()
    if not playlist_url:
        raise HTTPException(status_code=400, detail='Missing playlist_url')
    parsed = spotify.parse_spotify_url(playlist_url)
    if parsed is None or parsed[0] != 'playlist':
        raise HTTPException(
            status_code=400, detail='Not a Spotify playlist URL'
        )

    tracks = payload.get('tracks') or []
    if not isinstance(tracks, list):
        raise HTTPException(status_code=400, detail='tracks must be a list')

    try:
        playlist_name, _ = await asyncio.to_thread(
            spotify.playlist_info_and_tracks, parsed[1]
        )
    except Exception as exc:
        logger.exception('Failed to resolve playlist {}', playlist_url)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    entries = [t for t in tracks if isinstance(t, dict)]
    playlist_subdir = m3u.sanitize_playlist_name(playlist_name)
    target, kept = m3u.write_m3u(
        state.downloader.download_dir,
        playlist_name,
        entries,
        playlist_subdir=playlist_subdir,
    )
    if target is None:
        raise HTTPException(
            status_code=400, detail='No tracks resolved to a file on disk'
        )
    return {'path': str(target), 'count': kept}


@router.get('/api/settings')
def get_settings_endpoint(client_id: str = Query('')) -> dict[str, Any]:
    return state.settings


@router.post('/api/settings/update')
async def update_settings_endpoint(
    request: Request, client_id: str = Query('')
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in DEFAULT_SETTINGS:
                state.settings[key] = value
        if state.downloader is not None:
            fmt = payload.get('format')
            if isinstance(fmt, str) and fmt:
                state.downloader.audio_format = fmt
            bitrate = payload.get('bitrate')
            if isinstance(bitrate, str) and bitrate:
                state.downloader.audio_bitrate = bitrate
            output = payload.get('output')
            if isinstance(output, str) and output:
                state.downloader.output_template = output.replace(
                    '.{output-ext}', ''
                )
            if 'lyrics_providers' in payload or 'download_lyrics' in payload:
                state.downloader.lyrics_providers = (
                    _effective_lyrics_providers(state.settings)
                )
        if 'max_parallel_downloads' in payload:
            try:
                count = max(1, int(payload['max_parallel_downloads']))
                state.download_semaphore = asyncio.Semaphore(count)
            except (TypeError, ValueError):
                pass
    if state.settings_path is not None:
        _save_settings(state.settings_path, state.settings)
    return state.settings


@router.get('/api/truth')
def get_truth(
    search: str = Query(''),
    page: int = Query(1),
    limit: int = Query(20),
) -> dict[str, Any]:
    """List of Truth: paginated search of all downloaded tracks in monitor DB."""
    if state.monitor_db is None:
        return {'items': [], 'total': 0, 'page': page, 'pages': 1}
    items, total, pages = state.monitor_db.list_all_downloads(
        search=search, page=page, limit=limit
    )
    # Enrich with organizer metadata (genre, artist, album, title, orig_*)
    svc = get_organizer()
    if svc is not None:
        ids = [item['track_spotify_id'] for item in items if item.get('track_spotify_id')]
        enriched = svc.db.get_processed_by_spotify_ids(ids)
        for item in items:
            meta = enriched.get(item.get('track_spotify_id') or '', {})
            for key in ('genre', 'artist', 'album', 'title', 'orig_genre', 'orig_artist', 'orig_album', 'orig_title'):
                item[key] = meta.get(key, '')
    return {'items': items, 'total': total, 'page': page, 'pages': pages}


@router.delete('/api/truth/{track_id}')
def delete_truth(track_id: int) -> dict[str, Any]:
    """Remove a track from the List of Truth so it can be re-downloaded."""
    if state.monitor_db is None:
        raise HTTPException(status_code=503, detail='Monitor DB not ready')
    spotify_id = state.monitor_db.get_spotify_id_for_download(track_id)
    deleted = state.monitor_db.delete_download(track_id)
    # Also clear from organizer processed table so the file can be re-organized
    if deleted and spotify_id:
        svc = get_organizer()
        if svc is not None:
            svc.db.delete_processed_by_spotify_id(spotify_id)
    return {'deleted': deleted}


@router.get('/api/organizer/config')
def get_organizer_config() -> dict[str, Any]:
    """Return current organizer rules (genre rules + artist aliases)."""
    genre_rules = state.settings.get('genre_rules')
    if not genre_rules:
        genre_rules = [
            {'keyword': kw, 'folder': folder}
            for kw, folder in DEFAULT_GENRE_RULES
        ]
    country_to_folder = state.settings.get('country_to_folder')
    if not country_to_folder:
        country_to_folder = DEFAULT_COUNTRY_TO_FOLDER
    artist_rules = state.settings.get('artist_rules') or []
    artist_genre_rules = state.settings.get('artist_genre_rules') or []
    artist_separator_tokens = state.settings.get('artist_separator_tokens') or DEFAULT_SEPARATORS
    available_folders = sorted(set(
        r['folder'] for r in genre_rules
        if isinstance(r, dict) and r.get('folder')
    ))
    from .soundcloud import get_client_id as _sc_get_id
    return {
        'genre_rules': genre_rules,
        'artist_rules': artist_rules,
        'artist_genre_rules': artist_genre_rules,
        'country_to_folder': country_to_folder,
        'available_folders': available_folders,
        'artist_separator_tokens': artist_separator_tokens,
        'soundcloud_client_id': state.settings.get('soundcloud_client_id') or _sc_get_id(),
    }


@router.post('/api/organizer/config')
async def save_organizer_config(request: Request) -> dict[str, Any]:
    """Save organizer rules to settings and hot-reload the organizer."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc

    if isinstance(payload.get('genre_rules'), list):
        state.settings['genre_rules'] = payload['genre_rules']
    if isinstance(payload.get('artist_rules'), list):
        state.settings['artist_rules'] = payload['artist_rules']
    if isinstance(payload.get('artist_genre_rules'), list):
        state.settings['artist_genre_rules'] = payload['artist_genre_rules']
    if isinstance(payload.get('country_to_folder'), dict):
        state.settings['country_to_folder'] = payload['country_to_folder']
    if isinstance(payload.get('artist_separator_tokens'), list):
        state.settings['artist_separator_tokens'] = payload['artist_separator_tokens']
    if isinstance(payload.get('soundcloud_client_id'), str):
        cid = payload['soundcloud_client_id'].strip()
        state.settings['soundcloud_client_id'] = cid
        from .soundcloud import set_client_id as _sc_set
        _sc_set(cid)

    if state.settings_path is not None:
        _save_settings_full(state.settings_path, state.settings)

    # Hot-reload organizer rules + separator tokens
    svc = get_organizer()
    if svc is not None:
        svc.resolver.reload_from_settings(state.settings)
        svc.voter.separators = state.settings.get('artist_separator_tokens') or DEFAULT_SEPARATORS

    return {'saved': True}


@router.get('/api/soundcloud/discover')
async def soundcloud_discover_client_id() -> dict[str, Any]:
    """Scrapt soundcloud.com und gibt die eingebettete client_id zurück."""
    import asyncio

    from .soundcloud import discover_client_id
    from .soundcloud import set_client_id as _sc_set
    loop = asyncio.get_event_loop()
    cid = await loop.run_in_executor(None, discover_client_id)
    if not cid:
        raise HTTPException(status_code=404, detail='client_id nicht gefunden')
    # Direkt aktivieren + in Settings persistieren
    _sc_set(cid)
    state.settings['soundcloud_client_id'] = cid
    if state.settings_path is not None:
        _save_settings_full(state.settings_path, state.settings)
    return {'client_id': cid}


@router.post('/api/soundcloud/extract')
async def soundcloud_extract_client_id(request: Request) -> dict[str, Any]:
    """Extrahiert die client_id aus vom User eingefügtem SoundCloud-HTML."""
    import re

    body = await request.json()
    html = body.get('html', '')
    if not html:
        raise HTTPException(status_code=400, detail='html field required')
    match = re.search(r'["\']client_id["\']\s*:\s*["\']([a-zA-Z0-9]{20,})["\']', html)
    if not match:
        raise HTTPException(status_code=404, detail='client_id not found in HTML')
    cid = match.group(1)
    from .soundcloud import set_client_id as _sc_set
    _sc_set(cid)
    state.settings['soundcloud_client_id'] = cid
    if state.settings_path is not None:
        _save_settings_full(state.settings_path, state.settings)
    return {'client_id': cid}


def _cookies_path() -> Path:
    if state.settings_path is not None:
        return state.settings_path.parent / 'cookies.txt'
    return Path('/data/cookies.txt')


@router.get('/api/cookies')
def cookies_status() -> dict[str, Any]:
    """Returns whether a cookies.txt file is present and basic stats."""
    p = _cookies_path()
    if not p.exists():
        return {'present': False}
    try:
        content = p.read_text(encoding='utf-8', errors='replace')
        lines = [l for l in content.splitlines() if l.strip() and not l.startswith('#')]
        return {
            'present': True,
            'size_bytes': p.stat().st_size,
            'entry_count': len(lines),
        }
    except Exception:
        return {'present': True, 'size_bytes': p.stat().st_size, 'entry_count': None}


@router.post('/api/cookies')
async def cookies_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a Netscape-format cookies.txt file for yt-dlp."""
    p = _cookies_path()
    try:
        data = await file.read()
        p.write_bytes(data)
        content = data.decode('utf-8', errors='replace')
        lines = [l for l in content.splitlines() if l.strip() and not l.startswith('#')]
        return {'ok': True, 'entry_count': len(lines), 'size_bytes': len(data)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete('/api/cookies')
def cookies_delete() -> dict[str, Any]:
    """Remove the uploaded cookies.txt file."""
    p = _cookies_path()
    if not p.exists():
        raise HTTPException(status_code=404, detail='No cookies file found')
    try:
        p.unlink()
        return {'ok': True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get('/api/organizer/status')
def organizer_status() -> dict:
    """Returns currently active organizer jobs."""
    return {"jobs": list(getattr(state, 'organizer_jobs', {}).values())}


@router.get('/api/health/apis')
def health_check_apis() -> dict:
    import shutil
    import urllib.request
    results: dict[str, dict] = {}
    log_lines: list[str] = []
    ts = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _http_ok(url: str, headers: Optional[dict] = None, timeout: int = 8) -> tuple[bool, str]:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ok = r.status < 500
                return ok, f'HTTP {r.status}'
        except Exception as exc:
            return False, str(exc)[:120]

    # YouTube Music
    try:
        from downtify import providers
        providers.search_songs('test', limit=1)
        results['youtube_music'] = {'status': 'ok', 'detail': 'ytmusicapi reachable'}
    except Exception as e:
        msg = str(e)[:120]
        results['youtube_music'] = {'status': 'error', 'detail': msg}
        log_lines.append(f'[{ts}] youtube_music: {msg}')

    # Spotify (public embed, no key needed)
    try:
        from downtify import spotify
        spotify.track_from_id('4iV5W9uYEdYUVa79Axb7Rh')  # known public track ID
        results['spotify'] = {'status': 'ok', 'detail': 'Spotify embed reachable'}
    except Exception as e:
        msg = str(e)[:120]
        results['spotify'] = {'status': 'error', 'detail': msg}
        log_lines.append(f'[{ts}] spotify: {msg}')

    # Deezer
    ok, detail = _http_ok('https://api.deezer.com/search?q=test&limit=1')
    results['deezer'] = {'status': 'ok' if ok else 'error', 'detail': detail}
    if not ok:
        log_lines.append(f'[{ts}] deezer: {detail}')

    # Last.fm
    ok, detail = _http_ok('https://ws.audioscrobbler.com/2.0/?method=track.search&track=test&api_key=nokey&format=json&limit=1')
    results['lastfm'] = {'status': 'ok' if ok else 'error', 'detail': detail}
    if not ok:
        log_lines.append(f'[{ts}] lastfm: {detail}')

    # MusicBrainz
    ok, detail = _http_ok(
        'https://musicbrainz.org/ws/2/recording?query=test&limit=1&fmt=json',
        headers={'User-Agent': 'Downtiplx/2.7.0'},
        timeout=10,
    )
    results['musicbrainz'] = {'status': 'ok' if ok else 'error', 'detail': detail}
    if not ok:
        log_lines.append(f'[{ts}] musicbrainz: {detail}')

    # SoundCloud
    try:
        from downtify.soundcloud import get_client_id
        cid = get_client_id()
        if not cid:
            results['soundcloud'] = {'status': 'warning', 'detail': 'No client_id configured — use Auto-detect in Settings'}
        else:
            ok, detail = _http_ok(
                f'https://api.soundcloud.com/tracks?q=test&client_id={cid}&limit=1',
                timeout=8,
            )
            if not ok and '401' in detail:
                results['soundcloud'] = {'status': 'error', 'detail': 'client_id invalid (401) — re-run Auto-detect'}
                log_lines.append(f'[{ts}] soundcloud: client_id 401')
            else:
                results['soundcloud'] = {'status': 'ok' if ok else 'warning', 'detail': detail}
    except Exception as e:
        msg = str(e)[:120]
        results['soundcloud'] = {'status': 'error', 'detail': msg}
        log_lines.append(f'[{ts}] soundcloud: {msg}')

    # Shazam
    try:
        import shazamio  # noqa: F401
        results['shazam'] = {'status': 'ok', 'detail': 'shazamio installed'}
    except ImportError as e:
        msg = str(e)[:120]
        results['shazam'] = {'status': 'error', 'detail': f'Import failed: {msg}'}
        log_lines.append(f'[{ts}] shazam: {msg}')

    # AcoustID (fpcalc fingerprinter)
    try:
        fpcalc = shutil.which('fpcalc')
        if fpcalc:
            results['acoustid'] = {'status': 'ok', 'detail': f'fpcalc found at {fpcalc}'}
        else:
            results['acoustid'] = {'status': 'warning', 'detail': 'fpcalc not in PATH — fingerprinting disabled'}
    except Exception as e:
        results['acoustid'] = {'status': 'error', 'detail': str(e)[:120]}

    # yt-dlp
    try:
        import yt_dlp  # noqa: F401
        results['yt_dlp'] = {'status': 'ok', 'detail': f'v{yt_dlp.version.__version__}'}
    except ImportError as e:
        msg = str(e)[:120]
        results['yt_dlp'] = {'status': 'error', 'detail': msg}
        log_lines.append(f'[{ts}] yt_dlp: {msg}')

    # Write error log
    if log_lines:
        try:
            log_path = Path('/data/API Fehler.log')
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write('\n'.join(log_lines) + '\n')
        except Exception:
            pass

    return {'apis': results, 'checked_at': ts}


# ── Cache API ─────────────────────────────────────────────────────────────────

@router.get('/api/cache/stats')
def get_cache_stats() -> dict[str, Any]:
    svc = get_organizer()
    if svc is None:
        return {'count': 0}
    count = svc.db.count_artist_knowledge()
    return {'count': count}


@router.get('/api/cache/tracks')
def list_cache_tracks(
    search: str = Query(''),
    limit: int = Query(50),
    offset: int = Query(0),
) -> dict[str, Any]:
    svc = get_organizer()
    if svc is None:
        return {'items': [], 'total': 0}
    items = svc.db.list_artist_knowledge(search=search, limit=limit, offset=offset)
    total = svc.db.count_artist_knowledge(search=search)
    return {'items': items, 'total': total}


@router.delete('/api/cache/tracks')
def delete_all_cache() -> dict[str, Any]:
    svc = get_organizer()
    if svc is None:
        raise HTTPException(status_code=503, detail='Organizer not running')
    svc.db.clear_artist_knowledge()
    return {'deleted': True}


@router.delete('/api/cache/tracks/{artist_norm}/album')
async def delete_artist_album(artist_norm: str, request: Request) -> dict[str, Any]:
    svc = get_organizer()
    if svc is None:
        raise HTTPException(status_code=503, detail='Organizer not running')
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc
    album = payload.get('album', '')
    if not album:
        raise HTTPException(status_code=400, detail='album required')
    svc.db.remove_artist_album(artist_norm, album)
    return {'deleted': True}


@router.delete('/api/cache/tracks/{artist_norm}')
def delete_cache_track(artist_norm: str) -> dict[str, Any]:
    svc = get_organizer()
    if svc is None:
        raise HTTPException(status_code=503, detail='Organizer not running')
    svc.db.delete_artist_knowledge(artist_norm)
    return {'deleted': True}


# ── Auth API ──────────────────────────────────────────────────────────────────

@router.get('/api/auth')
def auth_status(request: Request) -> dict[str, Any]:
    return {
        'protected': bool(_AUTH_PASSWORD),
        'authenticated': _is_authenticated(request),
    }


@router.post('/api/auth')
async def auth_login(request: Request, response: Response) -> dict[str, Any]:
    if not _AUTH_PASSWORD:
        return {'ok': True}
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')
    if body.get('password', '') != _AUTH_PASSWORD:
        raise HTTPException(status_code=401, detail='Wrong password')
    response.set_cookie(
        _SESSION_COOKIE,
        _make_token(),
        httponly=True,
        samesite='strict',
        max_age=_SESSION_MAX_AGE,
    )
    return {'ok': True}


@router.post('/api/auth/logout')
def auth_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(_SESSION_COOKIE)
    return {'ok': True}


# ── Audit API ─────────────────────────────────────────────────────────────────

@router.get('/api/audit/{track_id}')
def get_audit(track_id: str) -> dict[str, Any]:
    svc = get_organizer()
    if svc is None:
        raise HTTPException(status_code=503, detail='Organizer not running')
    audit = svc.db.get_audit(track_id)
    if audit is None and state.monitor_db is not None:
        # For YouTube-sourced downloads the organizer saves the audit under
        # "scanner:<stem>" because the file has no embedded Spotify ID tag.
        # Fall back: look up the filename from monitor.db by track_spotify_id.
        from pathlib import Path as _Path
        filename = state.monitor_db.get_filename_for_spotify_id(track_id)
        if filename:
            stem = _Path(filename).stem
            audit = svc.db.get_audit(f'scanner:{stem}')
    if audit is None:
        raise HTTPException(status_code=404, detail='No audit found')
    return audit


@router.websocket('/api/ws')
async def websocket_endpoint(
    ws: WebSocket, client_id: str = Query(...)
) -> None:
    await state.connections.connect(client_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.connections.disconnect(client_id)
    except Exception:
        state.connections.disconnect(client_id)


# ---------------------------------------------------------------------------
# Playlist monitoring endpoints
# ---------------------------------------------------------------------------


def _require_monitor_db() -> PlaylistMonitorDB:
    if state.monitor_db is None:
        raise HTTPException(
            status_code=500, detail='Monitor database not ready'
        )
    return state.monitor_db


@router.get('/api/monitor/playlists')
async def list_monitor_playlists() -> list[dict[str, Any]]:
    db = _require_monitor_db()
    playlists = await asyncio.to_thread(db.list_playlists)
    return [p.to_dict() for p in playlists]


@router.post('/api/monitor/playlists')
async def add_monitor_playlist(request: Request) -> dict[str, Any]:
    db = _require_monitor_db()
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    url = payload.get('url', '')
    interval_minutes = int(payload.get('interval_minutes', 60))

    parsed = spotify.parse_spotify_url(url)
    if parsed is None or parsed[0] != 'playlist':
        raise HTTPException(
            status_code=400, detail='A valid Spotify playlist URL is required'
        )

    _, spotify_id = parsed

    existing = await asyncio.to_thread(db.get_by_spotify_id, spotify_id)
    if existing is not None:
        raise HTTPException(
            status_code=409, detail='This playlist is already being monitored'
        )

    try:
        name, _tracks = await asyncio.to_thread(
            spotify.playlist_info_and_tracks, spotify_id
        )
    except Exception as exc:
        logger.exception('Failed to resolve playlist {}', spotify_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    playlist = await asyncio.to_thread(
        db.add_playlist, spotify_id, name, url, interval_minutes
    )

    # Kick off the first download pass immediately so the user does not have
    # to wait up to a full monitor sweep interval for the initial backfill.
    if state.downloader is not None:
        loop = state.loop or asyncio.get_running_loop()

        async def _initial_check(pl=playlist) -> None:
            try:
                await check_playlist(
                    pl,
                    db,
                    state.downloader,  # type: ignore[arg-type]
                    state.connections.broadcast,
                    loop,
                    state.settings,
                )
            except Exception:
                logger.exception('Initial check failed for playlist {}', pl.id)

        asyncio.create_task(_initial_check())

    return playlist.to_dict()


@router.patch('/api/monitor/playlists/{playlist_id}')
async def update_monitor_playlist(
    playlist_id: int, request: Request
) -> dict[str, Any]:
    db = _require_monitor_db()
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    kwargs: dict[str, Any] = {}
    if 'interval_minutes' in payload:
        kwargs['interval_minutes'] = int(payload['interval_minutes'])
    if 'enabled' in payload:
        kwargs['enabled'] = bool(payload['enabled'])

    updated = await asyncio.to_thread(
        db.update_playlist, playlist_id, **kwargs
    )
    if updated is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    return updated.to_dict()


@router.delete('/api/monitor/playlists/{playlist_id}')
async def delete_monitor_playlist(playlist_id: int) -> dict[str, Any]:
    db = _require_monitor_db()
    deleted = await asyncio.to_thread(db.delete_playlist, playlist_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    return {'deleted': True, 'id': playlist_id}


@router.post('/api/monitor/playlists/{playlist_id}/check')
async def manual_check_playlist(playlist_id: int) -> dict[str, Any]:
    db = _require_monitor_db()
    playlist = await asyncio.to_thread(db.get_playlist, playlist_id)
    if playlist is None:
        raise HTTPException(
            status_code=404, detail='Monitored playlist not found'
        )
    if state.downloader is None:
        raise HTTPException(status_code=500, detail='Downloader not ready')

    loop = state.loop or asyncio.get_running_loop()

    async def _run() -> None:
        try:
            count = await check_playlist(
                playlist,  # type: ignore[arg-type]
                db,
                state.downloader,  # type: ignore[arg-type]
                state.connections.broadcast,
                loop,
            )
            logger.info(
                'Manual check: downloaded {} new track(s) from "{}"',
                count,
                playlist.name,
            )  # type: ignore[union-attr]
        except Exception:
            logger.exception(
                'Manual check failed for playlist {}', playlist_id
            )

    asyncio.create_task(_run())
    return {'status': 'check_started', 'id': playlist_id}
