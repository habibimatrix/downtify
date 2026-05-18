# Downtiplx

Self-hosted music downloader and organizer. Download Spotify tracks, albums, and playlists as high-quality audio files, then let the pipeline sort, tag, and file everything automatically.

---

## Features

- **Spotify & SoundCloud downloads** — tracks, albums, playlists via yt-dlp
- **11-step metadata voting pipeline** — 6 sources (Spotify, Deezer, Last.fm, MusicBrainz, SoundCloud, Discogs) vote on genre, artist, album, and title; best-of consensus wins
- **Artist Knowledge Cache** — after the first song, each artist's genre and albums are remembered; subsequent songs skip all API calls for genre
- **Organizer rules** — keyword→genre map, artist→genre overrides, country-based genre rules, artist alias normalization, custom separator tokens
- **Fingerprint recognition** — AcoustID + AudD cascade identifies untagged or wrongly tagged files
- **Audit trail** — per-track pipeline trace shows every step, every API result, every voting decision
- **Scanner directory** — drop any audio file into `/scanner` and it gets identified, tagged, and filed
- **Download watcher** — automatically processes files arriving in `/downloads`
- **Playlist Monitor** — watch Spotify playlists; new tracks download automatically on schedule
- **M3U export** — generates `.m3u` playlist files alongside downloaded tracks
- **Cache editor** — GUI to view, search, and clean artist knowledge cache entries
- **Web player** — in-browser playback of your library with queue support
- **Authentication** — optional password protection for the web UI
- **Dark / light theme** — Plex-gold color scheme

---

## Quick Start

```yaml
# docker-compose.yml
services:
  downtiplx:
    container_name: downtiplx
    image: 'downtiplx:latest'
    restart: unless-stopped
    build: .
    ports:
      - '8000:30321'
    volumes:
      - ./downloads:/downloads
      - ./musik:/musik
      - ./scanner:/scanner
      - ./data:/data
      - ./frontend/dist:/downtify/frontend/dist:ro
    environment:
      - DOWNTIFY_PORT=30321
      - CLIENT_ID=your_spotify_client_id
      - CLIENT_SECRET=your_spotify_client_secret
      - LASTFM_API_KEY=your_lastfm_key
      - DISCOGS_TOKEN=your_discogs_token
      - ACOUSTID_API_KEY=your_acoustid_key
      - AUDD_API_TOKEN=your_audd_token
      - SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id
```

```bash
docker compose up -d
```

Open `http://localhost:8000`.

---

## Metadata Voting Pipeline

Every downloaded or scanned file runs through an 11-step pipeline:

```
Step 0   Tags + Fingerprint     Read ID3/Vorbis tags; run AudD/AcoustID if tags missing
Step 0.5 Artist-Knowledge-Cache Check if artist genre is already known -> skip genre voting
Step 1   Query 6 sources        Spotify, Deezer, Last.fm, MusicBrainz, SoundCloud, Discogs
Step 2-4 Voting                 Plurality vote; quality: sehr hoch / hoch / mittel / niedrig
Step 4.5 Album fuzzy match      If artist known: fuzzy-compare voted album against cached albums
Step 5   Status 1               Fields with quality >= hoch are finalized
Step 6-7 MusicBrainz            Resolve remaining open fields
Step 8-9 Fingerprint            AcoustID -> AudD cascade for still-open fields
Step 10  Org fields             Determine meta_source, apply best-of logic
Step 11  Organizer rules        Genre keywords, artist->genre, country map, alias normalization
Step 12  Cache write            Update artist genre + albums in knowledge cache
```

**Shortcut**: Spotify-sourced track + artist genre in cache = steps 1-9 entirely skipped.

---

## Artist Knowledge Cache

The cache maps each artist to their genre and known albums:

```
raf camora -> genre: Deutschrap | albums: [Palmen aus Plastik, NXTLVL, Anthrazit]
```

- Genre is overwritten if a new song produces a different result (logged in audit trail)
- Albums are append-only; remove wrong entries from the Cache Editor in the Organizer view
- Genre from cache + Spotify-ID = zero external API calls

---

## Organizer Rules

Configured in the web UI under **Organizer**:

| Rule type | Example | Effect |
|---|---|---|
| Genre keyword | `hip hop` -> `Hip-Hop` | Normalizes genre spelling |
| Artist -> Genre | `RAF Camora` -> `Deutschrap` | Overrides voted genre for specific artists |
| Country map | `DE` + `rap` -> `Deutschrap` | Country-aware genre routing |
| Artist alias | `Raf Camora` = `RAF Camora` | Deduplicates artist spelling variants |
| Separator tokens | `feat.`, `ft.`, `x` | Splits featured artists from main artist field |

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOWNTIFY_PORT` | `30321` | HTTP port inside container |
| `CLIENT_ID` | — | Spotify app client ID (required) |
| `CLIENT_SECRET` | — | Spotify app client secret (required) |
| `LASTFM_API_KEY` | — | Last.fm API key |
| `DISCOGS_TOKEN` | — | Discogs personal access token |
| `ACOUSTID_API_KEY` | — | AcoustID fingerprinting key |
| `AUDD_API_TOKEN` | — | AudD recognition token |
| `SOUNDCLOUD_CLIENT_ID` | — | SoundCloud client ID (auto-discoverable in UI) |
| `DOWNLOAD_DIR` | `/downloads` | yt-dlp output directory |
| `MUSIK_DIR` | `/musik` | Organized music library |
| `SCANNER_DIR` | `/scanner` | Drop-folder for external files |
| `DATA_DIR` | `/data` | SQLite databases + settings |
| `ORGANIZER_POLL_INTERVAL` | `60` | Seconds between scanner sweeps |
| `ORGANIZER_FILE_COOLDOWN` | `30` | Seconds to wait after last file change |
| `ENABLE_DOWNLOAD_WATCHER` | `true` | Auto-process /downloads |
| `ENABLE_SCANNER` | `true` | Auto-process /scanner |
| `AUTH_PASSWORD` | — | Enable password protection when set |

---

## License

GPL-3.0
