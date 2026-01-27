/**
 * Spotify Podcast Downloader - Node.js Module
 *
 * Downloads podcast episodes by searching iTunes for RSS feeds
 * and using podcast-dl to download the audio file.
 *
 * Usage:
 *   import { downloadSpotifyEpisode, searchItunesRss } from './spotifyDownloader.js';
 *   const result = await downloadSpotifyEpisode(spotifyUrl, outputDir);
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import fetch from 'node-fetch';
import fs from 'fs';
import path from 'path';

const execAsync = promisify(exec);

/**
 * Get episode/show title from Spotify oEmbed API
 * @param {string} spotifyUrl - Spotify episode or show URL
 * @returns {Promise<{title: string, type: 'episode'|'show'}|null>}
 */
export async function getSpotifyInfo(spotifyUrl) {
    try {
        const response = await fetch(`https://open.spotify.com/oembed?url=${encodeURIComponent(spotifyUrl)}`);
        if (!response.ok) {
            console.error(`Spotify oEmbed failed: ${response.status}`);
            return null;
        }
        const data = await response.json();
        const type = spotifyUrl.includes('/episode/') ? 'episode' : 'show';
        return {
            title: data.title || null,
            type
        };
    } catch (error) {
        console.error('Error fetching Spotify info:', error.message);
        return null;
    }
}

/**
 * Search iTunes for podcast RSS feed
 * @param {string} query - Search query (podcast/episode title)
 * @param {string} entity - 'podcast' or 'podcastEpisode'
 * @returns {Promise<{feedUrl: string, collectionName: string}|null>}
 */
export async function searchItunesRss(query, entity = 'podcastEpisode') {
    try {
        const encodedQuery = encodeURIComponent(query);
        const url = `https://itunes.apple.com/search?term=${encodedQuery}&media=podcast&entity=${entity}&limit=10`;

        const response = await fetch(url);
        if (!response.ok) {
            console.error(`iTunes search failed: ${response.status}`);
            return null;
        }

        const data = await response.json();
        const results = data.results || [];

        if (results.length === 0) {
            return null;
        }

        // Deduplicate by feedUrl and return the first match
        const seen = new Set();
        for (const result of results) {
            const feedUrl = result.feedUrl;
            if (feedUrl && !seen.has(feedUrl)) {
                return {
                    feedUrl,
                    collectionName: result.collectionName || result.trackName || 'Unknown'
                };
            }
            seen.add(feedUrl);
        }

        return null;
    } catch (error) {
        console.error('Error searching iTunes:', error.message);
        return null;
    }
}

/**
 * Download episode from RSS feed using podcast-dl
 * @param {string} rssUrl - RSS feed URL
 * @param {string} outputDir - Directory to save the downloaded file
 * @param {string|null} episodeFilter - Regex pattern to filter specific episode
 * @returns {Promise<{success: boolean, filePath?: string, error?: string}>}
 */
export async function downloadFromRss(rssUrl, outputDir, episodeFilter = null) {
    try {
        // Ensure output directory exists
        if (!fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir, { recursive: true });
        }

        // Build podcast-dl command
        let command = `npx podcast-dl --url "${rssUrl}" --out-dir "${outputDir}" --episode-template "{{episode_title}}"`;

        if (episodeFilter) {
            // Escape special characters for shell
            const escapedFilter = episodeFilter.replace(/"/g, '\\"');
            command += ` --episode-regex "${escapedFilter}"`;
        }

        console.log(`[SpotifyDownloader] Running: ${command}`);

        const { stdout, stderr } = await execAsync(command, {
            timeout: 600000, // 10 minutes timeout
            maxBuffer: 50 * 1024 * 1024 // 50MB buffer
        });

        if (stderr && !stderr.includes('npm warn')) {
            console.log(`[SpotifyDownloader] stderr: ${stderr}`);
        }

        // Find the downloaded file(s)
        const files = fs.readdirSync(outputDir).filter(f =>
            f.endsWith('.mp3') || f.endsWith('.m4a') || f.endsWith('.wav')
        );

        if (files.length === 0) {
            return { success: false, error: 'No audio files downloaded' };
        }

        // Return the most recently modified file
        const filesWithStats = files.map(f => ({
            name: f,
            path: path.join(outputDir, f),
            mtime: fs.statSync(path.join(outputDir, f)).mtime
        }));

        filesWithStats.sort((a, b) => b.mtime - a.mtime);

        return {
            success: true,
            filePath: filesWithStats[0].path,
            fileName: filesWithStats[0].name
        };
    } catch (error) {
        console.error('[SpotifyDownloader] Download error:', error.message);
        return { success: false, error: error.message };
    }
}

