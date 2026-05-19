<h1 align="center">
  <picture>
    <img width="80" src="frontend/src/assets/downtify.svg" alt="DowntiplX Logo">
  </picture>
  <br>
  DowntiplX
</h1>

<p align="center">
  <strong>Self-hosted music downloader + intelligent music organizer.<br>One paste, perfectly tagged — then automatically sorted, genre-matched and cached forever.</strong>
</p>

<div align="center">

[![Test](https://github.com/habibimatrix/downtify/actions/workflows/test.yml/badge.svg)](https://github.com/habibimatrix/downtify/actions/workflows/test.yml)
[![GitHub License](https://img.shields.io/github/license/habibimatrix/downtify?color=orange)](LICENSE)

</div>

---

## What is DowntiplX?

DowntiplX is a fork of [Downtify](https://github.com/henriquesebastiao/downtify) with one core philosophy added:

> *A well-organized NAS folder is not a luxury — it's a requirement.*

Paste a Spotify link. Get a perfectly tagged audio file. Then watch the **12-step Organizer pipeline** classify it, vote on the correct genre across 6 independent sources, apply your custom rules, and cache the result — so the next song by the same artist takes milliseconds instead of seconds.

Everything runs inside a single Docker container. No Spotify API key. No account. No cloud dependency.

---

## DowntiplX vs. Downtify

| Feature | Downtify (upstream) | DowntiplX |
|---|---|---|
| Download tracks / albums / playlists | ✅ | ✅ |
| Playlist Monitor (auto-download new songs) | ✅ | ✅ |
| Multi-format: MP3 · FLAC · M4A · OGG · OPUS | ✅ | ✅ |
| Real-time progress via WebSocket | ✅ | ✅ |
| Multi-language UI (EN / ES / PT-BR) | ✅ | ✅ |
| Organize by Artist (simple) | ✅ | Replaced by Organizer |
| **12-step Organizer pipeline** | ❌ | ✅ |
| **Artist-Knowledge-Cache** | ❌ | ✅ Learns permanently |
| **Audit trail per song** | ❌ | ✅ Every step traceable |
| **pfad_-prefix fast import** | ❌ | ✅ API-free batch import |
| **SoundCloud via HTML-paste** | ❌ | ✅ No outbound requests |
| **3-section download view** | ❌ | ✅ Active / Organizing / Done |
| **API health status bar** | ❌ | ✅ On welcome page |
| Logo | Green | Orange PLX |

---

## Quick Start

```bash
docker run -d -p 8000:8000 --name downtiplx \
  -v /path/to/music:/downloads \
  -v downtiplx_data:/data \
  ghcr.io/habibimatrix/downtify:latest
```

Open [http://localhost:8000](http://localhost:8000), paste a Spotify link, hit download.

### Docker Compose

```yaml
services:
  downtiplx:
    container_name: downtiplx
    image: ghcr.io/habibimatrix/downtify:latest
    ports:
      - '8000:8000'
    volumes:
      - ./downloads:/downloads    # your music library
      - ./data:/data              # SQLite DBs + settings
    restart: unless-stopped
```

**Volume breakdown:**
- `/downloads` — all audio files, organized by the Organizer pipeline
- `/data` — persistent state: `organizer.db`, `monitor.db`, `settings.json`

**Custom port** (Unraid, TrueNAS, Proxmox):

```yaml
ports:
  - '30321:8000'
```

---

## How It Works — Download Pipeline

```
Spotify embed page  →  YouTube Music search  →  yt-dlp + ffmpeg + mutagen
    (metadata)            (audio match)           (download & tag)
         ↓
  Organizer Pipeline (12 steps)
         ↓
  /downloads/<Genre>/<Artist> - <Title>.mp3
```

1. **Metadata** — Spotify links resolved by scraping `open.spotify.com/embed`. No credentials required.
2. **Audio match** — [`ytmusicapi`](https://ytmusicapi.readthedocs.io/) searches YouTube Music, picks the best match by duration comparison.
3. **Download & tag** — [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) downloads, `ffmpeg` converts, [`mutagen`](https://mutagen.readthedocs.io/) embeds all metadata.
4. **Organize** — The Organizer pipeline places the file in the correct genre/artist folder.

---

## How It Works — The Organizer Pipeline

The Organizer is the heart of DowntiplX. Every downloaded (or manually scanned) audio file passes through **12 deterministic steps**:

```
┌─────────────────────────────────────────────────────────────────────┐
│  [0]   Read tags          Extract metadata from MP3/FLAC tags       │
│  [0.5] Cache lookup       Artist known? → SKIP to step 11 ──────┐  │
│                                                                  │  │
│  [1]   Query 6 sources    File tags · Spotify · YouTube Music    │  │
│                           MusicBrainz · AcoustID · Filename      │  │
│  [2]   Genre voting       Weighted votes across all sources      │  │
│  [3]   Artist voting      Alias normalization + separator split  │  │
│  [4]   Album voting       Compilation detection                  │  │
│  [5]   Quality badge      Very High / High / Medium / Low        │  │
│  [6]   MusicBrainz deep   Extended recording lookup, country     │  │
│  [7]   Source comparison  Resolve conflicts                      │  │
│  [8]   AcoustID           Audio fingerprint as last resort       │  │
│  [9]   Merge              Best result from all sources           │  │
│  [10]  Source record      Document winning API                   │  │
│  [11]  Apply rules ←──────────────────────────────────────────┘  │
│         User-defined genre mapping table                          │
│  [12]  Cache update       Store result for this artist            │
│         ↓                                                         │
│  /downloads/<FinalGenre>/<Artist> - <Title>.mp3                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Cache-Hit Shortcut

When an artist is already in the cache, **steps 1–10 are skipped entirely**. The pipeline jumps directly from [0.5] → [11] → [12]. For a large re-scan, the second song by any known artist completes in milliseconds instead of making 6 API calls.

### Audit Trail

Every step is logged to `organizer.db`. Click the **Audit** button next to any song in `/list` to see the full trace: which API returned what, how the voting went, which rule changed the folder, what the cache looked like before and after.

---

## The Artist-Knowledge-Cache

The cache is a persistent SQLite table (`artist_knowledge_cache`) inside `organizer.db`. It stores per artist:

| Field | Description |
|---|---|
| `artist_norm` | Normalized key (`arctic monkeys`) |
| `genre` | Voted genre result |
| `genre_prev` | Previous genre — for auditing changes |
| `albums_json` | JSON array of known album titles — grows with every new song |
| `learned_at` | First cache entry timestamp |
| `genre_updated_at` | Last genre change timestamp |

**Why it matters:**

- **Speed** — milliseconds vs. multiple seconds per file for known artists
- **Privacy** — no outbound API calls for artists already in cache
- **Offline** — re-scan your full library without internet access
- **Transparency** — every entry is editable via `/organizer` → Artist Settings tab

Albums are learned incrementally. When you download a new album by a known artist, the album title is appended to `albums_json`. The cache never forgets unless you explicitly delete an entry.

---

## The pfad_-Shortcut

For importing existing, already-tagged libraries without any API lookups:

```
pfad_Electronic_Aphex Twin_Selected Ambient Works_Xtal.flac
     ↑Genre    ↑Artist     ↑Album                  ↑Title
```

Prefix a filename with `pfad_`. The Organizer detects it, skips the entire voting pipeline (steps 1–10), extracts genre/artist/album/title from the filename, applies your rules (step 11), and updates the cache (step 12). No internet required. Ideal for migrating thousands of pre-tagged files.

---

## SoundCloud Support

SoundCloud requires a `client_id` that rotates every few months. Auto-detection requires an outbound request from inside the container — which fails on most home server setups behind NAT.

**DowntiplX solution:** you extract it in your browser:

1. Open [soundcloud.com](https://soundcloud.com) in your browser
2. Press `Ctrl+U` to open page source
3. Select all → Copy
4. Go to **Settings → SoundCloud** → paste into the textarea → **Extract client_id**

The backend extracts the ID locally with a regex — no outbound request, fully air-gap compatible.

---

## Download View — 3 Sections

The `/list` page shows downloads in three live-updating sections:

| Section | Content |
|---|---|
| **Active Downloads** | Songs currently fetching from YouTube Music, with live progress bar |
| **Being Organized** | Files currently passing through the Organizer (step X/12 displayed) |
| **Done** | All finished songs — genre, artist, album, original metadata, and Audit button |

Deleting a song from the list clears it from the in-memory queue, making it immediately available for re-download.

---

## Organizer View — Two Tabs

Navigate to `/organizer`:

**Tab 1 — Genre Rules**
Keyword → folder mapping table. `techno` → `Techno`. Searchable, filterable. Changes take effect on the next download or re-scan.

**Tab 2 — Artist Settings**
- Artist → Genre overrides (highest priority, bypasses keyword voting entirely)
- Artist alias rules (`Daft Punk feat. Pharrell` → `Daft Punk`)
- Artist separator tokens (`feat.` / `&` / `vs.` splitting)
- Artist-Knowledge-Cache editor: paginated, searchable, individual album chips removable

---

## Playlist Monitor

Watch Spotify playlists and auto-download new songs as they appear — hands-free. Configure check intervals from 15 minutes to once a day. Only songs added *after* you start monitoring are fetched.

---

## Settings Defaults

| Setting | Default |
|---|---|
| Format | MP3 |
| Bitrate | 320 kbps |
| Download lyrics | Off |
| Generate M3U | Off |
| Max parallel downloads | 1 |

---

> [!WARNING]
> Users are responsible for their actions and any legal consequences. DowntiplX does not support unauthorized downloading of copyrighted material and takes no responsibility for user actions.

---

## License

Licensed under the [GPL-3.0](LICENSE) License.

Based on [Downtify](https://github.com/henriquesebastiao/downtify) by henriquesebastiao.
