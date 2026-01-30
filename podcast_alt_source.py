#!/usr/bin/env python3
"""
Podcast Alt Source
Finds and downloads podcast episodes from alternative platforms when Spotify DRM blocks direct access.
Matches episodes by duration to ensure accuracy.

Supported platforms (all free, no API keys required):
- Fyyd (German podcast database with open API - primary, has direct audio)
- PodBean (major podcast hosting platform)
- Player FM (podcast aggregator)
- Podchaser (global podcast database)
- RaiPlay Sound (Italian podcasts)
- YouTube (last resort - some podcasts upload full episodes)

The script searches these platforms and matches episodes by duration.
"""

import subprocess
import json
import re
import sys
import argparse
import urllib.parse
import html as html_module
import requests
from bs4 import BeautifulSoup
from pytubefix import YouTube, Search
from pytubefix.exceptions import PytubeFixError


# Known RaiPlay Sound show mappings
RAIPLAYSOUND_SHOWS = {
    'maturadio': {
        'base_url': 'https://www.raiplaysound.it/programmi/maturadio',
        'playlists': [
            'https://www.raiplaysound.it/playlist/italiano-maturadio.json',
            'https://www.raiplaysound.it/playlist/filosofia-maturadio.json',
            'https://www.raiplaysound.it/playlist/fisica-maturadio.json',
            'https://www.raiplaysound.it/playlist/greco-maturadio.json',
            'https://www.raiplaysound.it/playlist/inglese-maturadio.json',
            'https://www.raiplaysound.it/playlist/latino-maturadio.json',
            'https://www.raiplaysound.it/playlist/matematica-maturadio.json',
            'https://www.raiplaysound.it/playlist/scienze-maturadio.json',
            'https://www.raiplaysound.it/playlist/storia-maturadio.json',
            'https://www.raiplaysound.it/playlist/storiadellarte-maturadio.json',
        ]
    }
}


def parse_duration_to_seconds(duration_str: str) -> int:
    """Convert duration string to seconds. Handles various formats."""
    if not duration_str:
        return 0

    duration_str = duration_str.strip().lower()

    # Handle "X min" or "X min Y sec" format
    if 'min' in duration_str:
        match = re.search(r'(\d+)\s*min', duration_str)
        minutes = int(match.group(1)) if match else 0
        match = re.search(r'(\d+)\s*sec', duration_str)
        seconds = int(match.group(1)) if match else 0
        return minutes * 60 + seconds

    # Handle "HH:MM:SS" or "MM:SS" format
    if ':' in duration_str:
        parts = duration_str.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])

    # Handle ISO 8601 duration (PT34M16S)
    if duration_str.startswith('pt'):
        hours = 0
        minutes = 0
        seconds = 0
        match = re.search(r'(\d+)h', duration_str)
        if match:
            hours = int(match.group(1))
        match = re.search(r'(\d+)m', duration_str)
        if match:
            minutes = int(match.group(1))
        match = re.search(r'(\d+)s', duration_str)
        if match:
            seconds = int(match.group(1))
        return hours * 3600 + minutes * 60 + seconds

    # Try to parse as pure seconds
    try:
        return int(float(duration_str))
    except:
        return 0


def format_duration(seconds: int) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    if seconds <= 0:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def duration_matches(source_seconds: int, target_seconds: int, tolerance: int = 90) -> bool:
    """Check if durations match within tolerance (default 90 seconds)."""
    if source_seconds == 0 or target_seconds == 0:
        return True  # Can't compare, assume match
    return abs(source_seconds - target_seconds) <= tolerance


def decode_html_entities(text: str) -> str:
    """Decode HTML entities in text."""
    return html_module.unescape(text)


