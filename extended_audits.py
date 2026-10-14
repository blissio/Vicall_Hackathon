"""Bounded link checks and optional Google PageSpeed/Lighthouse reports."""
import hashlib
import json
import os
import threading
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from storage import load_document, save_document, stamp
from website_audit import PageParser, clean_url, origin, public_address


def report_path(workspace, kind, identity):
    directory = workspace.directory / kind
    directory.mkdir(exist_ok=True)
    return directory / (hashlib.sha256(identity.encode()).hexdigest()+'.json')


def get_report(workspace, kind, identity):
    if identity not in workspace.by_id:
        raise KeyError('Business not found')
    result = load_document(report_path(workspace, kind, identity), {'status': 'not_run', 'message': 'No report yet'})
    if result.get('status') == 'running' and getattr(workspace, 'extra_active', None) != (kind, identity):
        result = {**result, 'status': 'interrupted', 'message': 'Previous check interrupted; start a new check'}
    return result


def start_report(workspace, payload, kind):
    identity = payload.get('id')
    if not isinstance(identity, str) or identity not in workspace.by_id:
        raise KeyError('Business not found')
    url = clean_url(payload.get('url', ''))
    strategy = payload.get('strategy', 'mobile')
    if strategy not in {'mobile', 'desktop'}:
        raise ValueError('Choose mobile or desktop')
    with workspace.lock:
        if getattr(workspace, 'extra_active', None) or getattr(workspace, 'rendered_running', False) or workspace.audit_job['status'] == 'running' or workspace.research_job['status'] == 'running':
            raise ValueError('Wait for the current website research or audit to finish')
        previous = get_report(workspace, kind, identity)
        workspace.extra_active = (kind, identity)
        running = {'business_id': identity, 'status': 'running', 'requested_url': url, 'strategy': strategy, 'checked_at': stamp(),
                   'message': 'Checking sampled links' if kind == 'links' else 'Requesting Google PageSpeed Insights'}
        save_document(report_path(workspace, kind, identity), running)

    def work():
        try:
            result = audit_links(url) if kind == 'links' else audit_crux(url, strategy) if kind == 'field' else audit_performance(url, strategy)
        except Exception as exc:
            result = {'status': 'inconclusive', 'requested_url': url, 'checked_at': stamp(), 'message': str(exc)[:300]}
        with workspace.lock:
            result['business_id'] = identity
            if previous.get('status') not in {'not_run', 'running'}:
                result['history'] = [{k:v for k,v in previous.items() if k != 'history'}, *previous.get('history', [])][:4]
            try:
                save_document(report_path(workspace, kind, identity), result)
            finally:
                workspace.extra_active = None
    threading.Thread(target=work, daemon=True).start()
    return running


def load_reports(directory, identities):
    from storage import connect
    names = {hashlib.sha256(identity.encode()).hexdigest()+'.json': identity for identity in identities}
    result = {identity: {} for identity in identities}
    for kind in ('links', 'performance', 'field'):
        folder = directory / kind
        if not (folder / 'workspace.sqlite3').exists():
            continue
        with connect(folder) as db:
            rows = db.execute('SELECT name,body FROM documents') if len(names) > 500 else db.execute('SELECT name,body FROM documents WHERE name IN ('+','.join('?' for _ in names)+')', tuple(names)) if names else []
            for name,body in rows:
                if name in names:
                    result[names[name]][kind] = json.loads(body)
    return result


def audit_links(url, crawler=None):
    from business_research import ResearchCrawler
    crawler = crawler or ResearchCrawler()
    crawler.fetcher.reset_budget()
    page = crawler.page(clean_url(url))
    if not 200 <= page['status'] < 300 or 'html' not in page['headers'].get('content-type', '').lower() or page['truncated']:
        raise ValueError('The source page was blocked, incomplete, or not readable HTML')
    parser = PageParser()
    parser.feed(page['text'])
    targets = []
    for href in parser.links:
        try:
            target = clean_url(urljoin(page['url'], href))
        except ValueError:
            continue
        if origin(target) == origin(page['url']) and target != page['url'] and target not in targets:
            targets.append(target)
    checked = stamp()
    result = {'status': 'complete', 'requested_url': url, 'source_url': page['url'], 'checked_at': checked, 'links': [],
              'total_internal_links_found': len(targets), 'sample_limit': 10, 'message': 'Static sample of up to ten same-origin links. A temporary error is not proof of a broken link or closed business.'}
    def guard(target):
        if origin(target) != origin(page['url']):
            raise ValueError('Link redirected outside the sampled site')
        crawler.guard(target)
    for target in targets[:10]:
        item = {'url': target, 'source_url': page['url'], 'observed_at': checked}
        try:
            response = crawler.fetcher.get(target, limit=8192, before_request=guard)
            status = response['status']
            item.update(http_status=status, outcome='missing' if status in {404, 410} else 'response_observed' if 200 <= status < 300 else 'inconclusive')
        except Exception as exc:
            item.update(outcome='inconclusive', message=str(exc)[:160])
        result['links'].append(item)
    result['missing_count'] = sum(link['outcome'] == 'missing' for link in result['links'])
    return result


