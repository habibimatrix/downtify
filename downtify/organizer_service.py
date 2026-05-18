"""Downtify Organizer Service.

Background-Thread der innerhalb des Downtify-Containers läuft.
Übernimmt:
- Auto-Organisation neu heruntergeladener Songs aus /downloads
- Scanner-Ordner: importiert extern beschaffte Songs (mit AudD-Erkennung)
- Multi-Source Genre-Lookup (Spotify → Deezer → Last.fm → MusicBrainz → Sprache)
- Single Source of Truth: eigene SQLite (/data/organizer.db)
- Best-of-Logik mit automatischer Album-Migration

Konfiguration ausschließlich via Umgebungsvariablen.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import COMM
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

try:
    import acoustid as _acoustid_mod  # type: ignore[import-untyped]
    _HAS_ACOUSTID = True
except ImportError:
    _acoustid_mod = None  # type: ignore[assignment]
    _HAS_ACOUSTID = False

try:
    import discogs_client as _discogs_mod  # type: ignore[import-untyped]
    _HAS_DISCOGS = True
except ImportError:
    _discogs_mod = None  # type: ignore[assignment]
    _HAS_DISCOGS = False

try:
    from shazamio import Shazam as _Shazam  # type: ignore[import-untyped]
    _HAS_SHAZAM = True
except ImportError:
    _Shazam = None  # type: ignore[assignment, misc]
    _HAS_SHAZAM = False

# ── Konfiguration ─────────────────────────────────────────────────────────────

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/downloads"))
MUSIK_DIR = Path(os.getenv("MUSIK_DIR", "/musik"))
SCANNER_DIR = Path(os.getenv("SCANNER_DIR", "/scanner"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "organizer.db"

POLL_INTERVAL = int(os.getenv("ORGANIZER_POLL_INTERVAL", "60"))
FILE_COOLDOWN = int(os.getenv("ORGANIZER_FILE_COOLDOWN", "30"))

SPOTIFY_CLIENT_ID = os.getenv("CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN", "")

ENABLE_DOWNLOAD_WATCHER = os.getenv("ENABLE_DOWNLOAD_WATCHER", "true").lower() == "true"
ENABLE_SCANNER = os.getenv("ENABLE_SCANNER", "true").lower() == "true"

DEFAULT_FOLDER = "Sonstiges"
BESTOF_MIN = 2

AUDIO_EXT = {".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac", ".opus"}

MB_HEADERS = {"User-Agent": "DowntifyOrganizer/1.0 (self-hosted-nas)"}

# Global semaphore: MusicBrainz enforces 1 req/sec across the entire process
_MB_SEMAPHORE = threading.Semaphore(1)

SOUNDCLOUD_CLIENT_ID = os.getenv("SOUNDCLOUD_CLIENT_ID", "")

DEFAULT_SEPARATORS: list[str] = [
    "feat.", "ft.", "featuring", "feat", "&", " x ", "vs.", "vs",
    "with", "and", "×", "+", "/", "✕", "pres.", "presents",
    "prod.", "produced by", "meets",
]

log = logging.getLogger("downtify.organizer")

# ── Genre/Region Mapping ──────────────────────────────────────────────────────

# Reihenfolge zählt: spezifischere Patterns zuerst (erste Übereinstimmung gewinnt).
# Diese Liste wird als Fallback verwendet wenn settings.json keine genre_rules hat.
DEFAULT_GENRE_RULES: list[tuple[str, str]] = [

    # ══════════════════════════════════════════════════════════════════════════
    #  BLOCK 1 – STIL-GENRES  (höchste Priorität)
    #  Teil A: HYBRIDE – regional+stil Compound-Patterns → Sprach-Ordner.
    #          Müssen VOR ihrem generischen Stil-Keyword stehen.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Hybride: K-Pop ────────────────────────────────────────────────────────
    ("k-pop", "K-Pop"),
    ("kpop", "K-Pop"),
    ("k-r&b", "K-Pop"),
    ("k-hip hop", "K-Pop"),
    ("k-rap", "K-Pop"),
    ("k-indie", "K-Pop"),
    ("k-ballad", "K-Pop"),
    ("korean r&b", "K-Pop"),
    ("korean pop", "K-Pop"),
    ("korean hip hop", "K-Pop"),
    ("trot", "K-Pop"),

    # ── Hybride: Japanisch ────────────────────────────────────────────────────
    ("j-pop", "Japanisch"),
    ("jpop", "Japanisch"),
    ("j-rock", "Japanisch"),
    ("j-rap", "Japanisch"),
    ("j-soul", "Japanisch"),
    ("j-hip hop", "Japanisch"),
    ("idol pop", "Japanisch"),
    ("anison", "Japanisch"),
    ("visual kei", "Japanisch"),
    ("city pop", "Japanisch"),
    ("shibuya-kei", "Japanisch"),
    ("oshare kei", "Japanisch"),

    # ── Hybride: Latin ────────────────────────────────────────────────────────
    ("reggaeton", "Latin"),
    ("trap latino", "Latin"),
    ("latin pop", "Latin"),
    ("latin trap", "Latin"),
    ("latin urban", "Latin"),
    ("urban latin", "Latin"),
    ("latin rock", "Latin"),
    ("latin jazz", "Latin"),
    ("latin alternative", "Latin"),
    ("latin hip hop", "Latin"),
    ("cumbia", "Latin"),
    ("cumbia villera", "Latin"),
    ("salsa", "Latin"),
    ("bachata", "Latin"),
    ("merengue", "Latin"),
    ("dembow", "Latin"),
    ("bossa nova", "Latin"),
    ("samba", "Latin"),
    ("sertanejo", "Latin"),
    ("sertanejo universitário", "Latin"),
    ("forro", "Latin"),
    ("forró", "Latin"),
    ("axé", "Latin"),
    ("axe music", "Latin"),
    ("pagode", "Latin"),
    ("baile funk", "Latin"),
    ("funk carioca", "Latin"),
    ("funk brasileiro", "Latin"),
    ("funk ostentação", "Latin"),
    ("vallenato", "Latin"),
    ("norteño", "Latin"),
    ("norteno", "Latin"),
    ("ranchera", "Latin"),
    ("mariachi", "Latin"),
    ("corrido", "Latin"),
    ("corridos tumbados", "Latin"),
    ("narcocorrido", "Latin"),
    ("banda", "Latin"),
    ("grupero", "Latin"),
    ("grupera", "Latin"),
    ("flamenco", "Latin"),
    ("zouk", "Latin"),
    ("calypso", "Latin"),
    ("soca", "Latin"),
    ("punta", "Latin"),
    ("mambo", "Latin"),
    ("cha-cha-cha", "Latin"),
    ("bolero", "Latin"),
    ("son cubano", "Latin"),
    ("timba", "Latin"),
    ("nueva canción", "Latin"),
    ("nueva cancion", "Latin"),
    ("tropicália", "Latin"),
    ("tropicalia", "Latin"),
    ("mpb", "Latin"),

    # ── Hybride: Rap-regional ─────────────────────────────────────────────────
    ("deutschrap", "Deutschrap"),
    ("german rap", "Deutschrap"),
    ("french rap", "Rap"),
    ("rap français", "Rap"),
    ("rap francais", "Rap"),
    ("uk rap", "Rap"),
    ("italian rap", "Rap"),
    ("spanish rap", "Rap"),
    ("arabic rap", "Rap"),
    ("persian rap", "Persisch"),
    ("gangsta rap", "Rap"),
    ("conscious rap", "Rap"),
    ("horrorcore", "Rap"),
    ("battle rap", "Rap"),
    ("freestyle rap", "Rap"),
    ("memphis rap", "Phonk"),

    # ── Hybride: Rock-regional ────────────────────────────────────────────────
    ("anatolian rock", "Türkisch"),
    ("raga rock", "Indisch"),
    ("blues rock", "Rock"),
    ("folk rock", "Rock"),
    ("country rock", "Rock"),

    # ── Hybride: Indisch-Stil ─────────────────────────────────────────────────
    ("desi hip hop", "Indisch"),
    ("sufi pop", "Indisch"),
    ("desi pop", "Indisch"),
    ("hindi pop", "Indisch"),
    ("urdu pop", "Indisch"),
    ("tamil pop", "Indisch"),
    ("telugu pop", "Indisch"),
    ("punjabi pop", "Indisch"),
    ("persian pop", "Persisch"),
    ("persian classical", "Persisch"),
    ("persian traditional", "Persisch"),
    ("persian folk", "Persisch"),
    ("iranian pop", "Persisch"),
    ("farsi pop", "Persisch"),
    ("afghan pop", "Persisch"),
    ("israeli pop", "Hebräisch"),
    ("mediterranean israeli", "Hebräisch"),
    ("musica mizrahit", "Hebräisch"),
    ("pop romanesc", "Rumänisch"),
    ("muzica populara", "Rumänisch"),

    # ── Hybride: Afrikanisch-Stil ─────────────────────────────────────────────
    ("afro house", "Afrohouse"),
    ("afro tech", "Afrikanisch"),

    # ══════════════════════════════════════════════════════════════════════════
    #  Teil B: REINE STIL-GENRES  (spezifisch → generisch)
    # ══════════════════════════════════════════════════════════════════════════

    # ── Phonk ─────────────────────────────────────────────────────────────────
    ("drift phonk", "Phonk"),
    ("memphis phonk", "Phonk"),
    ("raver phonk", "Phonk"),
    ("pluggnb", "Phonk"),
    ("phonk", "Phonk"),

    # ── Goa / Psytrance ──────────────────────────────────────────────────────
    ("progressive psy", "Goa"),
    ("psychedelic trance", "Goa"),
    ("psy trance", "Goa"),
    ("darkpsy", "Goa"),
    ("dark psy", "Goa"),
    ("forest psy", "Goa"),
    ("hi-tech psy", "Goa"),
    ("twilight psy", "Goa"),
    ("suomisaundi", "Goa"),
    ("nitzhonot", "Goa"),
    ("full on", "Goa"),
    ("psytrance", "Goa"),
    ("goa", "Goa"),

    # ── Drop / Bass / DnB / Hardcore ─────────────────────────────────────────
    ("drum and bass", "Drop"),
    ("drum & bass", "Drop"),
    ("liquid dnb", "Drop"),
    ("liquid drum", "Drop"),
    ("neurofunk", "Drop"),
    ("d&b", "Drop"),
    ("dnb", "Drop"),
    ("hardcore techno", "Drop"),
    ("uk hardcore", "Drop"),
    ("happy hardcore", "Drop"),
    ("gabber", "Drop"),
    ("terrorcore", "Drop"),
    ("speedcore", "Drop"),
    ("frenchcore", "Drop"),
    ("melodic dubstep", "Drop"),
    ("brostep", "Drop"),
    ("deathstep", "Drop"),
    ("neurostep", "Drop"),
    ("tearout", "Drop"),
    ("riddim", "Drop"),
    ("dubstep", "Drop"),
    ("bass house", "Drop"),
    ("hardstyle", "Drop"),
    ("rawstyle", "Drop"),
    ("hybrid trap", "Drop"),
    ("glitch hop", "Drop"),
    ("moombahton", "Drop"),
    ("jungle", "Drop"),
    ("breakbeat", "Drop"),
    ("breaks", "Drop"),
    ("future bass", "Drop"),
    ("wave", "Drop"),
    ("dark clubbing", "Drop"),
    ("industrial techno", "Drop"),
    ("midtempo", "Drop"),
    ("bass music", "Drop"),
    ("hardcore", "Drop"),

    # ── House / Techno / Trance ───────────────────────────────────────────────
    ("deep house", "House"),
    ("tech house", "House"),
    ("progressive house", "House"),
    ("future house", "House"),
    ("big room house", "House"),
    ("ambient house", "House"),
    ("lo-fi house", "House"),
    ("tropical house", "House"),
    ("melodic house", "House"),
    ("organic house", "House"),
    ("funky house", "House"),
    ("soulful house", "House"),
    ("jackin house", "House"),
    ("chicago house", "House"),
    ("acid house", "House"),
    ("electro house", "House"),
    ("progressive trance", "House"),
    ("vocal trance", "House"),
    ("acid techno", "House"),
    ("melodic techno", "House"),
    ("minimal techno", "House"),
    ("detroit techno", "House"),
    ("uk garage", "House"),
    ("speed garage", "House"),
    ("uk funky", "House"),
    ("2-step", "House"),
    ("complextro", "House"),
    ("microhouse", "House"),
    ("nu-disco", "House"),
    ("italo disco", "House"),
    ("big room", "House"),
    ("mainstage", "House"),
    ("electronica", "House"),
    ("electro", "House"),
    ("house", "House"),
    ("minimal", "House"),
    ("techno", "House"),
    ("trance", "House"),
    ("edm", "House"),
    ("electronic", "House"),

    # ── Party / Dance / Disco ─────────────────────────────────────────────────
    ("eurodance", "Party"),
    ("dance pop", "Party"),
    ("bubblegum dance", "Party"),
    ("commercial dance", "Party"),
    ("disco polo", "Party"),
    ("italodance", "Party"),
    ("italodisco", "Party"),
    ("europop", "Party"),
    ("teen pop", "Party"),
    ("hands up", "Party"),
    ("schlager", "Party"),
    ("nu disco", "Party"),
    ("italo", "Party"),
    ("disco", "Party"),
    ("club", "Party"),
    ("party", "Party"),
    ("dance", "Party"),

    # ── Rap ───────────────────────────────────────────────────────────────────
    # trap/drill VOR rap (Substring-Fix: "rap" ist in "trap" enthalten)
    ("trap", "HipHop"),
    ("drill", "HipHop"),
    ("rap", "Rap"),

    # ── HipHop ───────────────────────────────────────────────────────────────
    ("uk drill", "HipHop"),
    ("afro drill", "HipHop"),
    ("east coast rap", "HipHop"),
    ("west coast rap", "HipHop"),
    ("southern rap", "HipHop"),
    ("dirty south", "HipHop"),
    ("boom bap", "HipHop"),
    ("cloud rap", "HipHop"),
    ("mumble rap", "HipHop"),
    ("emo rap", "HipHop"),
    ("lo-fi hip hop", "HipHop"),
    ("lofi hip hop", "HipHop"),
    ("lo-fi rap", "HipHop"),
    ("jazz rap", "HipHop"),
    ("alternative hip hop", "HipHop"),
    ("abstract hip hop", "HipHop"),
    ("instrumental hip hop", "HipHop"),
    ("grime", "HipHop"),
    ("crunk", "HipHop"),
    ("snap", "HipHop"),
    ("chopped and screwed", "HipHop"),
    ("chillhop", "HipHop"),
    ("vaporwave", "HipHop"),
    ("hip hop", "HipHop"),
    ("hip-hop", "HipHop"),
    ("hiphop", "HipHop"),

    # ── Rock / Metal ─────────────────────────────────────────────────────────
    ("alternative rock", "Rock"),
    ("alt rock", "Rock"),
    ("indie rock", "Rock"),
    ("hard rock", "Rock"),
    ("symphonic metal", "Rock"),
    ("progressive metal", "Rock"),
    ("gothic metal", "Rock"),
    ("funk metal", "Rock"),
    ("heavy metal", "Rock"),
    ("thrash metal", "Rock"),
    ("death metal", "Rock"),
    ("black metal", "Rock"),
    ("doom metal", "Rock"),
    ("stoner metal", "Rock"),
    ("sludge metal", "Rock"),
    ("power metal", "Rock"),
    ("nu-metal", "Rock"),
    ("nu metal", "Rock"),
    ("prog metal", "Rock"),
    ("progressive rock", "Rock"),
    ("prog rock", "Rock"),
    ("post-punk", "Rock"),
    ("post-grunge", "Rock"),
    ("post-rock", "Rock"),
    ("psychedelic rock", "Rock"),
    ("garage rock", "Rock"),
    ("noise rock", "Rock"),
    ("math rock", "Rock"),
    ("stoner rock", "Rock"),
    ("metalcore", "Rock"),
    ("deathcore", "Rock"),
    ("rapcore", "Rock"),
    ("new wave", "Rock"),
    ("darkwave", "Rock"),
    ("gothic rock", "Rock"),
    ("goth", "Rock"),
    ("shoegaze", "Rock"),
    ("britpop", "Rock"),
    ("screamo", "Rock"),
    ("emo", "Rock"),
    ("grunge", "Rock"),
    ("punk", "Rock"),
    ("metal", "Rock"),
    ("rock", "Rock"),

    # ── Classic Oldies ────────────────────────────────────────────────────────
    ("rock and roll", "Classic Oldies"),
    ("doo-wop", "Classic Oldies"),
    ("film score", "Classic Oldies"),
    ("game soundtrack", "Classic Oldies"),
    ("soundtrack", "Classic Oldies"),
    ("cinematic", "Classic Oldies"),
    ("classical", "Classic Oldies"),
    ("baroque", "Classic Oldies"),
    ("renaissance", "Classic Oldies"),
    ("cool jazz", "Classic Oldies"),
    ("big band", "Classic Oldies"),
    ("bebop", "Classic Oldies"),
    ("dixieland", "Classic Oldies"),
    ("swing", "Classic Oldies"),
    ("jazz", "Classic Oldies"),
    ("blues", "Classic Oldies"),
    ("bluegrass", "Classic Oldies"),
    ("country", "Classic Oldies"),
    ("folk", "Classic Oldies"),
    ("gospel", "Classic Oldies"),
    ("spiritual", "Classic Oldies"),
    ("opera", "Classic Oldies"),
    ("chanson", "Classic Oldies"),
    ("variété", "Classic Oldies"),
    ("schlager oldies", "Classic Oldies"),
    ("oldies", "Classic Oldies"),

    # ── R&B / Soul ────────────────────────────────────────────────────────────
    ("contemporary r&b", "R&B"),
    ("alternative r&b", "R&B"),
    ("alt r&b", "R&B"),
    ("future r&b", "R&B"),
    ("new jack swing", "R&B"),
    ("neo soul", "R&B"),
    ("quiet storm", "R&B"),
    ("disco soul", "R&B"),
    ("rhythm and blues", "R&B"),
    ("trip hop", "R&B"),
    ("motown", "R&B"),
    ("r&b", "R&B"),
    ("rnb", "R&B"),
    ("soul", "R&B"),
    ("funk", "R&B"),

    # ── Pop (generisch) ───────────────────────────────────────────────────────
    ("synth-pop", "Pop"),
    ("synthpop", "Pop"),
    ("electropop", "Pop"),
    ("indie pop", "Pop"),
    ("dream pop", "Pop"),
    ("art pop", "Pop"),
    ("chamber pop", "Pop"),
    ("baroque pop", "Pop"),
    ("bedroom pop", "Pop"),
    ("lo-fi pop", "Pop"),
    ("acoustic pop", "Pop"),
    ("singer-songwriter", "Pop"),
    ("pop", "Pop"),

    # ── Sonstiges-Stil ────────────────────────────────────────────────────────
    ("reggae", "Sonstiges"),
    ("dancehall", "Sonstiges"),
    ("ska", "Sonstiges"),
    ("dub", "Sonstiges"),
    ("ambient", "Sonstiges"),
    ("new age", "Sonstiges"),
    ("meditation", "Sonstiges"),
    ("lounge", "Sonstiges"),
    ("easy listening", "Sonstiges"),
    ("chillout", "House"),
    ("downtempo", "Sonstiges"),
    ("world music", "Sonstiges"),
    ("fado", "Sonstiges"),
    ("celtic", "Sonstiges"),
    ("irish folk", "Sonstiges"),

    # ══════════════════════════════════════════════════════════════════════════
    #  BLOCK 2 – SPRACHE / REGION  (zweite Priorität)
    # ══════════════════════════════════════════════════════════════════════════

    # ── Indisch / Südasien ────────────────────────────────────────────────────
    ("bollywood", "Indisch"),
    ("filmi", "Indisch"),
    ("kollywood", "Indisch"),
    ("tollywood", "Indisch"),
    ("mollywood", "Indisch"),
    ("bhangra", "Indisch"),
    ("punjabi", "Indisch"),
    ("hindustani", "Indisch"),
    ("carnatic", "Indisch"),
    ("ghazal", "Indisch"),
    ("qawwali", "Indisch"),
    ("desi", "Indisch"),
    ("hindi", "Indisch"),
    ("urdu", "Indisch"),
    ("tamil", "Indisch"),
    ("telugu", "Indisch"),
    ("bengali", "Indisch"),
    ("kannada", "Indisch"),
    ("malayalam", "Indisch"),
    ("marathi", "Indisch"),
    ("gujarati", "Indisch"),
    ("rajasthani", "Indisch"),
    ("garba", "Indisch"),
    ("dandiya", "Indisch"),
    ("bhajan", "Indisch"),
    ("kirtan", "Indisch"),
    ("baul", "Indisch"),
    ("lavani", "Indisch"),
    ("rabindra sangeet", "Indisch"),
    ("thumri", "Indisch"),
    ("dhrupad", "Indisch"),
    ("raga", "Indisch"),
    ("indipop", "Indisch"),
    ("indi-pop", "Indisch"),
    ("india pop", "Indisch"),
    ("nepali", "Indisch"),
    ("sinhala", "Indisch"),
    ("indian", "Indisch"),

    # ── Afrikanisch ───────────────────────────────────────────────────────────
    ("afrobeats", "Afrikanisch"),
    ("afrobeat", "Afrikanisch"),
    ("afropop", "Afrikanisch"),
    ("afrofusion", "Afrikanisch"),
    ("afro pop", "Afrikanisch"),
    ("afro fusion", "Afrikanisch"),
    ("afro soul", "Afrikanisch"),
    ("afro dancehall", "Afrikanisch"),
    ("afro swing", "Afrikanisch"),
    ("afrojuju", "Afrikanisch"),
    ("afrowave", "Afrikanisch"),
    ("amapiano", "Afrikanisch"),
    ("highlife", "Afrikanisch"),
    ("hiplife", "Afrikanisch"),
    ("juju music", "Afrikanisch"),
    ("juju", "Afrikanisch"),
    ("fuji music", "Afrikanisch"),
    ("kwaito", "Afrikanisch"),
    ("gqom", "Afrikanisch"),
    ("soukous", "Afrikanisch"),
    ("congolese rumba", "Afrikanisch"),
    ("mbalax", "Afrikanisch"),
    ("bikutsi", "Afrikanisch"),
    ("makossa", "Afrikanisch"),
    ("chimurenga", "Afrikanisch"),
    ("mbaqanga", "Afrikanisch"),
    ("isicathamiya", "Afrikanisch"),
    ("bongo flava", "Afrikanisch"),
    ("naija", "Afrikanisch"),
    ("gnawa", "Afrikanisch"),
    ("zouglou", "Afrikanisch"),
    ("coupé-décalé", "Afrikanisch"),
    ("coupe decale", "Afrikanisch"),
    ("ethio-jazz", "Afrikanisch"),
    ("ethiojazz", "Afrikanisch"),
    ("afrotech", "Afrikanisch"),
    ("south african", "Afrikanisch"),
    ("nigerian", "Afrikanisch"),
    ("ghanaian", "Afrikanisch"),
    ("kenyan", "Afrikanisch"),
    ("tanzanian", "Afrikanisch"),
    ("ugandan", "Afrikanisch"),
    ("congolese", "Afrikanisch"),
    ("zimbabwean", "Afrikanisch"),
    ("african", "Afrikanisch"),

    # ── Persisch / Iranisch ───────────────────────────────────────────────────
    ("persian", "Persisch"),
    ("iranian", "Persisch"),
    ("irani", "Persisch"),
    ("farsi", "Persisch"),
    ("losanjelesi", "Persisch"),
    ("dastgah", "Persisch"),
    ("radif", "Persisch"),
    ("tajik", "Persisch"),
    ("tajiki", "Persisch"),
    ("afghani", "Persisch"),
    ("pashto", "Persisch"),
    ("dari", "Persisch"),
    ("kurdish", "Persisch"),

    # ── Hebräisch / Israelisch ────────────────────────────────────────────────
    ("mizrahi", "Hebräisch"),
    ("mizrahit", "Hebräisch"),
    ("israeli", "Hebräisch"),
    ("hebrew", "Hebräisch"),
    ("piyyut", "Hebräisch"),
    ("yiddish", "Hebräisch"),
    ("klezmer", "Hebräisch"),
    ("niggun", "Hebräisch"),
    ("hasidic", "Hebräisch"),

    # ── Rumänisch ─────────────────────────────────────────────────────────────
    ("manele", "Rumänisch"),
    ("romanian", "Rumänisch"),
    ("hora", "Rumänisch"),
    ("doina", "Rumänisch"),
    ("lautareasca", "Rumänisch"),
    ("lautaresc", "Rumänisch"),
    ("maneaua", "Rumänisch"),

    # ── Albanisch ─────────────────────────────────────────────────────────────
    ("albanian", "Albanisch"),
    ("shqip", "Albanisch"),
    ("kosovan", "Albanisch"),
    ("tallava", "Albanisch"),
    ("iso polyphony", "Albanisch"),
    ("valle", "Albanisch"),
    ("çifteli", "Albanisch"),

    # ── Türkisch ──────────────────────────────────────────────────────────────
    ("turk pop", "Türkisch"),
    ("türk pop", "Türkisch"),
    ("arabesk", "Türkisch"),
    ("arabesque", "Türkisch"),
    ("türkçe", "Türkisch"),
    ("türkü", "Türkisch"),
    ("turku", "Türkisch"),
    ("halk müziği", "Türkisch"),
    ("halk muzigi", "Türkisch"),
    ("anatolian", "Türkisch"),
    ("sanat müziği", "Türkisch"),
    ("sanat muzigi", "Türkisch"),
    ("fantezi", "Türkisch"),
    ("damar", "Türkisch"),
    ("özgün müzik", "Türkisch"),
    ("çalgı", "Türkisch"),
    ("roman havası", "Türkisch"),
    ("turkish", "Türkisch"),

    # ── Arabisch ──────────────────────────────────────────────────────────────
    ("arab pop", "Arabisch"),
    ("khaleeji", "Arabisch"),
    ("khaliji", "Arabisch"),
    ("levantine", "Arabisch"),
    ("shaabi", "Arabisch"),
    ("sha'bi", "Arabisch"),
    ("sha3bi", "Arabisch"),
    ("tarab", "Arabisch"),
    ("maqam", "Arabisch"),
    ("nasheed", "Arabisch"),
    ("sawt", "Arabisch"),
    ("mawal", "Arabisch"),
    ("mawwal", "Arabisch"),
    ("dabke", "Arabisch"),
    ("nubian", "Arabisch"),
    ("moroccan", "Arabisch"),
    ("algerian", "Arabisch"),
    ("tunisian", "Arabisch"),
    ("egyptian", "Arabisch"),
    ("gulf music", "Arabisch"),
    ("sudanese", "Arabisch"),
    ("libyan", "Arabisch"),
    ("yemeni", "Arabisch"),
    ("iraqi", "Arabisch"),
    ("rai", "Arabisch"),
    ("raï", "Arabisch"),
    ("arabic", "Arabisch"),

    # ── Russia / GUS ──────────────────────────────────────────────────────────
    ("shanson", "Russia"),
    ("chanson russe", "Russia"),
    ("russki", "Russia"),
    ("bard music", "Russia"),
    ("soviet", "Russia"),
    ("georgian pop", "Russia"),
    ("kazakh", "Russia"),
    ("uzbek", "Russia"),
    ("turkmen", "Russia"),
    ("armenian", "Russia"),
    ("moldovan", "Russia"),
    ("belarusian", "Russia"),
    ("kyrgyz", "Russia"),
    ("azerbaijani", "Russia"),
    ("latvian", "Russia"),
    ("lithuanian", "Russia"),
    ("estonian", "Russia"),
    ("russian", "Russia"),
    ("ukrainian", "Russia"),

    # ── Griechisch ────────────────────────────────────────────────────────────
    ("laika", "Griechisch"),
    ("laïká", "Griechisch"),
    ("rebetiko", "Griechisch"),
    ("rembetiko", "Griechisch"),
    ("entechno", "Griechisch"),
    ("skyladiko", "Griechisch"),
    ("dimotika", "Griechisch"),
    ("nisiotika", "Griechisch"),
    ("kantades", "Griechisch"),
    ("elafrolaika", "Griechisch"),
    ("greek", "Griechisch"),

    # ── Serbisch / Balkan ─────────────────────────────────────────────────────
    ("sevdalinka", "Serbisch"),
    ("sevdah", "Serbisch"),
    ("turbofolk", "Serbisch"),
    ("turbo folk", "Serbisch"),
    ("novokomponovana", "Serbisch"),
    ("narodna muzika", "Serbisch"),
    ("narodnjaci", "Serbisch"),
    ("trubaci", "Serbisch"),
    ("gusle", "Serbisch"),
    ("yugoslav", "Serbisch"),
    ("ex-yu", "Serbisch"),
    ("exyu", "Serbisch"),
    ("slovene", "Serbisch"),
    ("slovenian", "Serbisch"),
    ("bulgarian", "Serbisch"),
    ("macedonian", "Serbisch"),
    ("cocek", "Serbisch"),
    ("čoček", "Serbisch"),
    ("bosnian", "Serbisch"),
    ("croatian", "Serbisch"),
    ("serbian", "Serbisch"),
    ("balkan", "Serbisch"),

    # ── K-Pop (Breit-Keyword) ─────────────────────────────────────────────────
    ("korean", "K-Pop"),

    # ── Japanisch (Breit-Keywords) ────────────────────────────────────────────
    ("anime", "Japanisch"),
    ("enka", "Japanisch"),
    ("kayokyoku", "Japanisch"),
    ("japanese", "Japanisch"),

    # ── Latin (Breit-Keyword) ─────────────────────────────────────────────────
    ("latin", "Latin"),

    # ── Sonstiges-Sprache ─────────────────────────────────────────────────────
    ("mandopop", "Sonstiges"),
    ("cantopop", "Sonstiges"),
    ("c-pop", "Sonstiges"),
    ("thai pop", "Sonstiges"),
    ("opm", "Sonstiges"),
    ("pinoy pop", "Sonstiges"),
    ("vietnamese pop", "Sonstiges"),
    ("k-trot", "Sonstiges"),
]

DEFAULT_COUNTRY_TO_FOLDER: dict[str, str] = {
    # ── Rumänisch ──────────────────────────────────────────────────────────────
    "RO": "Rumänisch",
    # ── Albanisch ──────────────────────────────────────────────────────────────
    "AL": "Albanisch", "XK": "Albanisch", "MK": "Albanisch",
    # ── Russia / GUS ───────────────────────────────────────────────────────────
    "RU": "Russia", "UA": "Russia", "BY": "Russia", "MD": "Russia",
    "KZ": "Russia", "UZ": "Russia", "TM": "Russia", "KG": "Russia",
    "GE": "Russia", "AM": "Russia",
    "LT": "Russia", "LV": "Russia", "EE": "Russia",
    # ── Türkisch ───────────────────────────────────────────────────────────────
    "TR": "Türkisch", "AZ": "Türkisch",
    # ── Arabisch ───────────────────────────────────────────────────────────────
    "SA": "Arabisch", "AE": "Arabisch", "EG": "Arabisch", "MA": "Arabisch",
    "LB": "Arabisch", "JO": "Arabisch", "SY": "Arabisch", "IQ": "Arabisch",
    "DZ": "Arabisch", "TN": "Arabisch", "LY": "Arabisch", "YE": "Arabisch",
    "PS": "Arabisch", "BH": "Arabisch", "KW": "Arabisch", "OM": "Arabisch",
    "QA": "Arabisch", "SD": "Arabisch", "SS": "Arabisch", "MR": "Arabisch",
    "SO": "Arabisch", "DJ": "Arabisch", "KM": "Arabisch",
    # ── Griechisch ─────────────────────────────────────────────────────────────
    "GR": "Griechisch", "CY": "Griechisch",
    # ── Serbisch ───────────────────────────────────────────────────────────────
    "RS": "Serbisch", "ME": "Serbisch", "BA": "Serbisch", "HR": "Serbisch",
    "SI": "Serbisch", "BG": "Serbisch",
    # ── K-Pop ─────────────────────────────────────────────────────────────────
    "KR": "K-Pop",
    # ── Japanisch ─────────────────────────────────────────────────────────────
    "JP": "Japanisch",
    # ── Latin ─────────────────────────────────────────────────────────────────
    "BR": "Latin", "AR": "Latin", "MX": "Latin", "CO": "Latin",
    "CL": "Latin", "PE": "Latin", "PR": "Latin", "DO": "Latin",
    "VE": "Latin", "CU": "Latin", "ES": "Latin", "PT": "Latin",
    "PY": "Latin", "UY": "Latin", "BO": "Latin", "EC": "Latin",
    "GT": "Latin", "HN": "Latin", "SV": "Latin", "NI": "Latin",
    "CR": "Latin", "PA": "Latin", "HT": "Latin", "GP": "Latin",
    "MQ": "Latin", "GF": "Latin", "MF": "Latin",
    # ── Indisch / Südasien ─────────────────────────────────────────────────────
    "IN": "Indisch", "PK": "Indisch", "BD": "Indisch", "LK": "Indisch",
    "NP": "Indisch", "BT": "Indisch", "MV": "Indisch",
    "TJ": "Persisch",
    # ── Afrikanisch ────────────────────────────────────────────────────────────
    "NG": "Afrikanisch", "GH": "Afrikanisch", "ZA": "Afrikanisch",
    "KE": "Afrikanisch", "TZ": "Afrikanisch", "ET": "Afrikanisch",
    "SN": "Afrikanisch", "CI": "Afrikanisch", "CM": "Afrikanisch",
    "CD": "Afrikanisch", "CG": "Afrikanisch", "AO": "Afrikanisch",
    "MZ": "Afrikanisch", "ZW": "Afrikanisch", "MW": "Afrikanisch",
    "ZM": "Afrikanisch", "UG": "Afrikanisch", "RW": "Afrikanisch",
    "BI": "Afrikanisch", "BF": "Afrikanisch", "ML": "Afrikanisch",
    "GN": "Afrikanisch", "GM": "Afrikanisch", "SL": "Afrikanisch",
    "LR": "Afrikanisch", "BJ": "Afrikanisch", "TG": "Afrikanisch",
    "NE": "Afrikanisch", "GW": "Afrikanisch", "CV": "Afrikanisch",
    "ST": "Afrikanisch", "GQ": "Afrikanisch", "GA": "Afrikanisch",
    "CF": "Afrikanisch", "TD": "Afrikanisch", "ER": "Afrikanisch",
    "MG": "Afrikanisch", "NA": "Afrikanisch", "BW": "Afrikanisch",
    "LS": "Afrikanisch", "SZ": "Afrikanisch", "SC": "Afrikanisch",
    "MU": "Afrikanisch", "RE": "Afrikanisch",
    # ── Persisch ───────────────────────────────────────────────────────────────
    "IR": "Persisch", "AF": "Persisch",
    # ── Hebräisch ─────────────────────────────────────────────────────────────
    "IL": "Hebräisch",
    # ── Sonstiges ─────────────────────────────────────────────────────────────
    "DE": "Sonstiges", "AT": "Sonstiges", "CH": "Sonstiges", "FR": "Sonstiges",
    "IT": "Sonstiges", "NL": "Sonstiges", "BE": "Sonstiges", "LU": "Sonstiges",
    "GB": "Sonstiges", "IE": "Sonstiges", "IS": "Sonstiges", "NO": "Sonstiges",
    "SE": "Sonstiges", "DK": "Sonstiges", "FI": "Sonstiges", "MT": "Sonstiges",
    "SM": "Sonstiges", "VA": "Sonstiges", "AD": "Sonstiges", "MC": "Sonstiges",
    "LI": "Sonstiges", "GL": "Sonstiges", "FO": "Sonstiges",
    "PL": "Sonstiges", "CZ": "Sonstiges", "SK": "Sonstiges", "HU": "Sonstiges",
    "US": "Sonstiges", "CA": "Sonstiges",
    "JM": "Sonstiges", "TT": "Sonstiges", "BB": "Sonstiges",
    "AU": "Sonstiges", "NZ": "Sonstiges",
    "CN": "Sonstiges", "TW": "Sonstiges", "HK": "Sonstiges",
    "VN": "Sonstiges", "TH": "Sonstiges", "PH": "Sonstiges",
    "ID": "Sonstiges", "MY": "Sonstiges", "SG": "Sonstiges",
}

# Backward-compat aliases (used in _match_genre_rules / resolve)
GENRE_RULES = DEFAULT_GENRE_RULES
COUNTRY_TO_FOLDER = DEFAULT_COUNTRY_TO_FOLDER

ETHNIC_FOLDERS = {
    "Rumänisch", "Albanisch", "Türkisch", "Arabisch", "Indisch", "Persisch",
    "Hebräisch", "Russia", "Griechisch", "Serbisch", "K-Pop", "Latin",
    "Japanisch", "Afrikanisch", "Afrohouse", "Deutschrap",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sanitize(name: str, fallback: str = "Sonstiges") -> str:
    if not name or not name.strip():
        return fallback
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or fallback


def _primary_artist(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    for sep in ["/", ";"]:
        if sep in s:
            return s.split(sep)[0].strip()
    for marker in [" feat. ", " ft. ", " feat ", " ft ", " featuring "]:
        low = s.lower()
        if marker in low:
            return s[: low.index(marker)].strip()
    for sep in [" & ", " x "]:
        if sep.lower() in s.lower():
            return s[: s.lower().index(sep.lower())].strip()
    if "," in s:
        return s.split(",")[0].strip()
    return s


def _is_stable(path: Path, cooldown: int) -> bool:
    """Datei nicht mehr verändert in den letzten ``cooldown`` Sekunden?"""
    try:
        return (time.time() - path.stat().st_mtime) >= cooldown
    except Exception:
        return False


def _read_tags(path: Path) -> dict:
    result = {"title": None, "artist": None, "album": None, "spotify_id": None}
    try:
        f = MutagenFile(str(path), easy=True)
        if f is None:
            return result
        result["title"] = (f.get("title") or [None])[0]
        result["artist"] = (f.get("artist") or [None])[0]
        result["album"] = (f.get("album") or [None])[0]
        # spotify_id steht häufig in TXXX:SPOTIFY_ID (id3) oder einem custom-tag
        for k in ("spotify_id", "spotifyid", "spotify"):
            v = f.get(k)
            if v:
                result["spotify_id"] = v[0]
                break
    except Exception as e:
        log.warning(f"Tags nicht lesbar für {path.name}: {e}")
    return result


def _write_organizer_comment(path: Path, genre: str, artist: str, album: str, title: str) -> None:
    """Write organizer-resolved metadata into the file's comment tag."""
    comment = f"Genre: {genre} | Artist: {artist} | Album: {album} | Title: {title}"
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            audio = MP3(str(path))
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(COMM(encoding=3, lang='eng', desc='downtify', text=comment))
            audio.save(v2_version=3)
        elif ext in {".m4a", ".mp4", ".aac"}:
            audio = MP4(str(path))
            audio["©cmt"] = comment
            audio.save()
        elif ext == ".flac":
            audio = FLAC(str(path))
            audio["comment"] = comment
            audio.save()
        elif ext == ".ogg":
            audio = OggVorbis(str(path))
            audio["comment"] = comment
            audio.save()
        elif ext == ".opus":
            audio = OggOpus(str(path))
            audio["comment"] = comment
            audio.save()
        log.info(f"  ✎ Kommentar geschrieben: {comment}")
    except Exception as e:
        log.warning(f"  Kommentar-Tag konnte nicht geschrieben werden: {e}")


