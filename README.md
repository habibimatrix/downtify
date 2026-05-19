
<h1>
  <img width="185" height="50" alt="image" src="https://github.com/user-attachments/assets/4b11faec-f1e9-46bd-8902-bd6d0bd00ff0" />
</h1>

[![Fork of](https://img.shields.io/badge/fork%20of-henriquesebastiao%2Fdowntify-E5A00D?style=flat-square&logo=github&logoColor=1a0e00)](https://github.com/henriquesebastiao/downtify)
[![License](https://img.shields.io/badge/license-GPL--3.0-CC7B19?style=flat-square)](LICENSE)
[![Plex](https://img.shields.io/badge/Plex%20compatible-folder%20structure-E5A00D?style=flat-square&logo=plex&logoColor=1a0e00)](https://www.plex.tv)

</div>

---

> **Fork** of [henriquesebastiao/downtify](https://github.com/henriquesebastiao/downtify) — all credit for the original project and its web interface goes to [@henriquesebastiao](https://github.com/henriquesebastiao).
>
> This fork uses the Downtify UI as a **managed console**: it keeps the familiar download interface but adds a fully automated organisation layer on top — every downloaded or scanned track is fingerprinted, tagged via a multi-source voting pipeline, and filed into a clean `Genre/Artist/Album/` folder structure that Plex Media Server can pick up directly without any manual intervention.

---

## What Downtiplx adds to the original

| Feature | Description |
|---|---|
| **Automated folder structure** | Every track lands in `Genre/Artist/Album/` — Plex-compatible out of the box. No manual sorting needed. |
| **11-step metadata voting pipeline** | 6 sources (Spotify, Deezer, Last.fm, MusicBrainz, SoundCloud, Discogs) vote on genre, artist, album, and title so the best metadata wins. |
| **Artist Knowledge Cache** | After the first song by any artist, genre and albums are remembered. Subsequent songs skip all API calls. |
| **Organizer rules GUI** | Manage genre keywords, artist→genre overrides, country rules, and artist aliases directly in the web UI. |
| **Fingerprint recognition** | AcoustID + AudD identify untagged or wrongly tagged files dropped into the scanner folder. |
| **Audit trail** | Per-track pipeline trace — see exactly which source won each field and why. |
| **Scanner directory** | Drop any audio file into `/scanner` and it gets identified, tagged, and filed automatically. |
| **Playlist Monitor** | Watch Spotify playlists; new tracks download and organise on schedule. |
| **Artist Knowledge Cache editor** | Remove wrong genre or album entries directly from the web UI. |
| **Plex-gold theme** | Redesigned UI in `#E5A00D` amber to match the Plex look. |

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
      - /your/plex/music:/musik          # point Plex at this folder
      - /your/scanner/inbox:/scanner     # drop audio files here to auto-organise
      - /your/data:/data                 # databases + settings
    environment:
      - DOWNTIFY_PORT=30321
      - CLIENT_ID=your_spotify_client_id
      - CLIENT_SECRET=your_spotify_client_secret
      - LASTFM_API_KEY=your_lastfm_key
      - DISCOGS_TOKEN=your_discogs_token
      - ACOUSTID_API_KEY=your_acoustid_key
      - AUDD_API_TOKEN=your_audd_token
      - SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id
      # - AUTH_PASSWORD=yourpassword     # optional: protect the web UI
```

```bash
docker compose up -d
```

Open `http://localhost:8000` — paste a Spotify link to download, or drop files into `/scanner` to have them organised automatically.

**Plex setup:** point your Plex music library at the `/musik` volume. The folder structure `Genre/Artist/Album/` is recognised by Plex without any custom agent.

---

## How it works

```
Spotify / SoundCloud URL
        │
        ▼
  yt-dlp download ──────────────────────────────────────────┐
                                                            │
Scanner drop folder ─────────────────────────────────────── ▼
                                              11-step metadata pipeline
                                              ├─ Step 0   Read tags + fingerprint
                                              ├─ Step 0.5 Artist cache lookup
                                              ├─ Step 1   Query 6 API sources
                                              ├─ Step 2-4 Voting (best-of consensus)
                                              ├─ Step 4.5 Fuzzy album match
                                              ├─ Step 5-9 MusicBrainz + fingerprint
                                              ├─ Step 11  Organizer rules
                                              └─ Step 12  Update artist cache
                                                            │
                                                            ▼
                                              Genre/Artist/Album/track.mp3
                                                            │
                                                            ▼
                                                     Plex Media Server
```

---

## Metadata Voting Pipeline

Every file runs through an 11-step pipeline where 6 independent sources vote on each metadata field — the plurality winner with the highest confidence is used:

| Step | Name | Description |
|---|---|---|
| 0 | Tags + Fingerprint | Read existing ID3/Vorbis tags; AudD/AcoustID if tags are missing |
| 0.5 | **Artist Cache** | If artist genre is known → skip genre voting entirely |
| 1 | Query 6 sources | Spotify · Deezer · Last.fm · MusicBrainz · SoundCloud · Discogs |
| 2–4 | Voting | Plurality vote per field; quality: `sehr hoch` / `hoch` / `mittel` / `niedrig` |
| 4.5 | Album fuzzy match | Fuzzy-compare voted album against artist's known albums |
| 5–7 | MusicBrainz | Resolve remaining open fields via recording + artist lookup |
| 8–9 | Fingerprint | AcoustID → AudD cascade for still-unresolved fields |
| 10 | Org fields | Determine final meta source |
| 11 | Organizer rules | Genre keywords, artist→genre, country map, alias normalisation |
| 12 | Cache write | Update artist genre + albums in knowledge cache |

**Fast path:** Spotify-sourced track + artist genre in cache → steps 1–9 entirely skipped (zero external API calls).

---

## Artist Knowledge Cache

After the first song by an artist, Downtiplx remembers their genre and known albums:

```
raf camora  →  genre: Deutschrap  |  albums: [Palmen aus Plastik, NXTLVL, Anthrazit]
```

- **Genre** is overwritten when a new song produces a different result (change is logged in the audit trail)
- **Albums** are append-only — remove incorrect entries via the Cache Editor in the web UI
- **Spotify-ID + cached genre = zero API calls** for that track

---

## Organizer Rules

Configured in the web UI under **Organizer** — no config files to edit:

| Rule type | Example | Effect |
|---|---|---|
| Genre keyword | `hip hop` → `Hip-Hop` | Normalises genre spelling across all sources |
| Artist → Genre | `RAF Camora` → `Deutschrap` | Hardcoded genre override for specific artists |
| Country map | `DE` + `rap` → `Deutschrap` | Country-aware genre routing via MusicBrainz |
| Artist alias | `Raf Camora` = `RAF Camora` | Deduplicates artist name variants |
| Separator tokens | `feat.`, `ft.`, `×` | Splits featured artists out of the main artist field |

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOWNTIFY_PORT` | `30321` | HTTP port inside container |
| `CLIENT_ID` | — | Spotify app client ID **(required)** |
| `CLIENT_SECRET` | — | Spotify app client secret **(required)** |
| `LASTFM_API_KEY` | — | Last.fm API key |
| `DISCOGS_TOKEN` | — | Discogs personal access token |
| `ACOUSTID_API_KEY` | — | AcoustID fingerprinting key |
| `AUDD_API_TOKEN` | — | AudD recognition token |
| `SOUNDCLOUD_CLIENT_ID` | — | SoundCloud client ID (auto-discoverable in UI) |
| `DOWNLOAD_DIR` | `/downloads` | yt-dlp output directory |
| `MUSIK_DIR` | `/musik` | Organised music library (point Plex here) |
| `SCANNER_DIR` | `/scanner` | Drop-folder for external audio files |
| `DATA_DIR` | `/data` | SQLite databases + settings |
| `AUTH_PASSWORD` | — | Enable password protection when set |
| `ORGANIZER_POLL_INTERVAL` | `60` | Seconds between scanner sweeps |
| `ORGANIZER_FILE_COOLDOWN` | `30` | Seconds to wait after last file change before processing |
| `ENABLE_DOWNLOAD_WATCHER` | `true` | Auto-process `/downloads` |
| `ENABLE_SCANNER` | `true` | Auto-process `/scanner` |

---

## Credits

Original project: **[downtify](https://github.com/henriquesebastiao/downtify)** by [@henriquesebastiao](https://github.com/henriquesebastiao)

This fork extends the original with the automated organiser, metadata pipeline, and Plex-compatible folder structure. The download engine, Spotify integration, web player, and playlist monitor are all built on @henriquesebastiao's work.

---

## License

GPL-3.0 — same as the original project.
