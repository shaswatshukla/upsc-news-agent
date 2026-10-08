"""Credential-free checks for the daily Indian Express agent."""
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import agent

now = datetime.now(ZoneInfo('Asia/Kolkata'))
yesterday = (now - timedelta(hours=20)).strftime('%a, %d %b %Y %H:%M:%S %z')
old = (now - timedelta(hours=80)).strftime('%a, %d %b %Y %H:%M:%S %z')
xml = f'''<rss><channel>
<item><title>Current &amp; policy</title><link>https://indianexpress.com/article/india/policy-123/?utm_source=test</link><pubDate>{yesterday}</pubDate></item>
<item><title>Old</title><link>https://indianexpress.com/article/india/old-234/</link><pubDate>{old}</pubDate></item>
<item><title>No numeric ID</title><link>https://indianexpress.com/article/india/policy/</link></item>
<item><title>Other host</title><link>https://example.org/article/india/test/</link></item>
</channel></rss>'''
records = agent.parse_feed('India', xml.encode(), now)
assert len(records) == 2
assert records[0]['prid'] == '123'
assert '?' not in records[0]['link']
assert records[1]['prid'].startswith('https://indianexpress.com/')
assert records[0]['title'] == 'Current & policy'

news_response = type('NewsResponse', (), {'raise_for_status': lambda self: None})()
news_response.content = f'''<rss><channel>
<item><title>Policy update - The Indian Express</title><link>https://news.google.com/rss/articles/example</link><source url="https://indianexpress.com">The Indian Express</source><pubDate>{yesterday}</pubDate></item>
<item><title>Other publisher</title><link>https://news.google.com/rss/articles/other</link><source url="https://example.org">Other</source><pubDate>{yesterday}</pubDate></item>
</channel></rss>'''.encode()
with patch.object(agent.requests, 'get', return_value=news_response):
    fallback = agent.fetch_google_news_items(now)
assert len(fallback) == 1 and fallback[0]['title'] == 'Policy update'
assert 'SOURCE LIMITATION:' in fallback[0]['preview_text']
assert fallback[0]['link'].startswith('https://news.google.com/')

class Response:
    content = b''
    def raise_for_status(self): pass

response = Response()
response.content = b'<script type="application/ld+json">{"isAccessibleForFree":false}</script><div class="full-details"><p>hidden text</p></div>'
with patch.object(agent.requests, 'get', return_value=response):
    try:
        agent.fetch_article_text('https://indianexpress.com/article/india/policy-123/')
        raise AssertionError('Premium content was not skipped')
    except agent.ArticleUnavailable:
        pass

response.content = ('<div class="full-details"><p>' + 'Public article fact. ' * 120 + '</p></div>').encode()
with patch.object(agent.requests, 'get', return_value=response):
    assert len(agent.fetch_article_text('https://indianexpress.com/article/india/policy-123/')) > 400

with tempfile.TemporaryDirectory() as directory:
    agent.SEEN_PRIDS_PATH = Path(directory) / 'seen.json'
    agent.save_seen_prids([str(i) for i in range(600)])
    seen = agent.load_seen_prids()
    assert seen[0] == '100' and seen[-1] == '599' and len(seen) == 500
    report = {'overview': 'Environment & governance.', 'items': [{'title': 'Policy update', 'gs_papers': ['GS2', 'GS3'], 'topic': 'Governance', 'summary': 'Public factual overview.', 'prelims_facts': [], 'mains_angle': 'Consider implementation.', 'source_url': records[0]['link']}]}
    path = Path(directory) / 'check.pdf'
    agent.build_pdf(report, '09 October 2026', path)
    assert path.read_bytes().startswith(b'%PDF-')

with patch.object(agent, 'load_config', return_value={'MAX_RELEASES': 25}), patch.object(agent, 'fetch_rss_items', return_value=[]), patch.object(agent, 'load_seen_prids', return_value=[]), patch.object(agent, 'send_email') as email:
    try: agent.main()
    except SystemExit as result: assert result.code == 0
    email.assert_not_called()

with patch.object(agent, 'load_config', return_value={'MAX_RELEASES': 25}), patch.object(agent, 'fetch_rss_items', return_value=records[:1]), patch.object(agent, 'load_seen_prids', return_value=[]), patch.object(agent, 'fetch_article_text', return_value='Public facts'), patch.object(agent, 'call_gemini', return_value={'overview': '', 'items': []}), patch.object(agent, 'save_seen_prids') as save, patch.object(agent, 'send_email') as email:
    try: agent.main()
    except SystemExit as result: assert result.code == 0
    save.assert_called_once_with(['123', agent.headline_id(records[0]['title'])])
    email.assert_not_called()

print('PASS: recent article dates, URL deduplication, missing ID, premium skip, public body, history retention, PDF, and both empty outcomes')