def _match_genre_rules(genres: list, rules: Optional[list] = None) -> Optional[str]:
    if not genres:
        return None
    joined = " | ".join(g.lower() for g in genres)
    for keyword, folder in (rules if rules is not None else GENRE_RULES):
        if keyword in joined:
            return folder
    return None


def _detect_script(text: str) -> Optional[str]:
    """Erkennt Skript/Sprache anhand der Zeichen im Titel."""
    if not text:
        return None
    for ch in text:
        code = ord(ch)
        if 0x0400 <= code <= 0x04FF:  # Kyrillisch
            return "Russia"
        if 0x0600 <= code <= 0x06FF:  # Arabisch
            return "Arabisch"
        if 0x0370 <= code <= 0x03FF:  # Griechisch
            return "Griechisch"
        if 0xAC00 <= code <= 0xD7AF:  # Hangul (Koreanisch)
            return "K-Pop"
        if 0x3040 <= code <= 0x30FF:  # Hiragana/Katakana
            return "Japanisch"
    return None


# ── Datenbank ─────────────────────────────────────────────────────────────────

class OrganizerDB:
    def __init__(self, path: Path):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock:
            self.conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA wal_autocheckpoint=200;

                CREATE TABLE IF NOT EXISTS processed (
                    file_id      TEXT PRIMARY KEY,    -- "filename:size:mtime" oder spotify_id
                    spotify_id   TEXT,
                    source       TEXT,                -- "download" / "scanner"
                    genre        TEXT,
                    artist       TEXT,
                    album        TEXT,
                    title        TEXT,
                    musik_path   TEXT,
                    processed_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_processed_spotify
                    ON processed(spotify_id);

                CREATE TABLE IF NOT EXISTS artist_genres_cache (
                    artist       TEXT PRIMARY KEY,
                    genres_csv   TEXT,
                    looked_up_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS artist_country_cache (
                    artist       TEXT PRIMARY KEY,
                    country      TEXT,
                    looked_up_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS track_metadata_cache (
                    artist_norm      TEXT NOT NULL,
                    title_norm       TEXT NOT NULL,
                    final_meta_json  TEXT NOT NULL,
                    cached_at        INTEGER NOT NULL,
                    PRIMARY KEY (artist_norm, title_norm)
                );

                CREATE TABLE IF NOT EXISTS metadata_audit (
                    track_id   TEXT PRIMARY KEY,
                    audit_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
            """)
            self.conn.commit()

    def is_processed(self, file_id: str, spotify_id: Optional[str] = None) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM processed WHERE file_id = ? OR (spotify_id IS NOT NULL AND spotify_id = ?)",
                (file_id, spotify_id or ""),
            ).fetchone()
            return row is not None

    def mark_processed(self, file_id, spotify_id, source, genre, artist, album, title, musik_path) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO processed
                   (file_id, spotify_id, source, genre, artist, album, title, musik_path, processed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (file_id, spotify_id, source, genre, artist, album, title,
                 musik_path, int(time.time())),
            )
            self.conn.commit()

    def get_cached_genres(self, artist: str) -> Optional[list]:
        with self.lock:
            row = self.conn.execute(
                "SELECT genres_csv FROM artist_genres_cache WHERE artist=?",
                (artist,)
            ).fetchone()
        if row is None:
            return None
        return [g for g in row[0].split("|") if g]

    def cache_genres(self, artist: str, genres: list) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO artist_genres_cache VALUES (?, ?, ?)",
                (artist, "|".join(genres or []), int(time.time())),
            )
            self.conn.commit()

    def get_cached_country(self, artist: str) -> Optional[str]:
        with self.lock:
            row = self.conn.execute(
                "SELECT country FROM artist_country_cache WHERE artist=?",
                (artist,)
            ).fetchone()
        return row[0] if row else None

    def cache_country(self, artist: str, country: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO artist_country_cache VALUES (?, ?, ?)",
                (artist, country or "", int(time.time())),
            )
            self.conn.commit()

    def get_track_cache(self, artist_norm: str, title_norm: str) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT final_meta_json, cached_at FROM track_metadata_cache WHERE artist_norm=? AND title_norm=?",
                (artist_norm, title_norm),
            ).fetchone()
        if row is None:
            return None
        age_days = (time.time() - row[1]) / 86400
        if age_days > 30:
            return None
        return json.loads(row[0])

    def set_track_cache(self, artist_norm: str, title_norm: str, meta: dict) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO track_metadata_cache (artist_norm, title_norm, final_meta_json, cached_at) VALUES (?, ?, ?, ?)",
                (artist_norm, title_norm, json.dumps(meta), int(time.time())),
            )
            self.conn.commit()

    def delete_track_cache(self, artist_norm: str, title_norm: str) -> None:
        with self.lock:
            self.conn.execute(
                "DELETE FROM track_metadata_cache WHERE artist_norm=? AND title_norm=?",
                (artist_norm, title_norm),
            )
            self.conn.commit()

    def clear_track_cache(self) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM track_metadata_cache")
            self.conn.commit()

    def list_track_cache(self, search: str = "", limit: int = 50, offset: int = 0) -> list:
        with self.lock:
            if search:
                rows = self.conn.execute(
                    """SELECT artist_norm, title_norm, final_meta_json, cached_at
                       FROM track_metadata_cache
                       WHERE artist_norm LIKE ? OR title_norm LIKE ?
                       ORDER BY cached_at DESC LIMIT ? OFFSET ?""",
                    (f"%{search}%", f"%{search}%", limit, offset),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """SELECT artist_norm, title_norm, final_meta_json, cached_at
                       FROM track_metadata_cache
                       ORDER BY cached_at DESC LIMIT ? OFFSET ?""",
                    (limit, offset),
                ).fetchall()
        result = []
        for artist_norm, title_norm, meta_json, cached_at in rows:
            meta = json.loads(meta_json)
            result.append({
                "artist_norm": artist_norm,
                "title_norm": title_norm,
                "cached_at": cached_at,
                **meta,
            })
        return result

    def count_track_cache(self, search: str = "") -> int:
        with self.lock:
            if search:
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM track_metadata_cache WHERE artist_norm LIKE ? OR title_norm LIKE ?",
                    (f"%{search}%", f"%{search}%"),
                ).fetchone()
            else:
                row = self.conn.execute("SELECT COUNT(*) FROM track_metadata_cache").fetchone()
        return row[0] if row else 0

    def save_audit(self, track_id: str, audit_json: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata_audit (track_id, audit_json, created_at) VALUES (?, ?, ?)",
                (track_id, audit_json, int(time.time())),
            )
            self.conn.commit()

    def get_audit(self, track_id: str) -> Optional[dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT audit_json FROM metadata_audit WHERE track_id=?",
                (track_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def shutdown(self) -> None:
        with self.lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            self.conn.close()


# ── Spotify API ──────────────────────────────────────────────────────────────

class SpotifyClient:
    def __init__(self):
        self.token: Optional[str] = None
        self.expiry: float = 0.0

    def get_token(self) -> Optional[str]:
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            return None
        if self.token and time.time() < self.expiry - 60:
            return self.token
        try:
            r = requests.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
                timeout=10,
            )
            if r.status_code == 200:
                d = r.json()
                self.token = d["access_token"]
                self.expiry = time.time() + d.get("expires_in", 3600)
                return self.token
        except Exception as e:
            log.warning(f"Spotify Token Fehler: {e}")
        return None

    def lookup_genres(self, artist: str, title: str) -> list:
        token = self.get_token()
        if not token:
            return []
        h = {"Authorization": f"Bearer {token}"}
        try:
            # Strategie 1: direkt Artist suchen
            r = requests.get(
                "https://api.spotify.com/v1/search",
                params={"q": artist, "type": "artist", "limit": 1},
                headers=h, timeout=10,
            )
            if r.status_code == 200:
                items = r.json().get("artists", {}).get("items", [])
                if items and items[0].get("genres"):
                    return items[0]["genres"]
            # Strategie 2: über Track
            for q in [f"track:{title} artist:{artist}", f"{artist} {title}"]:
                r = requests.get(
                    "https://api.spotify.com/v1/search",
                    params={"q": q, "type": "track", "limit": 1},
                    headers=h, timeout=10,
                )
                if r.status_code != 200:
                    continue
                tracks = r.json().get("tracks", {}).get("items", [])
                if not tracks:
                    continue
                artist_id = tracks[0]["artists"][0]["id"]
                r2 = requests.get(
                    f"https://api.spotify.com/v1/artists/{artist_id}",
                    headers=h, timeout=10,
                )
                if r2.status_code == 200:
                    return r2.json().get("genres", []) or []
        except Exception as e:
            log.warning(f"  Spotify-Fehler: {e}")
        return []

    def search_track(self, artist: str, title: str) -> dict:
        """Full track metadata from Spotify. Returns {genre, artist, album, title} or {}."""
        token = self.get_token()
        if not token:
            return {}
        h = {"Authorization": f"Bearer {token}"}
        try:
            for q in [f"track:{title} artist:{artist}", f"{artist} {title}"]:
                r = requests.get(
                    "https://api.spotify.com/v1/search",
                    params={"q": q, "type": "track", "limit": 1},
                    headers=h, timeout=10,
                )
                if r.status_code != 200:
                    continue
                tracks = r.json().get("tracks", {}).get("items", [])
                if not tracks:
                    continue
                t = tracks[0]
                artist_name = t["artists"][0]["name"] if t.get("artists") else ""
                album_name = t.get("album", {}).get("name", "")
                title_name = t.get("name", "")
                artist_id = t["artists"][0]["id"] if t.get("artists") else ""
                genres: list = []
                if artist_id:
                    r2 = requests.get(
                        f"https://api.spotify.com/v1/artists/{artist_id}",
                        headers=h, timeout=10,
                    )
                    if r2.status_code == 200:
                        genres = r2.json().get("genres", [])
                return {
                    "genre": genres[0] if genres else "",
                    "artist": artist_name,
                    "album": album_name,
                    "title": title_name,
                }
        except Exception as e:
            log.debug(f"  Spotify search_track Fehler: {e}")
        return {}


# ── Deezer API (kein Auth nötig) ─────────────────────────────────────────────

def lookup_deezer(artist: str, title: str) -> list:
    """Deezer Track suchen → Album-Genre auflösen. Kein API-Key nötig."""
    result = search_deezer_track(artist, title)
    if result.get("genre"):
        return [result["genre"]]
    return []


def search_deezer_track(artist: str, title: str) -> dict:
    """Deezer track search → full metadata {genre, artist, album, title}."""
    try:
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": f'artist:"{artist}" track:"{title}"', "limit": 1},
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        items = r.json().get("data", [])
        if not items:
            return {}
        t = items[0]
        artist_name = t.get("artist", {}).get("name", "")
        album_name = t.get("album", {}).get("title", "")
        title_name = t.get("title", "")
        genre = ""
        album_id = t.get("album", {}).get("id")
        if album_id:
            r2 = requests.get(f"https://api.deezer.com/album/{album_id}", timeout=10)
            if r2.status_code == 200:
                genres = r2.json().get("genres", {}).get("data", [])
                if genres:
                    genre = genres[0].get("name", "")
        return {"genre": genre, "artist": artist_name, "album": album_name, "title": title_name}
    except Exception as e:
        log.debug(f"  Deezer-Fehler: {e}")
    return {}


# ── Last.fm API ──────────────────────────────────────────────────────────────

def lookup_lastfm(artist: str) -> list:
    if not LASTFM_API_KEY:
        return []
    try:
        r = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method":  "artist.getTopTags",
                "artist":  artist,
                "api_key": LASTFM_API_KEY,
                "format":  "json",
                "autocorrect": 1,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        tags = r.json().get("toptags", {}).get("tag", [])
        return [t["name"] for t in tags if t.get("name")][:10]
    except Exception as e:
        log.warning(f"  Last.fm-Fehler: {e}")
    return []


def search_lastfm_track(artist: str, title: str) -> dict:
    """Last.fm track.getInfo → full metadata {genre, artist, album, title}."""
    if not LASTFM_API_KEY:
        return {}
    try:
        r = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "track.getInfo",
                "artist": artist,
                "track": title,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "autocorrect": 1,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("track", {})
        if not data:
            return {}
        artist_info = data.get("artist", {})
        artist_name = artist_info.get("name", "") if isinstance(artist_info, dict) else str(artist_info)
        album_info = data.get("album", {})
        album_name = album_info.get("title", "") if isinstance(album_info, dict) else ""
        title_name = data.get("name", "")
        tags = data.get("toptags", {}).get("tag", [])
        genre = tags[0]["name"] if tags and isinstance(tags, list) else ""
        return {"genre": genre, "artist": artist_name, "album": album_name, "title": title_name}
    except Exception as e:
        log.debug(f"  Last.fm search_track Fehler: {e}")
    return {}


# ── MusicBrainz ──────────────────────────────────────────────────────────────

def lookup_musicbrainz_artist(artist: str) -> tuple[Optional[str], list]:
    """Gibt (country, tags) zurück."""
    with _MB_SEMAPHORE:
        try:
            r = requests.get(
                "https://musicbrainz.org/ws/2/artist/",
                params={"query": f'artist:"{artist}"', "fmt": "json", "limit": 1},
                headers=MB_HEADERS, timeout=12,
            )
            time.sleep(1.1)  # Rate-Limit MB: 1 req/sec
            if r.status_code != 200:
                return None, []
            items = r.json().get("artists", [])
            if not items:
                return None, []
            a = items[0]
            country = a.get("country")
            tags = [t["name"] for t in a.get("tags", []) if t.get("name")]
            genres = [g["name"] for g in a.get("genres", []) if g.get("name")]
            return country, tags + genres
        except Exception as e:
            log.warning(f"  MusicBrainz-Fehler: {e}")
    return None, []


def search_musicbrainz_recording(artist: str, title: str) -> dict:
    """MusicBrainz recording search → {artist, album, title} or {}."""
    with _MB_SEMAPHORE:
        try:
            r = requests.get(
                "https://musicbrainz.org/ws/2/recording/",
                params={
                    "query": f'recording:"{title}" AND artist:"{artist}"',
                    "fmt": "json",
                    "limit": 3,
                    "inc": "artist-credits releases",
                },
                headers=MB_HEADERS,
                timeout=12,
            )
            time.sleep(1.1)
            if r.status_code != 200:
                return {}
            recordings = r.json().get("recordings", [])
            if not recordings:
                return {}
            rec = recordings[0]
            rec_title = rec.get("title", "")
            credits = rec.get("artist-credit", [])
            artist_name = ""
            if credits:
                first = credits[0]
                artist_name = first.get("name") or first.get("artist", {}).get("name", "")
            releases = rec.get("releases", [])
            album_name = releases[0].get("title", "") if releases else ""
            return {"artist": artist_name, "album": album_name, "title": rec_title, "genre": ""}
        except Exception as e:
            log.debug(f"  MusicBrainz Recording-Fehler: {e}")
    return {}


# ── AudD Fingerprinting (für Scanner) ────────────────────────────────────────

_audd_quota_exhausted: bool = False
_audd_quota_reset_time: float = 0.0


def audd_identify(path: Path) -> Optional[dict]:
    """Identifiziert eine Datei via AudD. Gibt {artist, title, album} zurück."""
    global _audd_quota_exhausted, _audd_quota_reset_time
    if not AUDD_API_TOKEN:
        return None
    if _audd_quota_exhausted:
        if time.time() < _audd_quota_reset_time:
            log.info("  AudD-Quota erschöpft, überspringe")
            return None
        _audd_quota_exhausted = False
    try:
        with open(path, "rb") as f:
            r = requests.post(
                "https://api.audd.io/",
                data={"api_token": AUDD_API_TOKEN, "return": "spotify"},
                files={"file": f},
                timeout=30,
            )
        if r.status_code != 200:
            return None
        data = r.json()
        err = data.get("error") or {}
        if err.get("error_code") == 901 or err.get("error_code") == '901':
            _audd_quota_exhausted = True
            _audd_quota_reset_time = time.time() + 3600
            log.warning("  AudD-Quota erschöpft, 1h Cooldown")
            return None
        result = data.get("result")
        if not result:
            return None
        return {
            "artist":     result.get("artist"),
            "title":      result.get("title"),
            "album":      result.get("album"),
            "spotify_id": (result.get("spotify") or {}).get("id"),
        }
    except Exception as e:
        log.warning(f"  AudD-Fehler: {e}")
    return None


def _lookup_discogs_genres(artist: str, title: str) -> list[str]:
    """Lookup genres via Discogs API. Requires DISCOGS_TOKEN env var."""
    if not _HAS_DISCOGS:
        return []
    token = os.getenv("DISCOGS_TOKEN", "")
    if not token:
        return []
    try:
        d = _discogs_mod.Client("downtify/1.0", user_token=token)
        results = d.search(f"{artist} {title}", type="release")
        for r in results.page(1)[:3]:
            genres = getattr(r, "genres", None) or []
            if genres:
                log.info(f"  Discogs Genres: {genres}")
                return list(genres)
    except Exception as e:
        log.debug(f"  Discogs-Fehler: {e}")
    return []


def search_discogs_track(artist: str, title: str) -> dict:
    """Discogs release search → full metadata {genre, artist, album, title}."""
    if not _HAS_DISCOGS:
        return {}
    token = os.getenv("DISCOGS_TOKEN", "")
    if not token:
        return {}
    try:
        d = _discogs_mod.Client("downtify/1.0", user_token=token)
        results = d.search(f"{artist} {title}", type="release")
        for rel in results.page(1)[:3]:
            genres = getattr(rel, "genres", None) or []
            artists = getattr(rel, "artists", None) or []
            artist_name = artists[0].name if artists else ""
            album_name = getattr(rel, "title", "") or ""
            tracklist = getattr(rel, "tracklist", None) or []
            track_title = ""
            for t in tracklist:
                if title.lower() in t.title.lower():
                    track_title = t.title
                    break
            return {
                "genre": genres[0] if genres else "",
                "artist": artist_name,
                "album": album_name,
                "title": track_title or title,
            }
    except Exception as e:
        log.debug(f"  Discogs search_track Fehler: {e}")
    return {}


def _acoustid_lookup_genres(path: Path) -> list[str]:
    """Fingerprint lookup via AcoustID → MusicBrainz recording → genres."""
    if not _HAS_ACOUSTID:
        return []
    api_key = os.getenv("ACOUSTID_API_KEY", "")
    if not api_key:
        return []
    try:
        results = list(_acoustid_mod.match(api_key, str(path)))
        for score, recording_id, _title, _artist in results:
            if score > 0.8 and recording_id:
                mb_url = f"https://musicbrainz.org/ws/2/recording/{recording_id}?inc=genres&fmt=json"
                resp = requests.get(mb_url, headers=MB_HEADERS, timeout=10)
                if resp.status_code == 200:
                    genres = [g.get("name", "") for g in resp.json().get("genres", [])]
                    if genres:
                        log.info(f"  AcoustID Genres: {genres}")
                        return genres
    except Exception as e:
        log.debug(f"  AcoustID-Fehler: {e}")
    return []


def _shazam_identify_sync(path: Path) -> Optional[dict]:
    """Shazam song recognition (sync wrapper around async shazamio)."""
    if not _HAS_SHAZAM:
        return None
    try:
        async def _run():
            shazam = _Shazam()
            return await shazam.recognize(str(path))

        out = asyncio.run(_run())
        track = out.get("track", {})
        if not track:
            return None
        album = None
        for section in track.get("sections", []):
            for meta in section.get("metadata", []):
                if isinstance(meta, dict) and meta.get("title", "").lower() == "album":
                    album = meta.get("text")
                    break
            if album:
                break
        return {
            "title": track.get("title"),
            "artist": track.get("subtitle"),
            "genre": track.get("genres", {}).get("primary"),
            "album": album,
        }
    except Exception as e:
        log.debug(f"  Shazam-Fehler: {e}")
        return None


# ── Genre-Ermittlung mit voller Kette ────────────────────────────────────────

class GenreResolver:
    def __init__(self, db: OrganizerDB, spotify: SpotifyClient):
        self.db = db
        self.spotify = spotify
        self._genre_rules: list[tuple[str, str]] = DEFAULT_GENRE_RULES
        self._country_map: dict[str, str] = DEFAULT_COUNTRY_TO_FOLDER
        self._artist_rules: list[dict] = []
        self._artist_genre_rules: list[tuple[str, str]] = []  # (pattern, genre)

    def reload_from_settings(self, settings: dict) -> None:
        """Hot-reload rules from settings dict (called after save via API)."""
        raw_genre = settings.get('genre_rules')
        if raw_genre and isinstance(raw_genre, list):
            self._genre_rules = [
                (r['keyword'], r['folder'])
                for r in raw_genre
                if isinstance(r, dict) and r.get('keyword') and r.get('folder')
            ]
        else:
            self._genre_rules = DEFAULT_GENRE_RULES

        raw_country = settings.get('country_to_folder')
        if raw_country and isinstance(raw_country, dict):
            self._country_map = raw_country
        else:
            self._country_map = DEFAULT_COUNTRY_TO_FOLDER

        raw_artist = settings.get('artist_rules')
        if raw_artist and isinstance(raw_artist, list):
            self._artist_rules = [
                r for r in raw_artist
                if isinstance(r, dict) and r.get('pattern') and r.get('artist')
            ]
        else:
            self._artist_rules = []

        raw_ag = settings.get('artist_genre_rules')
        if raw_ag and isinstance(raw_ag, list):
            self._artist_genre_rules = [
                (r['pattern'].lower(), r['genre'])
                for r in raw_ag
                if isinstance(r, dict) and r.get('pattern') and r.get('genre')
            ]
        else:
            self._artist_genre_rules = []

    def _apply_artist_genre_rules(self, artist: str) -> Optional[str]:
        """Return genre if artist matches any artist→genre rule, else None."""
        al = artist.lower()
        for pattern, genre in self._artist_genre_rules:
            if pattern in al:
                log.info(f"  Artist→Genre Rule: '{artist}' → '{genre}'")
                return genre
        return None

    def apply_artist_alias(self, raw_artist: str) -> str:
        """Apply artist alias rules: if pattern matches → return mapped artist."""
        lower = raw_artist.lower()
        for rule in self._artist_rules:
            if rule['pattern'].lower() in lower:
                log.info(f"  Artist-Alias: '{raw_artist}' → '{rule['artist']}'")
                return rule['artist']
        return raw_artist

    def get_artist_rules(self) -> list[dict]:
        return self._artist_rules

    def resolve(self, artist: str, title: str) -> str:
        if not artist:
            return DEFAULT_FOLDER

        # Artist→Genre rules: highest priority, no API calls needed
        ag = self._apply_artist_genre_rules(artist)
        if ag:
            return ag

        # Cache prüfen
        cached = self.db.get_cached_genres(artist)
        if cached is not None:
            log.info(f"  Genres (cached): {cached or '—'}")
            spotify_genres = cached
        else:
            # Spotify
            spotify_genres = self.spotify.lookup_genres(artist, title)
            log.info(f"  Spotify Genres: {spotify_genres or '—'}")
            if not spotify_genres:
                # Deezer
                deezer_genres = lookup_deezer(artist, title)
                if deezer_genres:
                    log.info(f"  Deezer Genres: {deezer_genres}")
                    spotify_genres = deezer_genres
            if not spotify_genres:
                # Last.fm
                lastfm_genres = lookup_lastfm(artist)
                if lastfm_genres:
                    log.info(f"  Last.fm Tags: {lastfm_genres[:5]}")
                    spotify_genres = lastfm_genres
            if not spotify_genres:
                # Discogs (text-based, no fingerprint needed)
                discogs_genres = _lookup_discogs_genres(artist, title)
                if discogs_genres:
                    spotify_genres = discogs_genres
            self.db.cache_genres(artist, spotify_genres)

        # Ethnische Genres haben absolute Priorität
        f = _match_genre_rules(spotify_genres, self._genre_rules)
        if f in ETHNIC_FOLDERS:
            return f

        # MusicBrainz Country (mit Cache)
        country = self.db.get_cached_country(artist)
        if country is None:
            country, mb_tags = lookup_musicbrainz_artist(artist)
            self.db.cache_country(artist, country or "")
        else:
            mb_tags = []
        if country and country in self._country_map:
            log.info(f"  Artist Country: {country}")
            return self._country_map[country]

        # Stil-basierte Spotify-Rules
        if f:
            return f

        # MusicBrainz Tags
        if mb_tags:
            log.info(f"  MusicBrainz Tags: {mb_tags[:5]}")
            f = _match_genre_rules(mb_tags, self._genre_rules)
            if f:
                return f

        # Zeichensatz-Detection
        script = _detect_script(title)
        if script:
            log.info(f"  Script-Detection: {script}")
            return script

        return DEFAULT_FOLDER

    def apply_rules_only(
        self,
        artist: str,
        title: str,
        raw_genres: list,
        country: Optional[str] = None,
        mb_tags: Optional[list] = None,
    ) -> str:
        """Apply organizer rules to pre-gathered data, without any API calls."""
        ag = self._apply_artist_genre_rules(artist)
        if ag:
            return ag
        f = _match_genre_rules(raw_genres, self._genre_rules)
        if f in ETHNIC_FOLDERS:
            return f
        if country and country in self._country_map:
            return self._country_map[country]
        if f:
            return f
        if mb_tags:
            f2 = _match_genre_rules(mb_tags, self._genre_rules)
            if f2:
                return f2
        script = _detect_script(title)
        if script:
            return script
        return DEFAULT_FOLDER


# ── Voting helpers ────────────────────────────────────────────────────────────

def _norm_voter(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or "").lower())


def _split_voter_entry(value: str, separators: list) -> list:
    """Smart-split at separator tokens."""
    parts = [value.strip()]
    for sep in sorted(separators, key=len, reverse=True):
        new_parts = []
        for p in parts:
            new_parts.extend(s.strip() for s in p.split(sep) if s.strip())
        parts = new_parts
    return parts


def _vote_text_field(values: list, separators: list) -> tuple:
    """Vote for Artist/Album/Title. Returns (winner, quality)."""
    all_entries: list = []
    for v in values:
        if v:
            all_entries.extend(_split_voter_entry(v, separators))
    if not all_entries:
        return "", "niedrig"
    counter = Counter(all_entries)
    total = max(len(values), 1)
    winner, n = counter.most_common(1)[0]
    ratio = n / total
    if ratio >= 5 / 6:
        quality = "sehr hoch"
    elif ratio >= 4 / 6:
        quality = "hoch"
    elif ratio >= 2 / 6:
        quality = "mittel"
    else:
        quality = "niedrig"
    return winner, quality


def _vote_genre_field(values: list) -> tuple:
    """Vote for Genre: words appearing >3x. Returns (winner, has_clear)."""
    words: list = []
    for v in values:
        if v:
            words.extend(re.sub(r'[^a-z0-9 ]', ' ', v.lower()).split())
    if not words:
        return "", False
    counter = Counter(words)
    top = [w for w, n in counter.most_common() if n > 3]
    return " ".join(top), bool(top)


def _fuzzy_similar(a: str, b: str, threshold: float = 0.75) -> bool:
    na = re.sub(r'[^a-z0-9]', '', (a or "").lower())
    nb = re.sub(r'[^a-z0-9]', '', (b or "").lower())
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return shorter in longer and len(shorter) / len(longer) >= threshold


# ── MetadataVoter ─────────────────────────────────────────────────────────────

class MetadataVoter:
    """
    11-Schritt Voting-Pipeline für Metadaten-Auflösung.
    Queries alle Quellen parallel, wählt per Mehrheitsentscheid,
    nutzt MusicBrainz und Fingerprint als Fallback.
    """

    QUALITY_DONE = {"sehr hoch", "hoch"}
    FIELDS = ("genre", "artist", "album", "title")

    def __init__(
        self,
        db: OrganizerDB,
        spotify: SpotifyClient,
        resolver: GenreResolver,
        separators: Optional[list] = None,
    ):
        self.db = db
        self.spotify = spotify
        self.resolver = resolver
        self.separators = separators or DEFAULT_SEPARATORS
        self.audit_log: list = []

    def _log_step(self, step: object, name: str, **kwargs: object) -> None:
        entry: dict = {"step": step, "name": name}
        entry.update(kwargs)
        self.audit_log.append(entry)

    def resolve(
        self,
        path: Path,
        tags: dict,
        source: str,
        track_id: Optional[str] = None,
    ) -> dict:
        """Full 11-Schritt pipeline. Returns resolved metadata dict."""
        self.audit_log = []
        orig = {
            "orig_genre": tags.get("genre") or "",
            "orig_artist": tags.get("artist") or "",
            "orig_album": tags.get("album") or "",
            "orig_title": tags.get("title") or path.stem,
        }

        # Schritt 0: Fingerprint wenn Tags fehlen
        tags = self._step0_fingerprint(path, tags, source)
        self._log_step(0, "Tags + Fingerprint", values={
            "genre": tags.get("genre", ""), "artist": tags.get("artist", ""),
            "album": tags.get("album", ""), "title": tags.get("title", ""),
        })

        artist = tags.get("artist", "")
        title_raw = tags.get("title", "") or path.stem
        if not artist or not title_raw:
            return self._fallback(tags, orig)

        # Schritt 0.5: Cache-Lookup
        ak = _norm_voter(artist)
        tk = _norm_voter(title_raw)
        cached = self.db.get_track_cache(ak, tk)
        if cached:
            genre_raw = cached.get("genre_raw", "")
            country = cached.get("country")
            mb_tags_list: list = cached.get("mb_tags", [])
            final_genre = self.resolver.apply_rules_only(
                artist, title_raw, [genre_raw] if genre_raw else [], country, mb_tags_list
            )
            result = {**cached, "genre": final_genre, "cache_hit": True, "meta_source": "Cache (Schritt 0.5)"}
            result.update(orig)
            if final_genre != cached.get("genre"):
                self.db.set_track_cache(ak, tk, {**cached, "genre": final_genre})
            self._log_step("0.5", "Cache-Hit", action="Schritte 1-10 übersprungen", values={
                "genre": final_genre,
                "artist": cached.get("artist", ""),
                "album": cached.get("album", ""),
                "title": cached.get("title", ""),
            })
            self._save_audit(track_id, {"steps": self.audit_log, "cache": {"action": "hit"}})
            return result

        # Schritt 1: Alle Quellen parallel befragen
        # Spotify-Downloads: artist/album/title bereits bekannt → nur Genre voten
        spotify_sourced = bool(
            tags.get("spotify_id")
            and not str(tags["spotify_id"]).startswith(("scanner:", "pfad:"))
        )
        sources = self._step1_query_sources(artist, title_raw, tags, spotify_sourced=spotify_sourced)
        self._log_step(1, "6 Quellen befragt", sources=sources, spotify_sourced=spotify_sourced)

        # Schritt 2-4: Voting
        ergebnis1, status1, counts = self._step2_4_vote(sources)
        self._log_step(2, "Voting", counts=counts, ergebnis1=ergebnis1, status1=status1)

        # Schritt 5: Abgeschlossene Felder
        result_fields = {k: v for k, v in ergebnis1.items() if status1.get(k) == "abgeschlossen"}
        open1 = [k for k in self.FIELDS if status1.get(k) != "abgeschlossen"]
        self._log_step(5, "Status 1", written=list(result_fields.keys()), open=open1)

        country = None
        mb_tags_list = []

        # Schritt 6-7: MusicBrainz für offene Felder
        if open1:
            mb_result = search_musicbrainz_recording(artist, title_raw)
            country_cached = self.db.get_cached_country(artist)
            if country_cached is None:
                mb_artist_country, mb_tags_list = lookup_musicbrainz_artist(artist)
                country = mb_artist_country
                self.db.cache_country(artist, country or "")
            else:
                country = country_cached if country_cached else None

            self._log_step(6, "MusicBrainz Recording", result=mb_result, country=country)

            ergebnis2, status2 = self._step7_compare_mb(ergebnis1, mb_result, open1)
            result_fields.update({k: v for k, v in ergebnis2.items() if status2.get(k) == "abgeschlossen"})
            open2 = [k for k in open1 if status2.get(k) != "abgeschlossen"]
            self._log_step(7, "Status 2 MB Vergleich", written=[k for k in open1 if k not in open2], open=open2)

            # Schritt 8-9: Fingerprint für noch offene Felder
            if open2:
                fp_result = self._step8_fingerprint(path, open2)
                self._log_step(8, "Fingerprint für offene Felder", result=fp_result)
                ergebnis4 = self._step9_final(ergebnis1, ergebnis2, fp_result, open2)
                result_fields.update(ergebnis4)
                self._log_step(9, "Ergebnis 4", ergebnis4=ergebnis4)
        else:
            ergebnis2 = {}

        for field, default in [("genre", ""), ("artist", "Unbekannt"), ("album", "Unbekannt"), ("title", "Unbekannt")]:
            if not result_fields.get(field):
                result_fields[field] = default

        # Schritt 10: org_* + Quellenangabe
        genre_raw = result_fields.get("genre", "")
        meta_source = self._determine_source(status1)
        self._log_step(10, "org_* Felder", org=result_fields, source=meta_source)

        # Schritt 11: Organizer-Rules
        final_genre = self.resolver.apply_rules_only(
            result_fields.get("artist", ""),
            result_fields.get("title", ""),
            [genre_raw] if genre_raw else [],
            country,
            mb_tags_list,
        )
        rule_changes = []
        if final_genre != genre_raw:
            rule_changes.append({"field": "genre", "before": genre_raw, "after": final_genre})
        result_fields["genre"] = final_genre
        self._log_step(11, "Organizer-Rules", rules_applied=rule_changes)

        # Schritt 12: Cache schreiben
        cache_entry: dict = {
            **result_fields,
            "genre_raw": genre_raw,
            "country": country,
            "mb_tags": mb_tags_list[:5],
        }
        self.db.set_track_cache(ak, tk, cache_entry)
        if genre_raw:
            self.db.cache_genres(artist, [genre_raw])
        self._log_step(None, "Cache", action="written", key=f"{ak}::{tk}")

        output: dict = {**result_fields, "meta_source": meta_source, "cache_hit": False}
        output.update(orig)
        self._save_audit(track_id, {
            "steps": self.audit_log,
            "cache": {"action": "written", "key": f"{ak}::{tk}", "ttl_days": 30},
        })
        return output

    def _step0_fingerprint(self, path: Path, tags: dict, source: str) -> dict:
        if tags.get("title") and tags.get("artist"):
            return tags
        if source not in ("scanner", "download"):
            return tags
        log.info("  Tags unvollständig → Fingerprint (Schritt 0)...")
        shazam = _shazam_identify_sync(path)
        if shazam:
            for k in ("title", "artist", "album", "genre"):
                if shazam.get(k) and not tags.get(k):
                    tags[k] = shazam[k]
        if not (tags.get("title") and tags.get("artist")):
            acoustid_genres = _acoustid_lookup_genres(path)
            if acoustid_genres and not tags.get("genre"):
                tags["genre"] = acoustid_genres[0]
        if not (tags.get("title") and tags.get("artist")):
            audd = audd_identify(path)
            if audd:
                for k in ("title", "artist", "album"):
                    if audd.get(k) and not tags.get(k):
                        tags[k] = audd[k]
        return tags

    def _step1_query_sources(
        self, artist: str, title: str, tags: dict, *, spotify_sourced: bool = False
    ) -> dict:
        file_meta = {
            "genre": tags.get("genre", ""),
            "artist": tags.get("artist", ""),
            "album": tags.get("album", ""),
            "title": tags.get("title", ""),
        }

        def q_spotify() -> dict:
            return self.spotify.search_track(artist, title)

        def q_deezer() -> dict:
            return search_deezer_track(artist, title)

        def q_lastfm() -> dict:
            return search_lastfm_track(artist, title)

        def q_discogs() -> dict:
            return search_discogs_track(artist, title)

        def q_soundcloud() -> dict:
            try:
                from .soundcloud import search_soundcloud_track
                return search_soundcloud_track(artist, title)
            except Exception:
                return {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            f_sp = ex.submit(q_spotify)
            f_dz = ex.submit(q_deezer)
            f_lf = ex.submit(q_lastfm)
            f_dc = ex.submit(q_discogs)
            f_sc = ex.submit(q_soundcloud)
            sp = _safe_result(f_sp) or {}
            dz = _safe_result(f_dz) or {}
            lf = _safe_result(f_lf) or {}
            dc = _safe_result(f_dc) or {}
            sc = _safe_result(f_sc) or {}

        log.info(
            f"  Spotify: {sp.get('genre') or '—'} | Deezer: {dz.get('genre') or '—'} | "
            f"Last.fm: {lf.get('genre') or '—'} | Discogs: {dc.get('genre') or '—'} | "
            f"SC: {sc.get('genre') or '—'}"
        )

        if spotify_sourced:
            # Spotify-Download: artist/album/title sind bereits bekannt.
            # Nur Genre wird per Voting aufgelöst → die eigenen Tag-Werte in alle
            # Quellen einsetzen, damit das Voting 6/6 "sehr hoch" ergibt.
            log.info("  Spotify-sourced → artist/album/title aus Tags, nur Genre wird gevoted")
            for src in (sp, dz, lf, dc, sc):
                for f in ("artist", "album", "title"):
                    src[f] = file_meta[f]

        return {"file": file_meta, "spotify": sp, "deezer": dz, "lastfm": lf, "discogs": dc, "soundcloud": sc}

    def _step2_4_vote(self, sources: dict) -> tuple:
        source_list = list(sources.values())
        counts: dict = {}
        ergebnis1: dict = {}
        status1: dict = {}

        for field in ("artist", "album", "title"):
            vals = [s.get(field, "") for s in source_list]
            winner, quality = _vote_text_field(vals, self.separators)
            ergebnis1[field] = winner
            status1[field] = "abgeschlossen" if quality in self.QUALITY_DONE else "offen"
            counts[field] = {"quality": quality, "winner": winner}

        genre_vals = [s.get("genre", "") for s in source_list]
        winner_g, has_clear = _vote_genre_field(genre_vals)
        ergebnis1["genre"] = winner_g
        status1["genre"] = "abgeschlossen" if has_clear else "offen"
        counts["genre"] = {"has_clear": has_clear, "winner": winner_g}

        return ergebnis1, status1, counts

    def _step7_compare_mb(self, ergebnis1: dict, mb: dict, open_fields: list) -> tuple:
        ergebnis2: dict = {}
        status2: dict = {}
        for field in open_fields:
            e1_val = ergebnis1.get(field, "")
            mb_val = mb.get(field, "")
            if mb_val and e1_val and _fuzzy_similar(e1_val, mb_val):
                ergebnis2[field] = e1_val
                status2[field] = "abgeschlossen"
            elif mb_val:
                ergebnis2[field] = mb_val
                status2[field] = "abgeschlossen"
            else:
                ergebnis2[field] = e1_val
                status2[field] = "offen"
        return ergebnis2, status2

    def _step8_fingerprint(self, path: Path, open_fields: list) -> dict:
        result: dict = {}
        shazam = _shazam_identify_sync(path)
        if shazam:
            field_map = {"title": "title", "artist": "artist", "album": "album", "genre": "genre"}
            for field in open_fields:
                val = shazam.get(field_map.get(field, field))
                if val:
                    result[field] = val
        if "genre" in open_fields and "genre" not in result:
            genres = _acoustid_lookup_genres(path)
            if genres:
                result["genre"] = genres[0]
        return result

    def _step9_final(self, e1: dict, e2: dict, e3: dict, open_fields: list) -> dict:
        out: dict = {}
        for field in open_fields:
            out[field] = e3.get(field) or e2.get(field) or e1.get(field) or ""
        return out

    def _determine_source(self, status1: dict) -> str:
        done = [f for f in self.FIELDS if status1.get(f) == "abgeschlossen"]
        if len(done) == 4:
            return "Schritt 5 / Ergebnis 1 (Voting)"
        if len(done) >= 2:
            return "Schritt 7 / Ergebnis 2 (MusicBrainz)"
        return "Schritt 9 / Ergebnis 4"

    def _save_audit(self, track_id: Optional[str], audit: dict) -> None:
        if track_id:
            self.db.save_audit(track_id, json.dumps(audit))

    def _fallback(self, tags: dict, orig: dict) -> dict:
        return {
            "genre": DEFAULT_FOLDER,
            "artist": tags.get("artist") or "Unbekannt",
            "album": tags.get("album") or "Unbekannt",
            "title": tags.get("title") or orig.get("orig_title") or "Unbekannt",
            "meta_source": "Kein Artist/Title erkannt",
            "cache_hit": False,
            **orig,
        }


def _safe_result(future: concurrent.futures.Future, timeout: float = 15.0) -> object:
    try:
        return future.result(timeout=timeout)
    except Exception as e:
        log.debug(f"  Quelle Fehler: {e}")
        return {}


# ── Path Building & bestof-Migration ─────────────────────────────────────────

def _bestof_folder(artist: str) -> str:
    return f"Best of {artist}"


def _count_album_in_musik(artist: str, album: str) -> tuple[int, list]:
    """Zählt wieviele Songs vom (Artist, Album) bereits in /musik liegen."""
    matches = []
    if not MUSIK_DIR.exists():
        return 0, []
    for genre_dir in MUSIK_DIR.iterdir():
        if not genre_dir.is_dir():
            continue
        artist_dir = genre_dir / artist
        if not artist_dir.is_dir():
            continue
        for sub in artist_dir.iterdir():
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                if not f.is_file() or f.suffix.lower() not in AUDIO_EXT:
                    continue
                tags = _read_tags(f)
                if _sanitize(tags.get("album") or "", "Unbekannt") == album:
                    matches.append(f)
    return len(matches), matches


def _migrate_to_album(genre: str, artist: str, album: str, existing_files: list) -> None:
    """Verschiebt alle bisher in 'Best of' liegenden Songs ins Album-Verzeichnis."""
    album_dir = MUSIK_DIR / genre / artist / album
    album_dir.mkdir(parents=True, exist_ok=True)
    bestof_dir = MUSIK_DIR / genre / artist / _bestof_folder(artist)

    for src in existing_files:
        if src.parent == album_dir:
            continue
        dst = album_dir / src.name
        ctr = 1
        while dst.exists():
            dst = album_dir / f"{src.stem}_{ctr}{src.suffix}"
            ctr += 1
        try:
            shutil.move(str(src), str(dst))
            log.info(f"  Best of → Album: {src.name}")
        except Exception as e:
            log.warning(f"  Migration fehlgeschlagen {src.name}: {e}")

    # Leeren Best-of-Ordner aufräumen
    try:
        if bestof_dir.exists() and not any(bestof_dir.iterdir()):
            bestof_dir.rmdir()
    except Exception:
        pass


def determine_target_path(genre: str, artist: str, album: str, title: str, ext: str) -> Path:
    """Berechnet Zielpfad inkl. Best-of-Logik + ggf. Migration."""
    existing_count, existing_files = _count_album_in_musik(artist, album)

    # +1 weil der aktuelle Song noch nicht im Filesystem ist
    if existing_count + 1 >= BESTOF_MIN:
        # Album-Ordner: ggf. vorhandene Best-of-Einträge migrieren
        _migrate_to_album(genre, artist, album, existing_files)
        folder = MUSIK_DIR / genre / artist / album
    else:
        folder = MUSIK_DIR / genre / artist / _bestof_folder(artist)

    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (title + ext)
    ctr = 1
    while target.exists():
        target = folder / f"{title}_{ctr}{ext}"
        ctr += 1
    return target


# ── Downtify Monitor DB: filename nullifizieren ───────────────────────────────

def _nullify_monitor_filename(original_path: Path) -> None:
    """
    Setzt filename=NULL in Downtifys downloaded_tracks Tabelle.

    Warum: monitor.py re-downloaded einen Song wenn:
        stored is not None AND not (download_dir / stored).exists()

    Wenn filename=NULL ist, greift stored is not None NICHT → kein Re-Download.
    Der Song bleibt als "erledigt" in der DB – wird nie mehr neu heruntergeladen.
    """
    monitor_db = DATA_DIR / "downtify_monitor.db"
    if not monitor_db.exists():
        return
    try:
        # Relativer Pfad wie er in downloaded_tracks.filename gespeichert ist
        rel = original_path.relative_to(DOWNLOAD_DIR).as_posix()
        conn = sqlite3.connect(str(monitor_db), timeout=10)
        cur = conn.execute(
            "UPDATE downloaded_tracks SET filename = NULL WHERE filename = ?",
            (rel,),
        )
        conn.commit()
        conn.close()
        if cur.rowcount > 0:
            log.info(f"  ✓ Monitor DB: filename nullified ({rel})")
        else:
            log.debug(f"  Monitor DB: kein Eintrag für {rel} gefunden")
    except Exception as e:
        log.warning(f"  Monitor DB Update fehlgeschlagen: {e}")


# ── Datei-Verarbeitung ───────────────────────────────────────────────────────

def _file_id(path: Path, tags: dict) -> str:
    """Eindeutige ID für die Datei (Spotify-ID wenn vorhanden, sonst path+stat)."""
    if tags.get("spotify_id"):
        return f"spotify:{tags['spotify_id']}"
    try:
        st = path.stat()
        return f"file:{path.name}:{st.st_size}"
    except Exception:
        return f"file:{path.name}"


def _parse_pfad_filename(path: Path) -> Optional[dict]:
    """Parse pfad_genre_artist_album_title.ext → tag dict, or None if no pfad_ prefix."""
    stem = path.stem
    if not stem.lower().startswith('pfad_'):
        return None
    parts = stem[5:].split('_', 3)
    while len(parts) < 4:
        parts.append('-')
    genre, artist, album, title = parts
    return {
        'genre':  genre if genre != '-' else '',
        'artist': artist if artist != '-' else '',
        'album':  album if album != '-' else '',
        'title':  title if title != '-' else path.stem,
        'spotify_id': f'pfad:{path.stem}',
        'pfad_parsed': True,
    }


def process_file(  # noqa: PLR0914
    path: Path,
    source: str,
    db: OrganizerDB,
    resolver: GenreResolver,
    *,
    delete_after_move: bool = False,
    voter: Optional[MetadataVoter] = None,
) -> bool:
    """
    Verarbeitet eine einzelne Audio-Datei.
    Returns True bei Erfolg, False bei Skip/Error.
    """
    log.info(f"[{source}] Verarbeite: {path.name}")

    tags = _read_tags(path)

    # pfad_* filename convention → skip voting pipeline
    pfad = _parse_pfad_filename(path)
    if pfad:
        log.info("  pfad_-Dateiname erkannt, überspringe Voting-Pipeline")
        tags = {**tags, **pfad}
        orig_genre = tags.get("genre") or ""
        orig_artist = tags.get("artist") or ""
        orig_album = tags.get("album") or ""
        orig_title = tags.get("title") or path.stem
        if source == "scanner":
            scanner_spotify_id = tags.get("spotify_id") or f"scanner:{path.stem}"
            _insert_scanner_track(path, scanner_spotify_id, orig_title or path.stem, orig_genre)
        raw_artist = resolver.apply_artist_alias(tags.get("artist") or "Sonstiges")
        artist_p = _primary_artist(raw_artist)
        title = _sanitize(tags.get("title") or path.stem)
        artist = _sanitize(artist_p, "Sonstiges")
        album = _sanitize(tags.get("album") or "Unbekannt", "Unbekannt")
        genre = _sanitize(pfad.get("genre") or DEFAULT_FOLDER, DEFAULT_FOLDER)
    else:
        # ── Voting Pipeline ───────────────────────────────────────────────────
        if voter is None:
            voter = MetadataVoter(db, SpotifyClient(), resolver)

        track_id = tags.get("spotify_id") or f"scanner:{path.stem}"
        resolved = voter.resolve(path, tags, source, track_id=track_id)

        orig_genre = resolved.get("orig_genre") or ""
        orig_artist = resolved.get("orig_artist") or ""
        orig_album = resolved.get("orig_album") or ""
        orig_title = resolved.get("orig_title") or path.stem

        # Scanner: register in monitor.db before the move
        if source == "scanner":
            scanner_spotify_id = tags.get("spotify_id") or f"scanner:{path.stem}"
            _insert_scanner_track(path, scanner_spotify_id, orig_title or path.stem, orig_genre)

        raw_artist = resolver.apply_artist_alias(resolved.get("artist") or "Sonstiges")
        artist_p = _primary_artist(raw_artist)
        title = _sanitize(resolved.get("title") or path.stem)
        artist = _sanitize(artist_p, "Sonstiges")
        album = _sanitize(resolved.get("album") or "Unbekannt", "Unbekannt")
        genre = _sanitize(resolved.get("genre") or DEFAULT_FOLDER, DEFAULT_FOLDER)
        log.info(f"  meta_source: {resolved.get('meta_source', '—')} | cache_hit: {resolved.get('cache_hit', False)}")

    log.info(f"  → {genre} / {artist} / {album} / {title}")

    target = determine_target_path(genre, artist, album, title, path.suffix)

    try:
        shutil.move(str(path), str(target))
        log.info(f"  ✓ {target.relative_to(MUSIK_DIR)}")
    except Exception as e:
        log.error(f"  ✗ Move fehlgeschlagen: {e}")
        return False

    _write_organizer_comment(target, genre, artist, album, title)
    _update_monitor_metadata(
        path, genre, artist, album, title,
        orig_genre=orig_genre, orig_artist=orig_artist, orig_album=orig_album, orig_title=orig_title,
    )
    return True


# ── Watcher-Threads ──────────────────────────────────────────────────────────

def _cleanup_empty_scanner_subdirs(base: Path) -> None:
    """Delete subdirs of base that contain no audio files (including non-audio leftovers)."""
    for subdir in sorted(base.rglob('*'), reverse=True):
        if not subdir.is_dir() or subdir == base:
            continue
        has_audio = any(
            f.suffix.lower() in AUDIO_EXT
            for f in subdir.rglob('*')
            if f.is_file()
        )
        if not has_audio:
            try:
                shutil.rmtree(str(subdir))
                log.info(f"  Subfolder gelöscht (keine Audio): {subdir.relative_to(base)}")
            except Exception as e:
                log.warning(f"  Subfolder-Cleanup fehlgeschlagen: {e}")


def _scan_dir(
    directory: Path,
    db: OrganizerDB,
    resolver: GenreResolver,
    source: str,
    delete_after_move: bool,
    voter: Optional[MetadataVoter] = None,
) -> int:
    if not directory.exists():
        return 0
    files = [
        p for p in directory.rglob("*")
        if p.is_file()
        and p.suffix.lower() in AUDIO_EXT
        and _is_stable(p, FILE_COOLDOWN)
        and "@eaDir" not in p.parts
    ]
    if not files:
        return 0

    log.info(f"[{source}] Gefunden: {len(files)} Datei(en)")
    success = 0
    for f in files:
        try:
            if process_file(f, source, db, resolver, delete_after_move=delete_after_move, voter=voter):
                success += 1
        except Exception as e:
            log.error(f"Fehler bei {f.name}: {e}")

    _cleanup_empty_scanner_subdirs(directory)
    return success


def _download_watcher_loop(
    db: OrganizerDB, resolver: GenreResolver, stop: threading.Event,
    voter: Optional[MetadataVoter] = None,
) -> None:
    log.info(f"Download-Watcher: {DOWNLOAD_DIR} → {MUSIK_DIR}")
    while not stop.is_set():
        try:
            _scan_dir(DOWNLOAD_DIR, db, resolver, "download", delete_after_move=False, voter=voter)
        except Exception as e:
            log.error(f"Download-Scan Fehler: {e}")
        stop.wait(POLL_INTERVAL)


def _scanner_loop(
    db: OrganizerDB, resolver: GenreResolver, stop: threading.Event,
    voter: Optional[MetadataVoter] = None,
) -> None:
    log.info(f"Scanner-Watcher: {SCANNER_DIR} → {MUSIK_DIR}")
    while not stop.is_set():
        try:
            _scan_dir(SCANNER_DIR, db, resolver, "scanner", delete_after_move=True, voter=voter)
        except Exception as e:
            log.error(f"Scanner Fehler: {e}")
        stop.wait(POLL_INTERVAL)


# ── Public API ───────────────────────────────────────────────────────────────

class OrganizerService:
    def __init__(self):
        MUSIK_DIR.mkdir(parents=True, exist_ok=True)
        SCANNER_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = OrganizerDB(DB_PATH)
        self.spotify = SpotifyClient()
        self.resolver = GenreResolver(self.db, self.spotify)
        self.voter = MetadataVoter(self.db, self.spotify, self.resolver)
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        log.info("=" * 60)
        log.info("Downtify Organizer Service startet")
        log.info(f"Download-Watcher: {'aktiv' if ENABLE_DOWNLOAD_WATCHER else 'deaktiviert'}")
        log.info(f"Scanner:          {'aktiv' if ENABLE_SCANNER else 'deaktiviert'}")
        log.info(f"Spotify:          {'verbunden' if SPOTIFY_CLIENT_ID else 'fehlt (CLIENT_ID nicht gesetzt)'}")
        log.info(f"Last.fm:          {'verbunden' if LASTFM_API_KEY else 'fehlt'}")
        log.info(f"AudD:             {'verbunden' if AUDD_API_TOKEN else 'fehlt'}")
        log.info(f"Polling:          {POLL_INTERVAL}s | Cooldown: {FILE_COOLDOWN}s")
        log.info(f"Soundcloud:       {'verbunden' if SOUNDCLOUD_CLIENT_ID else 'fehlt'}")
        log.info("=" * 60)

        if ENABLE_DOWNLOAD_WATCHER:
            t = threading.Thread(
                target=_download_watcher_loop,
                args=(self.db, self.resolver, self.stop, self.voter),
                name="organizer-downloads",
                daemon=True,
            )
            t.start()
            self.threads.append(t)

        if ENABLE_SCANNER:
            t = threading.Thread(
                target=_scanner_loop,
                args=(self.db, self.resolver, self.stop, self.voter),
                name="organizer-scanner",
                daemon=True,
            )
            t.start()
            self.threads.append(t)

    def shutdown(self) -> None:
        log.info("Organizer Shutdown...")
        self.stop.set()
        self.db.shutdown()


_singleton: Optional[OrganizerService] = None


def start_organizer() -> OrganizerService:
    """Wird aus main.py beim Startup aufgerufen."""
    global _singleton
    if _singleton is not None:
        return _singleton
    _singleton = OrganizerService()
    _singleton.start()
    return _singleton


def get_organizer() -> Optional[OrganizerService]:
    """Return running singleton (None if not started yet)."""
    return _singleton


def stop_organizer() -> None:
    """Wird aus main.py beim Shutdown aufgerufen."""
    global _singleton
    if _singleton is not None:
        _singleton.shutdown()
        _singleton = None
