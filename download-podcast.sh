#!/bin/bash

# Podcast Downloader Script
# Converts Spotify URLs to RSS feeds via iTunes lookup, then downloads using podcast-dl

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 <url> [options]"
    echo ""
    echo "Download podcast episodes from RSS feeds or Spotify URLs"
    echo ""
    echo "Arguments:"
    echo "  url           RSS feed URL or Spotify episode/show URL"
    echo ""
    echo "Options:"
    echo "  -o, --output  Output directory (default: ./downloads)"
    echo "  -h, --help    Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 'https://feed.podbean.com/planetem/feed.xml'"
    echo "  $0 'https://open.spotify.com/episode/56AGRQErADHFMlMV4Gm7y4'"
    echo "  $0 'https://open.spotify.com/show/SHOW_ID'"
}

check_dependencies() {
    local missing=()

    if ! command -v node &> /dev/null && ! command -v npx &> /dev/null; then
        missing+=("nodejs/npm (for podcast-dl)")
    fi

    if ! command -v curl &> /dev/null; then
        missing+=("curl")
    fi

    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        echo -e "${RED}Error: Missing dependencies:${NC}"
        for dep in "${missing[@]}"; do
            echo "  - $dep"
        done
        exit 1
    fi
}

# Get episode/show title from Spotify oEmbed API
get_spotify_title() {
    local url="$1"
    curl -s "https://open.spotify.com/oembed?url=$url" 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title',''))" 2>/dev/null
}

