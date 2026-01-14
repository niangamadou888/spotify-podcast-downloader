# Podcast Downloader

A simple bash script to download podcasts from RSS feeds or Spotify URLs.

## How It Works

- **RSS feeds**: Downloads directly using `podcast-dl`
- **Spotify URLs**: Converts to RSS via iTunes API lookup, then downloads

## Requirements

- Node.js (for `podcast-dl`)
- Python 3
- curl

### macOS

```bash
brew install node python3
```

### Ubuntu/Debian

```bash
sudo apt install nodejs npm python3 curl
```

## Usage

```bash
./download-podcast.sh <url> [options]
```

### Options

| Option | Description |
|--------|-------------|
| `-o, --output` | Output directory (default: `./downloads`) |
| `-h, --help` | Show help message |

### Examples

**Download from RSS feed:**

```bash
./download-podcast.sh 'https://feed.podbean.com/planetem/feed.xml'
```

**Download Spotify episode:**

```bash
./download-podcast.sh 'https://open.spotify.com/episode/56AGRQErADHFMlMV4Gm7y4'
```

**Download entire Spotify show:**

```bash
./download-podcast.sh 'https://open.spotify.com/show/SHOW_ID'
```

**Custom output directory:**

```bash
./download-podcast.sh 'https://example.com/feed.xml' -o ~/Podcasts
```

## Notes

- Spotify URLs are converted to RSS feeds via iTunes search
- Episode URLs download only the specific episode
- Show URLs download all available episodes
- Files are organized by podcast name in the output directory

## License

MIT
