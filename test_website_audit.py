import socket
import unittest
from unittest.mock import patch

from website_audit import (PageParser, PublicFetcher, RestrictedTarget, audit_website,
                           clean_url, inspect_page, public_address, robots_policy)


GOOD_HTML = '''<!doctype html><html><head><title>Test Cafe | Pittsburgh</title>
<meta name="description" content="A neighborhood cafe in Pittsburgh.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://example.com/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"CafeOrCoffeeShop","name":"Test Cafe"}</script>
</head><body><h1>Welcome to Test Cafe</h1><p>Enjoy freshly roasted coffee and freshly baked goods every morning at our neighborhood cafe. Find our opening hours, menu, contact details and directions here.</p>
<a href="/menu">Menu</a><img src="coffee.jpg" alt="Coffee on a table"></body></html>'''


def response(url='https://example.com/', text=GOOD_HTML, status=200, content_type='text/html', headers=None, truncated=False):
    return {'url':url,'status':status,'text':text,'headers':{'content-type':content_type,**(headers or {})},
            'truncated':truncated,'bytes_read':len(text.encode()),'fetch_ms':100,'redirects':[]}


class FakeFetcher:
    def __init__(self, page=None, robots='', robots_status=200, exception=None):
        self.page = page or response()
        self.robots = robots
        self.robots_status = robots_status
        self.exception = exception
        self.delays = {}
        self.calls = []

    def get(self, url, limit=None, before_request=None):
        self.calls.append(url)
        if self.exception:
            raise self.exception
        if before_request:
            before_request(url)
        if url.endswith('/robots.txt'):
            return response(url,self.robots,self.robots_status,'text/plain')
        if url.endswith('/sitemap.xml'):
            return response(url,'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',200,'application/xml')
        return self.page