# Search iTunes for podcast and return RSS feed URL
search_itunes_rss() {
    local query="$1"
    local entity="$2"  # podcast or podcastEpisode

    # URL encode the query
    local encoded_query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$query'''))")

    curl -s "https://itunes.apple.com/search?term=${encoded_query}&media=podcast&entity=${entity}&limit=10" 2>/dev/null | \
        python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('results', [])
if results:
    # Return first result's feed URL
    print(results[0].get('feedUrl', ''))
" 2>/dev/null
}

# Interactive search - show multiple results and let user choose
search_itunes_interactive() {
    local query="$1"
    local entity="$2"

    local encoded_query=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$query")

    curl -s "https://itunes.apple.com/search?term=${encoded_query}&media=podcast&entity=${entity}&limit=10" 2>/dev/null | \
    python3 -c '
import sys, json

data = json.load(sys.stdin)
results = data.get("results", [])

if not results:
    print("NO_RESULTS")
    sys.exit(0)

# Deduplicate by feedUrl
seen = set()
unique = []
for r in results:
    feed = r.get("feedUrl", "")
    if feed and feed not in seen:
        seen.add(feed)
        unique.append(r)

if len(unique) == 1:
    print("SINGLE:" + unique[0].get("feedUrl", ""))
else:
    print("MULTIPLE")
    for i, r in enumerate(unique[:5], 1):
        name = r.get("collectionName", "Unknown").replace("\t", " ")
        feed = r.get("feedUrl", "")
        print(f"{i}\t{name}\t{feed}")
'
}

# Convert Spotify URL to RSS feed
spotify_to_rss() {
    local spotify_url="$1"

    echo -e "${BLUE}Fetching podcast info from Spotify...${NC}"

    # Get title from Spotify oEmbed
    local title=$(get_spotify_title "$spotify_url")

    if [ -z "$title" ]; then
        echo -e "${RED}Error: Could not fetch podcast info from Spotify${NC}"
        return 1
    fi

    echo -e "${GREEN}Found: ${NC}$title"
    echo -e "${BLUE}Searching for RSS feed...${NC}"

    # Determine if it's an episode or show URL
    local entity="podcastEpisode"
    if [[ "$spotify_url" == *"/show/"* ]]; then
        entity="podcast"
    fi

    # Search iTunes
    local search_result=$(search_itunes_interactive "$title" "$entity")

    if [ "$search_result" == "NO_RESULTS" ]; then
        echo -e "${RED}No matching podcasts found.${NC}"
        echo ""
        echo "Try searching manually:"
        echo "  1. Go to https://podcasts.apple.com and search for the podcast"
        echo "  2. Copy the RSS feed URL from the podcast page"
        echo "  3. Run: $0 '<RSS_URL>'"
        return 1
    fi

    local rss_url=""

    if [[ "$search_result" == SINGLE:* ]]; then
        rss_url="${search_result#SINGLE:}"
        echo -e "${GREEN}Found RSS feed: ${NC}$rss_url"
    else
        # Auto-select the first matching result
        local first_feed=""
        local first_name=""
        while IFS=$'\t' read -r num name feed; do
            if [ -n "$num" ] && [ "$num" != "MULTIPLE" ] && [ -z "$first_feed" ]; then
                first_feed="$feed"
                first_name="$name"
            fi
        done <<< "$search_result"

        if [ -n "$first_feed" ]; then
            echo -e "${YELLOW}Multiple podcasts found. Auto-selecting first match:${NC} $first_name"
            rss_url="$first_feed"
        else
            echo -e "${RED}Could not parse search results${NC}"
            return 1
        fi
    fi

    echo "$rss_url"
}

# Download from RSS feed using podcast-dl
download_from_rss() {
    local url="$1"
    local output_dir="$2"
    local episode_filter="$3"

    echo -e "${GREEN}Downloading from RSS feed...${NC}"
    echo -e "${BLUE}URL: ${NC}$url"
    if [ -n "$episode_filter" ]; then
        echo -e "${BLUE}Episode filter: ${NC}$episode_filter"
    fi
    echo ""

    if command -v npx &> /dev/null; then
        if [ -n "$episode_filter" ]; then
            # Download only the specific episode matching the filter
            npx podcast-dl --url "$url" --out-dir "$output_dir" --episode-template "{{podcast_title}}/{{episode_title}}" --episode-regex "$episode_filter"
        else
            # Download all episodes
            npx podcast-dl --url "$url" --out-dir "$output_dir" --episode-template "{{podcast_title}}/{{episode_title}}"
        fi
    else
        echo -e "${RED}Error: npx not found. Install Node.js first:${NC}"
        echo "  brew install node    # macOS"
        echo "  apt install nodejs   # Ubuntu/Debian"
        exit 1
    fi
}

# Main script
main() {
    local url=""
    local output_dir="./downloads"

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                usage
                exit 0
                ;;
            -o|--output)
                output_dir="$2"
                shift 2
                ;;
            *)
                if [ -z "$url" ]; then
                    url="$1"
                fi
                shift
                ;;
        esac
    done

    if [ -z "$url" ]; then
        usage
        exit 1
    fi

    check_dependencies

    # Create output directory
    mkdir -p "$output_dir"

    local rss_url=""
    local episode_filter=""

    # Determine URL type
    if [[ "$url" == *"spotify.com"* ]]; then
        echo -e "${YELLOW}Spotify URL detected. Converting to RSS...${NC}"
        echo ""

        # If it's an episode URL, get the episode title for filtering
        if [[ "$url" == *"/episode/"* ]]; then
            episode_filter=$(get_spotify_title "$url")
            # Escape special regex characters in the title
            episode_filter=$(echo "$episode_filter" | sed 's/[[\.*^$()+?{|]/\\&/g')
            echo -e "${BLUE}Will download only: ${NC}$episode_filter"
            echo ""
        fi

        rss_url=$(spotify_to_rss "$url")

        if [ -z "$rss_url" ] || [[ "$rss_url" == *"Error"* ]] || [[ "$rss_url" == *"No matching"* ]]; then
            exit 1
        fi

        # Extract just the URL (last line of output)
        rss_url=$(echo "$rss_url" | tail -1)
        echo ""
    elif [[ "$url" == *"feed"* ]] || [[ "$url" == *".xml"* ]] || [[ "$url" == *"rss"* ]]; then
        rss_url="$url"
    else
        # Assume it's an RSS feed
        echo -e "${YELLOW}Assuming URL is an RSS feed...${NC}"
        rss_url="$url"
    fi

    download_from_rss "$rss_url" "$output_dir" "$episode_filter"

    echo ""
    echo -e "${GREEN}Done! Files saved to: $output_dir${NC}"
}

main "$@"