def parse_performance(value, url, strategy):
    lighthouse = value.get('lighthouseResult', {})
    if not lighthouse or lighthouse.get('runtimeError'):
        raise ValueError('PageSpeed did not return a completed Lighthouse audit')
    categories = {}
    for key, item in lighthouse.get('categories', {}).items():
        score = item.get('score')
        categories[key] = round(score*100) if type(score) in {float, int} and 0 <= score <= 1 else None
    audits = lighthouse.get('audits', {})
    metrics = []
    for key in ('first-contentful-paint', 'largest-contentful-paint', 'total-blocking-time', 'cumulative-layout-shift', 'speed-index'):
        audit = audits.get(key, {})
        if audit:
            metrics.append({'id': key, 'title': audit.get('title', key), 'display_value': audit.get('displayValue'),
                            'numeric_value': audit.get('numericValue'), 'unit': audit.get('numericUnit')})
    findings = [{'id': key, 'title': audit.get('title'), 'description': audit.get('description', '')[:2000], 'display_value': audit.get('displayValue'), 'score': audit.get('score')}
                for key,audit in audits.items() if type(audit.get('score')) in {int,float} and audit['score'] < 1 and audit.get('scoreDisplayMode') != 'notApplicable'][:30]
    field = {scope: value[key] for scope,key in (('page', 'loadingExperience'), ('origin', 'originLoadingExperience'))
             if isinstance(value.get(key), dict) and value[key].get('metrics')}
    return {'status': 'complete', 'requested_url': url, 'final_url': lighthouse.get('finalUrl'), 'strategy': strategy,
            'checked_at': stamp(), 'provider': 'Google PageSpeed Insights', 'lighthouse_version': lighthouse.get('lighthouseVersion'),
            'categories': categories, 'lab_metrics': metrics, 'field_data': field, 'findings': findings,
            'report_url': 'https://pagespeed.web.dev/analysis?'+urlencode({'url': url, 'form_factor': strategy}),
            'message': 'Lighthouse scores and lab measurements are a sampled test. Real-user field data is shown separately when returned by Google; scores do not measure search rankings.'}


def audit_performance(url, strategy='mobile'):
    url = clean_url(url)
    parts = urlsplit(url)
    public_address(parts.hostname, 443 if parts.scheme == 'https' else 80)
    params = {'url': url, 'strategy': strategy, 'category': ['performance', 'accessibility', 'best-practices', 'seo']}
    api_key = os.getenv('PAGESPEED_API_KEY')
    if api_key:
        params['key'] = api_key
    request = Request('https://www.googleapis.com/pagespeedonline/v5/runPagespeed?'+urlencode(params, doseq=True), headers={'User-Agent': 'PittsburghIQ/2.1'})
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError('PageSpeed response exceeded the size limit')
            value = json.loads(raw)
    except HTTPError as exc:
        raise ValueError(f'PageSpeed returned HTTP {exc.code}. Check API access/quota or configure PAGESPEED_API_KEY; no performance conclusion was saved.') from None
    except (URLError, TimeoutError):
        raise ValueError('PageSpeed could not be reached. Retry later; the website status remains unknown.') from None
    return parse_performance(value, url, strategy)


def audit_crux(url, strategy='mobile'):
    url = clean_url(url)
    parts = urlsplit(url)
    public_address(parts.hostname, 443 if parts.scheme == 'https' else 80)
    key = os.getenv('CRUX_API_KEY') or os.getenv('PAGESPEED_API_KEY')
    if not key:
        raise ValueError('Configure CRUX_API_KEY with Chrome UX Report API access to fetch real-user metrics')
    request = Request('https://chromeuxreport.googleapis.com/v1/records:queryRecord?'+urlencode({'key': key}),
        data=json.dumps({'url': url, 'formFactor': 'PHONE' if strategy == 'mobile' else 'DESKTOP'}).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('Field-data response exceeded the size limit')
            value = json.loads(raw)
    except HTTPError as exc:
        raise ValueError('No URL-level real-user sample was found' if exc.code == 404 else f'CrUX returned HTTP {exc.code}; check API access and quota') from None
    except (URLError, TimeoutError):
        raise ValueError('Real-user metrics could not be fetched; no performance conclusion inferred') from None
    record = value.get('record', {})
    if not record.get('metrics'):
        raise ValueError('CrUX returned no metrics for this URL and device')
    return {'status': 'complete', 'requested_url': url, 'strategy': strategy, 'checked_at': stamp(), 'provider': 'Chrome UX Report API',
            'field_metrics': record['metrics'], 'collection_period': record.get('collectionPeriod'), 'record_key': record.get('key'),
            'message': 'Real-user aggregate metrics for the returned URL/device sample. Percentiles and collection period differ from a Lighthouse lab test.'}
