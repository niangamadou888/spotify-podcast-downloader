"""YouTube search without API keys (podcast_alt_source.py).

In November 2026 every YouTube Data API key answered HTTP 429, so the YouTube
step found nothing and Spotify-only shows failed ("none of the 10 alternative
sources is this episode") although the episode was on YouTube. The search now
falls back to youtube.com's results page, which lists each video's length.

Run: python3 -m unittest discover tests
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import podcast_alt_source as p  # noqa: E402


def results_page(videos):
    """A results page shaped like youtube.com's: ytInitialData holding videoRenderer entries."""
    items = []
    for v in videos:
        renderer = {'videoId': v['id'], 'title': {'runs': [{'text': v['title']}]},
                    'ownerText': {'runs': [{'text': v['channel']}]}}
        if v.get('length'):
            renderer['lengthText'] = {'simpleText': v['length']}
        items.append({'videoRenderer': renderer})
    data = {'contents': {'twoColumnSearchResultsRenderer': {'primaryContents': {
        'sectionListRenderer': {'contents': [{'itemSectionRenderer': {'contents': items}}]}}}}}
    return f'<html><script>var ytInitialData = {json.dumps(data)};</script></html>'


EPISODE = {'id': 'aiHLXzeWY0M', 'title': 'Ep 6: The "Post Anxiety" of Social Anxiety',
           'channel': 'Socially Blurred', 'length': '19:27'}


class ParseResultsPage(unittest.TestCase):
    def test_reads_id_title_channel_and_length_in_page_order(self):
        page = results_page([EPISODE, {'id': 'x2', 'title': 'Long one', 'channel': 'C', 'length': '1:02:03'}])
        self.assertEqual(p.parse_youtube_search_html(page), [
            {'videoId': 'aiHLXzeWY0M', 'title': 'Ep 6: The "Post Anxiety" of Social Anxiety',
             'channel': 'Socially Blurred', 'duration_seconds': 1167},
            {'videoId': 'x2', 'title': 'Long one', 'channel': 'C', 'duration_seconds': 3723},
        ])

    def test_leaves_out_results_without_a_length_and_repeats(self):
        page = results_page([{'id': 'live', 'title': 'Live now', 'channel': 'C'}, EPISODE, EPISODE])
        self.assertEqual([v['videoId'] for v in p.parse_youtube_search_html(page)], ['aiHLXzeWY0M'])

    def test_a_page_without_results_data_is_no_results(self):
        self.assertEqual(p.parse_youtube_search_html('<html>consent</html>'), [])
        self.assertEqual(p.parse_youtube_search_html('var ytInitialData = {broken;</script>'), [])
        self.assertEqual(p.parse_youtube_search_html(None), [])


class SearchFallsBackToResultsPage(unittest.TestCase):
    def test_spent_api_keys_fall_back_to_the_results_page(self):
        web = [{'videoId': 'aiHLXzeWY0M', 'title': EPISODE['title'], 'channel': 'Socially Blurred', 'duration_seconds': 1167}]
        with mock.patch.object(p, 'YOUTUBE_API_KEYS', ['k1']), \
             mock.patch.object(p, 'youtube_data_search', return_value=[]), \
             mock.patch.object(p, 'youtube_web_search', return_value=web) as web_search, \
             mock.patch('builtins.print'):
            found = p.search_youtube('The "Post Anxiety" of Social Anxiety', 'Socially Blurred', 1166)
        web_search.assert_called_once()
        self.assertEqual(found[0]['url'], 'https://www.youtube.com/watch?v=aiHLXzeWY0M')
        self.assertEqual(found[0]['duration_seconds'], 1167)
        self.assertEqual(found[0]['show'], 'Socially Blurred')

    def test_api_hits_without_lengths_also_fall_back(self):
        api = [{'videoId': 'aiHLXzeWY0M', 'title': EPISODE['title'], 'channel': 'Socially Blurred', 'description': ''}]
        web = [{'videoId': 'aiHLXzeWY0M', 'title': EPISODE['title'], 'channel': 'Socially Blurred', 'duration_seconds': 1167}]
        with mock.patch.object(p, 'YOUTUBE_API_KEYS', ['k1']), \
             mock.patch.object(p, 'youtube_data_search', return_value=api), \
             mock.patch.object(p, 'youtube_data_video_durations', return_value={}), \
             mock.patch.object(p, 'youtube_web_search', return_value=web), \
             mock.patch('builtins.print'):
            found = p.search_youtube('The "Post Anxiety" of Social Anxiety', 'Socially Blurred', 1166)
        self.assertEqual(found[0]['duration_seconds'], 1167)

    def test_working_api_keys_are_used_and_the_page_is_not_read(self):
        api = [{'videoId': 'aiHLXzeWY0M', 'title': EPISODE['title'], 'channel': 'Socially Blurred', 'description': ''}]
        with mock.patch.object(p, 'YOUTUBE_API_KEYS', ['k1']), \
             mock.patch.object(p, 'youtube_data_search', return_value=api), \
             mock.patch.object(p, 'youtube_data_video_durations', return_value={'aiHLXzeWY0M': 1167}), \
             mock.patch.object(p, 'youtube_web_search') as web_search, \
             mock.patch('builtins.print'):
            found = p.search_youtube('The "Post Anxiety" of Social Anxiety', 'Socially Blurred', 1166)
        web_search.assert_not_called()
        self.assertEqual(found[0]['duration_seconds'], 1167)