def get_spotify_episode_info(url: str) -> dict:
    """Extract episode metadata from Spotify URL using curl (more reliable than requests)."""
    print(f"[*] Fetching Spotify episode info...")

    try:
        # Use curl to fetch the page (more reliable - Spotify blocks some Python requests)
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Accept: text/html,application/xhtml+xml',
            '-H', 'Accept-Language: en-US,en;q=0.9',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        html_content = result.stdout

        if len(html_content) < 1000:
            print(f"[-] Failed to fetch page content")
            return {}

        info = {}

        # Extract episode ID from URL
        match = re.search(r'/episode/([a-zA-Z0-9]+)', url)
        if match:
            info['episode_id'] = match.group(1)

        # Extract og:title
        match = re.search(r'og:title.*?content="([^"]+)"', html_content)
        if match:
            title = decode_html_entities(match.group(1).strip())
            info['title'] = title
            info['episode_title'] = title

        # Extract music:duration (in seconds)
        match = re.search(r'music:duration.*?content="(\d+)"', html_content)
        if match:
            info['duration_seconds'] = int(match.group(1))

        # Extract description meta tag
        match = re.search(r'name="description".*?content="([^"]+)"', html_content)
        if match:
            info['description'] = decode_html_entities(match.group(1))

        # Extract show name from description: "Listen to this episode from SHOWNAME on Spotify"
        if 'description' in info:
            desc = info['description']
            m = re.search(r'from\s+(.+?)\s+on\s+Spotify', desc, re.IGNORECASE)
            if m:
                info['show_name'] = decode_html_entities(m.group(1).strip())

        # Also try JSON-LD for show name
        match = re.search(r'<script\s+type="application/ld\+json">(.+?)</script>', html_content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict):
                    if 'name' in data and not info.get('episode_title'):
                        info['episode_title'] = decode_html_entities(data['name'])
            except:
                pass

        # Print found info
        print(f"[+] Title: {info.get('episode_title', info.get('title', 'Unknown'))}")
        if info.get('show_name'):
            print(f"[+] Show: {info['show_name']}")
        if info.get('duration_seconds'):
            print(f"[+] Duration: {format_duration(info['duration_seconds'])}")

        return info

    except Exception as e:
        print(f"[-] Error fetching Spotify info: {e}")
        return {}




def search_raiplaysound(episode_title: str, show_name: str = None) -> list:
    """Search RaiPlay Sound for Italian podcasts."""
    print(f"[*] Searching RaiPlay Sound...")

    results = []

    # Normalize search terms from episode title
    search_terms = episode_title.lower().split()
    stopwords = ['the', 'and', 'for', 'con', 'del', 'della', 'di', 'il', 'la', 'le', 'lo', 'gli', 'un', 'una']
    search_terms = [t for t in search_terms if len(t) > 2 and t not in stopwords]

    # Check known shows first
    if show_name:
        show_key = show_name.lower().replace(' ', '').replace('-', '')
        if show_key in RAIPLAYSOUND_SHOWS:
            print(f"[+] Found known show: {show_name}")
            show_config = RAIPLAYSOUND_SHOWS[show_key]
            for playlist_url in show_config['playlists']:
                matches = search_raiplaysound_playlist(playlist_url, search_terms)
                results.extend(matches)

    # If no show name or no results, try all known shows
    if not results:
        for show_key, show_config in RAIPLAYSOUND_SHOWS.items():
            for playlist_url in show_config['playlists']:
                matches = search_raiplaysound_playlist(playlist_url, search_terms)
                results.extend(matches)

    # Deduplicate by URL
    seen = set()
    unique_results = []
    for r in results:
        if r['url'] not in seen:
            seen.add(r['url'])
            unique_results.append(r)

    # Sort by match_score (higher is better)
    unique_results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

    if unique_results:
        print(f"[+] Found {len(unique_results)} RaiPlay Sound results")

    # Return top results (already sorted by match score)
    return unique_results