class AuditTests(unittest.TestCase):
    def test_basic_page_and_evidence(self):
        result = audit_website('example.com', FakeFetcher())
        self.assertEqual(result['reachability'],'reachable')
        self.assertEqual(result['score'],100)
        self.assertEqual(result['grade'],'strong')
        self.assertEqual(result['metrics']['structured_types'],['CafeOrCoffeeShop'])
        self.assertTrue(result['sitemap']['valid_xml'])
        self.assertTrue(all('evidence' in c and 'recommendation' in c for c in result['checks']))

    def test_missing_metadata_generates_actionable_findings(self):
        page = response(text='<html><body><p>A cafe with coffee, pastries, community events and a wide variety of sandwiches for our neighborhood customers.</p><img src="x.jpg"></body></html>')
        result = audit_website('https://example.com/', FakeFetcher(page))
        self.assertEqual(result['grade'],'needs_work')
        self.assertIn('description',[c['key'] for c in result['recommendations']])
        self.assertEqual(result['metrics']['missing_alt'],1)

    def test_noindex_caps_score_and_multiple_h1_not_penalized(self):
        page = response(text=GOOD_HTML.replace('<body>','<body><h1>Second heading</h1>'),headers={'x-robots-tag':'noindex'})
        result = audit_website('https://example.com/', FakeFetcher(page))
        self.assertLessEqual(result['score'],49)
        self.assertEqual(next(c for c in result['checks'] if c['key']=='h1')['status'],'pass')
        self.assertEqual(next(c for c in result['checks'] if c['key']=='indexing')['status'],'critical')

    def test_colon_directives_and_crawler_scoped_headers(self):
        html = GOOD_HTML.replace('</head>','<meta name="robots" content="max-snippet: 50, noindex"></head>')
        self.assertLessEqual(inspect_page(response(text=html),True)['score'],49)
        self.assertEqual(inspect_page(response(headers={'x-robots-tag':'otherbot: noindex'}),True)['score'],100)
        self.assertLessEqual(inspect_page(response(headers={'x-robots-tag':'otherbot: noindex\ngooglebot: noindex'}),True)['score'],49)
        self.assertLessEqual(inspect_page(response(headers={'x-robots-tag':'max-snippet: 50, noindex'}),True)['score'],49)

    def test_googlebot_restriction_is_distinct_from_auditor_access(self):
        result = audit_website('https://example.com/',FakeFetcher(robots='User-agent: Googlebot\nDisallow: /\nUser-agent: *\nAllow: /'))
        self.assertEqual(result['reachability'],'reachable')
        self.assertLessEqual(result['score'],49)
        self.assertFalse(result['robots']['googlebot_allowed'])

    def test_robots_disallow_stops_html_fetch_and_is_not_bad_seo(self):
        fetcher = FakeFetcher(robots='User-agent: *\nDisallow: /')
        result = audit_website('https://example.com/',fetcher)
        self.assertEqual(result['reachability'],'restricted')
        self.assertIsNone(result['score'])
        self.assertNotIn('https://example.com/sitemap.xml',fetcher.calls)

    def test_robots_unavailable_defers_analysis(self):
        result = audit_website('https://example.com/',FakeFetcher(robots_status=503))
        self.assertEqual(result['reachability'],'restricted')
        self.assertIsNone(result['http_status'])

    def test_missing_robots_is_not_an_seo_failure(self):
        result = audit_website('https://example.com/',FakeFetcher(robots_status=404))
        self.assertEqual(result['score'],100)

    def test_blocked_error_non_html_and_timeout_have_no_score(self):
        for page,status in [(response(status=403),'restricted'),(response(status=404),'http_error'),
                            (response(content_type='application/pdf'),'non_html'),
                            (response(text='<title>Wait</title>verify you are human'),'restricted')]:
            result = audit_website('https://example.com/',FakeFetcher(page))
            self.assertEqual(result['reachability'],status)
            self.assertIsNone(result['score'])
        result = audit_website('https://example.com/',FakeFetcher(exception=TimeoutError()))
        self.assertEqual(result['reachability'],'unknown')
        self.assertIsNone(result['score'])

    def test_truncated_and_javascript_shells_are_not_scored(self):
        for page in [response(truncated=True),response(text='<html><head><title>App</title></head><body><div id="root"></div><script src="app.js"></script></body></html>')]:
            result = audit_website('https://example.com/',FakeFetcher(page))
            self.assertIsNone(result['score'])
            self.assertEqual(result['grade'],'partial')

    def test_robots_longest_match_allow_and_specific_agent(self):
        rules='User-agent: *\nDisallow: /private/\nAllow: /private/public/\nDisallow: /*?secret=$\nCrawl-delay: 3\nUser-agent: VicallSiteAudit\nDisallow: /special/'
        self.assertTrue(robots_policy(rules,'Googlebot','https://example.com/private/public/')['allowed'])
        self.assertFalse(robots_policy(rules,'Googlebot','https://example.com/private/')['allowed'])
        self.assertFalse(robots_policy(rules,'VicallSiteAudit','https://example.com/special/')['allowed'])
        self.assertTrue(robots_policy(rules,'VicallSiteAudit','https://example.com/private/')['allowed'])
        self.assertEqual(robots_policy(rules,'Googlebot','https://example.com/')['crawl_delay'],3)

    def test_private_urls_and_credentials_are_rejected(self):
        for url in ['http://127.0.0.1/','http://169.254.169.254/','http://[::1]/','https://localhost/','https://x.local/',
                    'http://192.168.1.1/','https://user:secret@example.com/','https://example.com:8443/',
                    'file:///etc/passwd','javascript:alert(1)','https://bad host.com/']:
            with self.subTest(url=url), self.assertRaises(RestrictedTarget):
                clean_url(url)

    def test_dns_mixed_private_addresses_are_rejected(self):
        answers=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443)),
                 (socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('website_audit.socket.getaddrinfo',return_value=answers):
            with self.assertRaises(RestrictedTarget):
                public_address('example.com',443)

    def test_redirect_to_private_network_is_rejected(self):
        class Redirect:
            status=302
            def getheaders(self): return [('Location','http://169.254.169.254/')]
        class Connection:
            sock=None
            def __init__(self,*args): pass
            def request(self,*args,**kwargs): pass
            def getresponse(self): return Redirect()
            def close(self): pass
        with patch('website_audit.public_address',return_value='8.8.8.8'),patch('website_audit.PinnedHTTPS',Connection):
            with self.assertRaises(RestrictedTarget):
                PublicFetcher().get('https://example.com/')


if __name__=='__main__':
    unittest.main()