class YtDlpSearch(unittest.TestCase):
    """yt-dlp's YouTube search: the second fallback when the results page gives
    nothing (an error, or a page whose layout changed)."""

    def run_result(self, stdout, returncode=0):
        return mock.Mock(stdout=stdout, stderr='', returncode=returncode)

    def test_reads_id_length_channel_and_title(self):
        out = ('aiHLXzeWY0M\t1167\tSocially Blurred\tEp 6: The "Post Anxiety" of Social Anxiety\n'
               'NA_ID\tNA\tSomeone\tA live stream\n'
               'x2\t3723.0\tC\tTitle\twith a tab\n')
        with mock.patch.object(p.subprocess, 'run', return_value=self.run_result(out)) as run, \
             mock.patch('builtins.print'):
            videos = p.youtube_ytdlp_search('Socially Blurred podcast', max_results=5)
        self.assertEqual(videos, [
            {'videoId': 'aiHLXzeWY0M', 'title': 'Ep 6: The "Post Anxiety" of Social Anxiety',
             'channel': 'Socially Blurred', 'duration_seconds': 1167},
            {'videoId': 'x2', 'title': 'Title\twith a tab', 'channel': 'C', 'duration_seconds': 3723},
        ])
        args = run.call_args.args[0]
        self.assertEqual(args[0], 'yt-dlp')
        self.assertEqual(args[-1], 'ytsearch5:Socially Blurred podcast', 'the query is one argument, no shell')

    def test_a_missing_or_failing_yt_dlp_is_no_results(self):
        with mock.patch.object(p.subprocess, 'run', side_effect=FileNotFoundError('yt-dlp')), mock.patch('builtins.print'):
            self.assertEqual(p.youtube_ytdlp_search('q'), [])
        with mock.patch.object(p.subprocess, 'run', side_effect=p.subprocess.TimeoutExpired('yt-dlp', 90)), \
             mock.patch('builtins.print'):
            self.assertEqual(p.youtube_ytdlp_search('q'), [])

    def test_used_only_when_the_results_page_gives_nothing(self):
        found = [{'videoId': 'aiHLXzeWY0M', 'title': EPISODE['title'], 'channel': 'Socially Blurred', 'duration_seconds': 1167}]
        with mock.patch.object(p, 'YOUTUBE_API_KEYS', []), \
             mock.patch.object(p, 'youtube_web_search', return_value=[]), \
             mock.patch.object(p, 'youtube_ytdlp_search', return_value=found) as ytdlp, \
             mock.patch('builtins.print'):
            results = p.search_youtube('The "Post Anxiety" of Social Anxiety', 'Socially Blurred', 1166)
        ytdlp.assert_called_once()
        self.assertEqual(results[0]['duration_seconds'], 1167)
        with mock.patch.object(p, 'YOUTUBE_API_KEYS', []), \
             mock.patch.object(p, 'youtube_web_search', return_value=found), \
             mock.patch.object(p, 'youtube_ytdlp_search') as ytdlp, \
             mock.patch('builtins.print'):
            p.search_youtube('The "Post Anxiety" of Social Anxiety', 'Socially Blurred', 1166)
        ytdlp.assert_not_called()

if __name__ == '__main__':
    unittest.main()