def search_raiplaysound_playlist(playlist_url: str, search_terms: list) -> list:
    """Search within a RaiPlay Sound playlist JSON."""
    results = []

    try:
        # Use curl to fetch (requests gets blocked)
        cmd = ['curl', '-s', '-L', '-H', 'User-Agent: Mozilla/5.0', playlist_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if not result.stdout or len(result.stdout) < 100:
            return []

        data = json.loads(result.stdout)
        cards = data.get('block', {}).get('cards', [])

        for card in cards:
            card_title = card.get('title', '').lower()
            card_desc = card.get('description', '').lower()

            matches = sum(1 for term in search_terms if term in card_title or term in card_desc)

            if matches >= 1:
                weblink = card.get('weblink', '')
                if weblink:
                    # Parse duration from "34 min" or "34:16" format
                    duration_str = card.get('literal_duration', '') or card.get('duration_small_format', '')
                    duration_seconds = parse_duration_to_seconds(duration_str)

                    results.append({
                        'title': card.get('title'),
                        'url': f"https://www.raiplaysound.it{weblink}",
                        'duration': duration_str,
                        'duration_seconds': duration_seconds,
                        'platform': 'raiplaysound',
                        'match_score': matches
                    })

    except Exception as e:
        pass

    return results


def search_fyyd(episode_title: str, show_name: str = None) -> list:
    """Search Fyyd - German podcast database with open REST API (no auth required)."""
    print(f"[*] Searching Fyyd (open API)...")

    results = []

    # Build search query
    search_query = episode_title
    if show_name:
        search_query = f"{show_name} {episode_title}"

    encoded_query = urllib.parse.quote(search_query)

    # Fyyd API - completely free, no authentication
    api_url = f"https://api.fyyd.de/0.2/search/episode?title={encoded_query}&count=20"

    try:
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            '-H', 'Accept: application/json',
            api_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if not result.stdout:
            return []

        data = json.loads(result.stdout)
        episodes = data.get('data', [])

        # Normalize search terms for matching
        search_terms = episode_title.lower().split()
        stopwords = ['the', 'and', 'for', 'a', 'an', 'of', 'to', 'in', 'on', 'with']
        search_terms = [t for t in search_terms if len(t) > 2 and t not in stopwords]

        for ep in episodes:
            title = ep.get('title', '')
            episode_url = ep.get('enclosure', '') or ep.get('url', '')
            duration_seconds = ep.get('duration', 0)
            podcast_title = ep.get('podcast', {}).get('title', '') if isinstance(ep.get('podcast'), dict) else ''

            if not episode_url:
                continue

            # Calculate match score
            title_lower = title.lower()
            match_count = sum(1 for term in search_terms if term in title_lower)

            # Check if it's a direct audio URL
            is_direct = any(ext in episode_url.lower() for ext in ['.mp3', '.m4a', '.mp4', '.aac', '.ogg'])

            results.append({
                'title': title,
                'show': podcast_title,
                'url': episode_url,
                'duration': format_duration(duration_seconds),
                'duration_seconds': duration_seconds,
                'platform': 'fyyd',
                'match_score': match_count,
                'direct_audio': is_direct
            })

        # Sort by match score
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        if results:
            print(f"[+] Found {len(results)} Fyyd results")

    except Exception as e:
        print(f"[-] Fyyd search error: {e}")

    return results[:15]


def search_podbean(episode_title: str, show_name: str = None) -> list:
    """Search PodBean - major podcast hosting platform."""
    print(f"[*] Searching PodBean...")

    results = []

    # Build search query
    search_query = episode_title
    if show_name:
        search_query = f"{show_name} {episode_title}"

    encoded_query = urllib.parse.quote(search_query)

    # PodBean search
    search_url = f"https://www.podbean.com/site/searchEpisode?q={encoded_query}"

    try:
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Accept: text/html,application/xhtml+xml',
            search_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if not result.stdout or len(result.stdout) < 500:
            return []

        html = result.stdout

        # Normalize search terms for matching
        search_terms = episode_title.lower().split()
        stopwords = ['the', 'and', 'for', 'a', 'an', 'of', 'to', 'in', 'on', 'with']
        search_terms = [t for t in search_terms if len(t) > 2 and t not in stopwords]

        # Parse episode links from search results
        # Look for episode URLs and titles
        episode_pattern = r'href="(https://www\.podbean\.com/[^"]*episode[^"]*)"[^>]*>([^<]+)</a>'
        matches_found = re.findall(episode_pattern, html, re.IGNORECASE)

        seen_urls = set()
        for url, title in matches_found:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = title.strip()
            if not title or len(title) < 3:
                continue

            # Calculate match score
            title_lower = title.lower()
            match_count = sum(1 for term in search_terms if term in title_lower)

            if match_count >= 1:
                results.append({
                    'title': title,
                    'url': url,
                    'duration': 'Unknown',
                    'duration_seconds': 0,
                    'platform': 'podbean',
                    'match_score': match_count
                })

        # Sort by match score
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        if results:
            print(f"[+] Found {len(results)} PodBean results")

    except Exception as e:
        print(f"[-] PodBean search error: {e}")

    return results[:10]


def search_player_fm(episode_title: str, show_name: str = None) -> list:
    """Search Player FM - podcast aggregator."""
    print(f"[*] Searching Player FM...")

    results = []

    # Build search query
    search_query = episode_title
    if show_name:
        search_query = f"{show_name} {episode_title}"

    encoded_query = urllib.parse.quote(search_query)

    # Player FM search
    search_url = f"https://player.fm/search?q={encoded_query}"

    try:
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Accept: text/html,application/xhtml+xml',
            search_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if not result.stdout or len(result.stdout) < 1000:
            return []

        html = result.stdout

        # Normalize search terms for matching
        search_terms = episode_title.lower().split()
        stopwords = ['the', 'and', 'for', 'a', 'an', 'of', 'to', 'in', 'on', 'with']
        search_terms = [t for t in search_terms if len(t) > 2 and t not in stopwords]

        # Parse episode links from search results
        # Player FM uses /series/ for podcasts and episode links within
        episode_pattern = r'href="(/series/[^"]+)"[^>]*>([^<]+)</a>'
        matches_found = re.findall(episode_pattern, html, re.IGNORECASE)

        seen_urls = set()
        for href, title in matches_found:
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title = title.strip()
            if not title or len(title) < 3:
                continue

            # Calculate match score
            title_lower = title.lower()
            match_count = sum(1 for term in search_terms if term in title_lower)

            if match_count >= 1:
                full_url = f"https://player.fm{href}"
                results.append({
                    'title': title,
                    'url': full_url,
                    'duration': 'Unknown',
                    'duration_seconds': 0,
                    'platform': 'player_fm',
                    'match_score': match_count
                })

        # Sort by match score
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        if results:
            print(f"[+] Found {len(results)} Player FM results")

    except Exception as e:
        print(f"[-] Player FM search error: {e}")

    return results[:10]


def search_podchaser(episode_title: str, show_name: str = None) -> list:
    """Search Podchaser for podcast episodes."""
    print(f"[*] Searching Podchaser...")

    results = []

    # Build search query
    search_query = episode_title
    if show_name:
        search_query = f"{show_name} {episode_title}"

    encoded_query = urllib.parse.quote(search_query)

    # Podchaser search URL
    search_url = f"https://www.podchaser.com/search/episodes?q={encoded_query}"

    try:
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Accept: text/html,application/xhtml+xml',
            search_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if not result.stdout or len(result.stdout) < 1000:
            return []

        html = result.stdout

        # Normalize search terms for matching
        search_terms = episode_title.lower().split()
        stopwords = ['the', 'and', 'for', 'a', 'an', 'of', 'to', 'in', 'on', 'with']
        search_terms = [t for t in search_terms if len(t) > 2 and t not in stopwords]

        # Parse episode cards from HTML
        # Look for episode links and titles in the search results
        # Pattern: /episodes/TITLE-ID format
        episode_pattern = r'href="(/episodes/[^"]+)"[^>]*>([^<]+)</a>'
        matches_found = re.findall(episode_pattern, html, re.IGNORECASE)

        seen_urls = set()
        for href, title in matches_found:
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title = title.strip()
            if not title or len(title) < 3:
                continue

            # Calculate match score
            title_lower = title.lower()
            match_count = sum(1 for term in search_terms if term in title_lower)

            if match_count >= 1:
                full_url = f"https://www.podchaser.com{href}"
                results.append({
                    'title': title,
                    'url': full_url,
                    'duration': 'Unknown',
                    'duration_seconds': 0,
                    'platform': 'podchaser',
                    'match_score': match_count
                })

        # Sort by match score
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        if results:
            print(f"[+] Found {len(results)} Podchaser results")

    except Exception as e:
        print(f"[-] Podchaser search error: {e}")

    return results[:10]


def search_youtube(episode_title: str, show_name: str = None, target_duration: int = 0) -> list:
    """Search YouTube for podcast episodes using pytube."""
    print(f"[*] Searching YouTube...")

    results = []

    # Build search query - include "podcast" to improve results
    search_query = episode_title
    if show_name:
        search_query = f"{show_name} {episode_title}"

    # Add "podcast" if not already in query to get better results
    if 'podcast' not in search_query.lower():
        search_query = f"{search_query} podcast"

    try:
        # Use pytube to search YouTube
        search = Search(search_query)
        search_results = search.results[:10]  # Get up to 10 results

        if not search_results:
            return []

        # Normalize search terms for matching
        search_terms = episode_title.lower().split()
        stopwords = ['the', 'and', 'for', 'a', 'an', 'of', 'to', 'in', 'on', 'with', 'podcast']
        search_terms = [t for t in search_terms if len(t) > 2 and t not in stopwords]

        for video in search_results:
            try:
                video_id = video.video_id
                title = video.title or ''
                duration_seconds = video.length or 0
                channel = video.author or ''

                if not video_id or not title:
                    continue

                # Calculate match score
                title_lower = title.lower()
                match_count = sum(1 for term in search_terms if term in title_lower)

                # Bonus for channel name matching show name
                if show_name and show_name.lower() in channel.lower():
                    match_count += 2

                video_url = f"https://www.youtube.com/watch?v={video_id}"

                results.append({
                    'title': title,
                    'show': channel,
                    'url': video_url,
                    'duration': format_duration(duration_seconds),
                    'duration_seconds': duration_seconds,
                    'platform': 'youtube',
                    'match_score': match_count,
                    'direct_audio': False
                })

            except Exception:
                continue

        # Sort by match score
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        if results:
            print(f"[+] Found {len(results)} YouTube results")

    except PytubeFixError as e:
        print(f"[-] YouTube search error: {e}")
    except Exception as e:
        print(f"[-] YouTube search error: {e}")

    return results[:10]


def download_raiplaysound(url: str, output_name: str) -> bool:
    """Download audio from RaiPlaySound page by extracting the relinker URL."""
    print(f"[*] Extracting audio from RaiPlaySound page...")

    try:
        # Fetch the page to find the relinker URL
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        html_content = result.stdout

        if not html_content or len(html_content) < 1000:
            print("[-] Failed to fetch RaiPlaySound page")
            return False

        # Look for relinker URL pattern
        # Pattern: https://mediapolisvod.rai.it/relinker/relinkerServlet.htm?cont=...
        relinker_match = re.search(
            r'https://mediapolisvod\.rai\.it/relinker/relinkerServlet\.htm\?cont=[^"\'<>\s]+',
            html_content
        )

        if not relinker_match:
            print("[-] Could not find relinker URL in page")
            return False

        relinker_url = relinker_match.group(0)
        print(f"[*] Found relinker URL: {relinker_url[:80]}...")

        # Follow the relinker redirect to get the actual audio URL
        cmd = [
            'curl', '-sI', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            relinker_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        headers = result.stdout

        # Extract the final Location header or look for the actual audio URL
        audio_url = None

        # Check if there's a redirect to the audio file
        location_matches = re.findall(r'location:\s*(https?://[^\s]+)', headers, re.IGNORECASE)
        for loc in location_matches:
            if any(ext in loc.lower() for ext in ['.mp3', '.m4a', '.aac', '.mp4']):
                audio_url = loc
                break

        if not audio_url:
            # Try direct download from relinker
            audio_url = relinker_url

        print(f"[*] Downloading audio: {audio_url[:80]}...")

        # Download the audio file
        output_file = f"{output_name}.mp3"
        cmd = [
            'curl', '-L', '-o', output_file,
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            '--progress-bar',
            audio_url
        ]

        result = subprocess.run(cmd, timeout=600)
        if result.returncode == 0:
            # Verify file was downloaded
            import os
            if os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
                print(f"[+] Saved to: {output_file}")
                return True
            else:
                print("[-] Downloaded file is too small or missing")
                return False
        return False

    except Exception as e:
        print(f"[-] RaiPlaySound download error: {e}")
        return False


def extract_audio_from_page(url: str, output_name: str) -> bool:
    """Try to extract and download audio from a podcast page by looking for common patterns."""
    print(f"[*] Attempting to extract audio from page...")

    try:
        # Fetch the page
        cmd = [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Accept: text/html,application/xhtml+xml',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        html_content = result.stdout

        if not html_content or len(html_content) < 500:
            print("[-] Failed to fetch page")
            return False

        audio_url = None

        # Pattern 1: Direct audio file URLs (.mp3, .m4a, .ogg, etc.)
        audio_patterns = [
            r'https?://[^"\'<>\s]+\.mp3(?:\?[^"\'<>\s]*)?',
            r'https?://[^"\'<>\s]+\.m4a(?:\?[^"\'<>\s]*)?',
            r'https?://[^"\'<>\s]+\.ogg(?:\?[^"\'<>\s]*)?',
            r'https?://[^"\'<>\s]+\.aac(?:\?[^"\'<>\s]*)?',
        ]

        for pattern in audio_patterns:
            matches = re.findall(pattern, html_content)
            # Filter out tiny files (icons, etc) and prefer longer URLs (more likely to be episode audio)
            for match in matches:
                # Skip obvious non-audio URLs
                if any(skip in match.lower() for skip in ['icon', 'logo', 'thumb', 'image', 'avatar', 'artwork']):
                    continue
                audio_url = match
                break
            if audio_url:
                break

        # Pattern 2: enclosure URL in RSS-like data or JSON
        if not audio_url:
            enclosure_match = re.search(r'"enclosure"[:\s]*"(https?://[^"]+)"', html_content)
            if enclosure_match:
                audio_url = enclosure_match.group(1)

        # Pattern 3: audio src attribute
        if not audio_url:
            audio_src_match = re.search(r'<audio[^>]+src=["\'](https?://[^"\']+)["\']', html_content)
            if audio_src_match:
                audio_url = audio_src_match.group(1)

        # Pattern 4: source element inside audio tag
        if not audio_url:
            source_match = re.search(r'<source[^>]+src=["\'](https?://[^"\']+\.(?:mp3|m4a|ogg))["\']', html_content)
            if source_match:
                audio_url = source_match.group(1)

        # Pattern 5: data-audio or data-url attributes
        if not audio_url:
            data_audio_match = re.search(r'data-(?:audio|url|src)=["\'](https?://[^"\']+\.(?:mp3|m4a|ogg)[^"\']*)["\']', html_content)
            if data_audio_match:
                audio_url = data_audio_match.group(1)

        if audio_url:
            print(f"[+] Found audio URL: {audio_url[:80]}...")
            return download_direct_audio(audio_url, output_name)
        else:
            print("[-] Could not extract audio URL from page")
            print(f"[*] You may need to visit the page manually: {url}")
            return False

    except Exception as e:
        print(f"[-] Error extracting audio: {e}")
        return False


def download_direct_audio(url: str, output_name: str) -> bool:
    """Download audio directly using curl (for direct audio URLs)."""
    print(f"[*] Downloading direct audio from: {url}")

    # Determine file extension from URL
    ext = 'mp3'
    if '.m4a' in url:
        ext = 'm4a'
    elif '.mp4' in url:
        ext = 'mp4'
    elif '.aac' in url:
        ext = 'aac'
    elif '.ogg' in url:
        ext = 'ogg'

    output_file = f"{output_name}.{ext}"

    cmd = [
        'curl', '-L', '-o', output_file,
        '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        '--progress-bar',
        url
    ]

    try:
        result = subprocess.run(cmd, timeout=600)
        if result.returncode == 0:
            print(f"[+] Saved to: {output_file}")
            return True
        return False
    except Exception as e:
        print(f"[-] Download error: {e}")
        return False


def download_with_pytube(url: str, output_name: str = None, audio_only: bool = True) -> bool:
    """Download audio using pytube."""
    print(f"[*] Downloading from: {url}")

    try:
        yt = YouTube(url)

        if audio_only:
            # Get the highest quality audio stream
            stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
            if not stream:
                print("[-] No audio stream found")
                return False

            print(f"[*] Downloading audio: {stream.abr}")
            output_file = stream.download(filename=output_name if output_name else None)

            # Convert to mp3 if ffmpeg is available
            if output_file and not output_file.endswith('.mp3'):
                mp3_file = output_file.rsplit('.', 1)[0] + '.mp3'
                try:
                    cmd = ['ffmpeg', '-i', output_file, '-vn', '-acodec', 'libmp3lame', '-q:a', '0', mp3_file, '-y']
                    result = subprocess.run(cmd, capture_output=True, timeout=300)
                    if result.returncode == 0:
                        import os
                        os.remove(output_file)
                        output_file = mp3_file
                except FileNotFoundError:
                    print("[*] ffmpeg not found, keeping original format")
                except Exception:
                    pass

            print(f"[+] Saved to: {output_file}")
            return True
        else:
            # Get the highest quality video+audio stream
            stream = yt.streams.get_highest_resolution()
            if not stream:
                print("[-] No video stream found")
                return False

            print(f"[*] Downloading video: {stream.resolution}")
            output_file = stream.download(filename=output_name if output_name else None)
            print(f"[+] Saved to: {output_file}")
            return True

    except PytubeFixError as e:
        print(f"[-] Download error: {e}")
        return False
    except Exception as e:
        print(f"[-] Download error: {e}")
        return False


def download_video_with_subs(url: str, output_name: str = None) -> bool:
    """Download video with subtitles from YouTube using pytube."""
    print(f"[*] Downloading video with subtitles from: {url}")

    try:
        yt = YouTube(url)

        # Download video
        stream = yt.streams.get_highest_resolution()
        if not stream:
            print("[-] No video stream found")
            return False

        print(f"[*] Downloading video: {stream.resolution}")
        output_file = stream.download(filename=output_name if output_name else None)
        print(f"[+] Video saved to: {output_file}")

        # Download captions if available
        if yt.captions:
            base_name = output_file.rsplit('.', 1)[0] if output_file else (output_name or yt.title)
            for lang_code, caption in yt.captions.items():
                try:
                    srt_content = caption.generate_srt_captions()
                    srt_file = f"{base_name}.{lang_code}.srt"
                    with open(srt_file, 'w', encoding='utf-8') as f:
                        f.write(srt_content)
                    print(f"[+] Subtitles saved: {srt_file}")
                except Exception:
                    pass
        else:
            print("[*] No captions available for this video")

        return True

    except PytubeFixError as e:
        print(f"[-] Download error: {e}")
        return False
    except Exception as e:
        print(f"[-] Download error: {e}")
        return False


def interactive_select(sources: list) -> dict:
    """Let user interactively select a source."""
    print("\nSelect a source to download:")
    for i, source in enumerate(sources, 1):
        platform = source.get('platform', 'unknown')
        title = source.get('title', 'Unknown')
        show = source.get('show', '')
        duration = source.get('duration', '')
        match_tag = " [MATCH]" if source.get('duration_match') else ""
        direct_tag = " [DIRECT]" if source.get('direct_audio') else ""
        dur_str = f" ({duration})" if duration else ""
        show_str = f" - {show}" if show else ""
        print(f"  {i}. [{platform}] {title}{show_str}{dur_str}{match_tag}{direct_tag}")

    print(f"  0. Cancel")

    while True:
        try:
            choice = input("\nEnter number: ").strip()
            if choice == '0':
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(sources):
                return sources[idx]
            print("Invalid selection. Try again.")
        except ValueError:
            print("Please enter a number.")
        except KeyboardInterrupt:
            return None


def main():
    parser = argparse.ArgumentParser(
        description='Find and download podcast episodes from alternative sources (matches by duration)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://open.spotify.com/episode/xxxxx
  %(prog)s https://open.spotify.com/episode/xxxxx -o my_episode
  %(prog)s https://open.spotify.com/episode/xxxxx --list-sources
  %(prog)s https://open.spotify.com/episode/xxxxx --show "The Daily"
  %(prog)s https://open.spotify.com/episode/xxxxx -i
  %(prog)s https://open.spotify.com/episode/xxxxx --fyyd-only

Supported platforms (all free, no API keys):
  - Fyyd (open API, often has direct audio - primary)
  - PodBean (major hosting platform)
  - Player FM (podcast aggregator)
  - Podchaser (global database)
  - RaiPlay Sound (Italian podcasts)
  - YouTube (last resort - full episodes sometimes uploaded)
        """
    )
    parser.add_argument('url', help='Spotify episode URL')
    parser.add_argument('-o', '--output', help='Output filename (without extension)')
    parser.add_argument('-s', '--show', help='Manually specify the show name (for better search)')
    parser.add_argument('--list-sources', action='store_true',
                        help='List found sources without downloading')
    parser.add_argument('-i', '--interactive', action='store_true',
                        help='Interactively select source to download')
    parser.add_argument('--with-video', action='store_true',
                        help='Download video (for YouTube sources)')
    parser.add_argument('--tolerance', type=int, default=90,
                        help='Duration match tolerance in seconds (default: 90)')
    # Platform-specific flags
    parser.add_argument('--fyyd-only', action='store_true',
                        help='Search only Fyyd')
    parser.add_argument('--podbean-only', action='store_true',
                        help='Search only PodBean')
    parser.add_argument('--player-fm-only', action='store_true',
                        help='Search only Player FM')
    parser.add_argument('--podchaser-only', action='store_true',
                        help='Search only Podchaser')
    parser.add_argument('--raiplaysound-only', action='store_true',
                        help='Search only RaiPlay Sound (Italian)')
    parser.add_argument('--youtube-only', action='store_true',
                        help='Search only YouTube')

    args = parser.parse_args()

    # Validate URL
    if 'spotify.com/episode' not in args.url:
        print("[-] Invalid Spotify episode URL")
        sys.exit(1)

    # Get episode info
    info = get_spotify_episode_info(args.url)
    if not info:
        print("[-] Could not fetch episode information")
        sys.exit(1)

    # Use manual show name if provided
    if args.show:
        info['show_name'] = args.show

    episode_title = info.get('episode_title', info.get('title', ''))
    show_name = info.get('show_name', '')
    target_duration = info.get('duration_seconds', 0)

    print(f"\n{'='*60}")
    print(f"Episode: {episode_title}")
    print(f"Show: {show_name or 'Unknown'}")
    print(f"Duration: {format_duration(target_duration)}")
    print(f"{'='*60}\n")

    sources = []

    # Determine which platforms to search
    single_platform = (args.fyyd_only or args.podbean_only or
                       args.player_fm_only or args.podchaser_only or
                       args.raiplaysound_only or args.youtube_only)
    search_all = not single_platform

    # Search Fyyd (open API - primary, often has direct audio)
    if search_all or args.fyyd_only:
        fyyd_results = search_fyyd(episode_title, show_name)
        sources.extend(fyyd_results)

    # Search PodBean
    if search_all or args.podbean_only:
        podbean_results = search_podbean(episode_title, show_name)
        good_podbean = [r for r in podbean_results if r.get('match_score', 0) >= 1]
        sources.extend(good_podbean[:10])

    # Search Player FM
    if search_all or args.player_fm_only:
        player_results = search_player_fm(episode_title, show_name)
        good_player = [r for r in player_results if r.get('match_score', 0) >= 1]
        sources.extend(good_player[:10])

    # Search Podchaser (global)
    if search_all or args.podchaser_only:
        podchaser_results = search_podchaser(episode_title, show_name)
        # Only add Podchaser results with good match scores
        good_podchaser = [r for r in podchaser_results if r.get('match_score', 0) >= 2]
        sources.extend(good_podchaser[:5])

    # Search RaiPlay Sound (for Italian content)
    if search_all or args.raiplaysound_only:
        rai_results = search_raiplaysound(episode_title, show_name)
        # Keep results with high match scores (2+)
        good_matches = [r for r in rai_results if r.get('match_score', 0) >= 2]
        sources.extend(good_matches[:10])

    # Search YouTube (last resort - may have full episodes uploaded)
    if search_all or args.youtube_only:
        youtube_results = search_youtube(episode_title, show_name, target_duration)
        # Only add YouTube results with decent match scores
        good_youtube = [r for r in youtube_results if r.get('match_score', 0) >= 1]
        sources.extend(good_youtube[:10])

    if not sources:
        print("[-] No alternative sources found")
        print("\nSuggestions:")
        print("  1. Try specifying the show name with --show 'Show Name'")
        print("  2. Try a different search term or episode")
        print("  3. Use Spotify desktop app to access transcript")
        sys.exit(1)

    # Mark sources that match duration
    matching_sources = []
    non_matching_sources = []

    for source in sources:
        source_duration = source.get('duration_seconds', 0)
        is_match = duration_matches(source_duration, target_duration, args.tolerance)
        source['duration_match'] = is_match

        if is_match:
            matching_sources.append(source)
        else:
            non_matching_sources.append(source)

    # Sort: matching sources first, then by match_score
    sources = matching_sources + non_matching_sources

    print(f"\n[+] Found {len(sources)} potential source(s):\n")
    print(f"    Target duration: {format_duration(target_duration)}")
    print(f"    Tolerance: ±{args.tolerance} seconds\n")

    for i, source in enumerate(sources, 1):
        platform = source.get('platform', 'unknown')
        title = source.get('title', 'Unknown')
        show = source.get('show', '')
        duration = source.get('duration', 'Unknown')
        duration_secs = source.get('duration_seconds', 0)

        if source.get('duration_match'):
            match_tag = " ✓ MATCH"
        elif duration_secs > 0 and target_duration > 0:
            diff = abs(duration_secs - target_duration)
            match_tag = f" (off by {format_duration(diff)})"
        else:
            match_tag = ""

        direct_tag = " [DIRECT AUDIO]" if source.get('direct_audio') else ""

        print(f"  {i}. [{platform}] {title}")
        if show:
            print(f"     Show: {show}")
        print(f"     Duration: {duration}{match_tag}{direct_tag}")
        print(f"     URL: {source['url']}\n")

    if args.list_sources:
        sys.exit(0)

    # Select source
    if args.interactive:
        download_source = interactive_select(sources)
        if not download_source:
            print("Cancelled.")
            sys.exit(0)
    else:
        # Auto-select: prefer matching duration + direct audio
        download_source = None

        # Priority 1: Fyyd with direct audio and matching duration (best free source)
        for source in sources:
            if source.get('duration_match') and source.get('platform') == 'fyyd':
                if source.get('direct_audio'):
                    download_source = source
                    break

        # Priority 2: Any source with matching duration and direct audio
        if not download_source:
            for source in sources:
                if source.get('duration_match') and source.get('direct_audio'):
                    download_source = source
                    break

        # Priority 3: Any source with matching duration
        if not download_source:
            for source in sources:
                if source.get('duration_match'):
                    download_source = source
                    break

        # Priority 4: Any source with direct audio AND matching duration
        if not download_source:
            for source in sources:
                if source.get('direct_audio') and source.get('duration_match'):
                    download_source = source
                    break

        # DO NOT auto-download if no duration match found
        # This prevents downloading a 5-minute clip when expecting a 50-minute podcast
        if not download_source:
            print("\n[!] ERROR: No source found with matching duration!")
            print(f"    Target duration: {format_duration(target_duration)} (±{args.tolerance}s tolerance)")
            print("\n    Available sources have mismatched durations:")
            for source in sources[:5]:
                dur_secs = source.get('duration_seconds', 0)
                if dur_secs > 0:
                    diff = abs(dur_secs - target_duration)
                    print(f"      - [{source['platform']}] {source.get('duration', 'Unknown')} (off by {format_duration(diff)})")
            print("\n    Options:")
            print("      1. Use -i/--interactive to manually select a source")
            print("      2. Use --tolerance N to increase tolerance (in seconds)")
            print("      3. Try --list-sources to see all available options")
            sys.exit(1)

    # Prepare output name
    output_name = args.output or episode_title or 'podcast_episode'
    output_name = re.sub(r'[^\w\s-]', '', output_name).strip().replace(' ', '_')

    print(f"\n[*] Selected: [{download_source['platform']}] {download_source['title']}")
    print(f"[*] Duration: {download_source.get('duration', 'Unknown')}")
    print(f"[*] Output: {output_name}")

    # Download
    url_to_download = download_source['url']

    # Check if direct audio URL (from Apple Podcasts)
    is_direct_audio = (
        download_source.get('direct_audio') or
        any(ext in url_to_download.lower() for ext in ['.mp3', '.m4a', '.mp4', '.aac', '.ogg'])
    )

    if download_source['platform'] == 'raiplaysound':
        # RaiPlaySound needs special handling to extract audio URL
        success = download_raiplaysound(url_to_download, output_name)
    elif download_source['platform'] == 'youtube':
        # YouTube - use pytube (only platform that uses pytube)
        if args.with_video:
            success = download_video_with_subs(url_to_download, output_name)
        else:
            success = download_with_pytube(url_to_download, output_name)
    elif is_direct_audio:
        # Direct audio URL (e.g., from Fyyd)
        success = download_direct_audio(url_to_download, output_name)
    else:
        # For other platforms (PodBean, Player FM, Podchaser, etc.)
        # Try to extract audio URL from the page
        success = extract_audio_from_page(url_to_download, output_name)

    if not success:
        print("[-] Download failed")
        sys.exit(1)

    print("[+] Download complete!")


if __name__ == '__main__':
    main()