/**
 * Download a podcast episode from Spotify URL
 * Uses iTunes to find RSS feed, then podcast-dl to download
 *
 * @param {string} spotifyUrl - Spotify episode or show URL
 * @param {string} outputDir - Directory to save the downloaded file
 * @returns {Promise<{success: boolean, filePath?: string, title?: string, error?: string}>}
 */
export async function downloadSpotifyEpisode(spotifyUrl, outputDir) {
    console.log(`[SpotifyDownloader] Starting download for: ${spotifyUrl}`);

    // Step 1: Get title from Spotify
    const spotifyInfo = await getSpotifyInfo(spotifyUrl);
    if (!spotifyInfo || !spotifyInfo.title) {
        return { success: false, error: 'Could not fetch podcast info from Spotify' };
    }

    console.log(`[SpotifyDownloader] Found title: ${spotifyInfo.title}`);

    // Step 2: Determine entity type and episode filter
    const entity = spotifyInfo.type === 'episode' ? 'podcastEpisode' : 'podcast';
    let episodeFilter = null;

    if (spotifyInfo.type === 'episode') {
        // Create exact match regex filter from episode title
        // Escape special regex characters
        episodeFilter = spotifyInfo.title.replace(/[[\].*^$()+?{|\\]/g, '\\$&');
    }

    // Step 3: Search iTunes for RSS feed
    const itunesResult = await searchItunesRss(spotifyInfo.title, entity);
    if (!itunesResult || !itunesResult.feedUrl) {
        return { success: false, error: 'Could not find RSS feed in iTunes' };
    }

    console.log(`[SpotifyDownloader] Found RSS feed: ${itunesResult.feedUrl}`);
    console.log(`[SpotifyDownloader] Podcast: ${itunesResult.collectionName}`);

    // Step 4: Download from RSS feed (try exact match first)
    let downloadResult = await downloadFromRss(itunesResult.feedUrl, outputDir, episodeFilter);

    // Step 5: If exact match failed and this is an episode, try partial name matching
    if (!downloadResult.success && spotifyInfo.type === 'episode') {
        console.log(`[SpotifyDownloader] Exact match failed, trying partial name matching...`);

        const words = spotifyInfo.title
            .split(/[\s\-:,]+/)  // Split on common separators
            .filter(word => word.length > 2)  // Skip very short words
            .map(word => word.replace(/[[\].*^$()+?{|\\]/g, '\\$&'));  // Escape regex chars

        if (words.length > 0) {
            const partialFilter = `.*${words.join('.*')}.*`;
            downloadResult = await downloadFromRss(itunesResult.feedUrl, outputDir, partialFilter);
        }
    }

    if (!downloadResult.success) {
        return downloadResult;
    }

    return {
        success: true,
        filePath: downloadResult.filePath,
        fileName: downloadResult.fileName,
        title: spotifyInfo.title,
        podcastName: itunesResult.collectionName,
        rssUrl: itunesResult.feedUrl
    };
}

/**
 * Clean up downloaded audio file
 * @param {string} filePath - Path to the file to delete
 * @returns {Promise<boolean>}
 */
export async function cleanupAudioFile(filePath) {
    try {
        if (filePath && fs.existsSync(filePath)) {
            fs.unlinkSync(filePath);
            console.log(`[SpotifyDownloader] Cleaned up: ${filePath}`);
            return true;
        }
        return false;
    } catch (error) {
        console.error(`[SpotifyDownloader] Cleanup error: ${error.message}`);
        return false;
    }
}

/**
 * Clean up entire download directory
 * @param {string} dirPath - Directory path to clean
 * @returns {Promise<boolean>}
 */
export async function cleanupDownloadDir(dirPath) {
    try {
        if (dirPath && fs.existsSync(dirPath)) {
            fs.rmSync(dirPath, { recursive: true, force: true });
            console.log(`[SpotifyDownloader] Cleaned up directory: ${dirPath}`);
            return true;
        }
        return false;
    } catch (error) {
        console.error(`[SpotifyDownloader] Directory cleanup error: ${error.message}`);
        return false;
    }
}
