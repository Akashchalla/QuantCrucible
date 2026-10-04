"""Check challenge API access without evaluating any strategy or touching test dates."""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
BASE = 'https://api.massive.com'
CACHE = ROOT / '.massive_cache' / 'preflight'


class CheckError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CheckError('Unexpected redirect; stopped before forwarding credentials.')


def read_key():
    key = os.environ.get('MASSIVE_API_KEY', '').strip()
    if not key and (ROOT / '.env').is_file():
        for line in (ROOT / '.env').read_text().splitlines():
            name, sep, value = line.strip().partition('=')
            if sep and name.strip() == 'MASSIVE_API_KEY':
                key = value.strip().strip('"\'')
                break
    if not key or key == 'your-key-here':
        raise CheckError('Key not configured. Put MASSIVE_API_KEY in the local .env file, then rerun.')
    return key


def safe_url(path, params=None):
    url = path if path.startswith('https://') else BASE + path
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'api.massive.com'
            or parsed.username or parsed.password or parsed.fragment):
        raise CheckError('Rejected an unexpected API destination.')
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() != 'apikey']
    query.extend((params or {}).items())
    return urlunparse(parsed._replace(query=urlencode(query)))


def get_json(path, key, params=None):
    url = safe_url(path, params)
    opener = build_opener(NoRedirect())
    for attempt in range(3):
        req = Request(url, headers={'Authorization': 'Bearer ' + key,
                                    'User-Agent': 'FilingEdge-GQH-Preflight/0.1'})
        try:
            with opener.open(req, timeout=15) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise CheckError('Unexpected response shape; inspect the endpoint schema.')
            if str(payload.get('status', '')).upper() in {'ERROR', 'NOT_AUTHORIZED'}:
                raise CheckError('API returned an error status; check challenge entitlements.')
            return payload
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            hint = {401: 'Key rejected.', 403: 'Endpoint or historical window is not entitled.',
                    429: 'Rate limit reached; retry later.'}.get(exc.code, 'Request failed.')
            raise CheckError(f'HTTP {exc.code}: {hint}') from None
        except (URLError, TimeoutError):
            raise CheckError('Network request failed or timed out. Check connectivity and network permissions.') from None
        except (ValueError, UnicodeError):
            raise CheckError('Response was not valid JSON.') from None
    raise CheckError('Request attempts exhausted.')


def save_private(name, payload, key):
    CACHE.mkdir(parents=True, exist_ok=True)
    # Remove any exact credential echo before writing a response to disk.
    (CACHE / name).write_text(json.dumps(payload, indent=2).replace(key, '[REDACTED]') + '\n')


def rows(payload):
    result = payload.get('results') or []
    if not isinstance(result, list):
        raise CheckError('Expected a list of result rows.')
    return result


def check_access(key):
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'purpose': 'Development-only access check; no performance results', 'checks': {}}
    try:
        taxonomy = []
        page = get_json('/stocks/taxonomies/vX/disclosures', key, {'limit': 1000})
        for page_number in range(10):
            taxonomy.extend(rows(page))
            if not page.get('next_url'):
                break
            if page_number == 9:
                raise CheckError('Taxonomy pagination limit reached; refusing a partial taxonomy.')
            page = get_json(page['next_url'], key)
        save_private('taxonomy.json', taxonomy, key)
        report['checks']['taxonomy_rows'] = len(taxonomy)
        print(f'Taxonomy accessible: {len(taxonomy)} rows.')
        candidates = sorted({str(r.get('tertiary_category', '')) for r in taxonomy
                             if any(s in json.dumps(r).lower() for s in ('repurchase', 'buyback'))})
        report['checks']['possible_buyback_tags'] = candidates
        print('Potential buyback tags saved in the private access report; definitions need review.')

        sample = get_json('/stocks/filings/8-K/vX/disclosures', key,
                          {'filing_date.gte': '2024-06-01', 'filing_date.lte': '2024-06-30',
                           'limit': 1, 'sort': 'filing_date.asc'})
        save_private('development_disclosure_sample.json', sample, key)
        report['checks']['development_disclosure_sample_rows'] = len(rows(sample))
        print(f'Development disclosures accessible: {len(rows(sample))} sample rows.')

        sample = get_json('/v3/reference/options/contracts', key,
                          {'underlying_ticker': 'AAPL', 'as_of': '2024-06-03',
                           'expiration_date.gte': '2024-06-21', 'expiration_date.lte': '2024-07-19',
                           'contract_type': 'put', 'strike_price.gte': 175,
                           'strike_price.lte': 190, 'limit': 1})
        save_private('development_contract_sample.json', sample, key)
        contracts = rows(sample)
        report['checks']['development_contract_sample_rows'] = len(contracts)
        print(f'Historical contracts accessible: {len(contracts)} sample rows.')
        if contracts:
            ticker = contracts[0].get('ticker', '')
            if not ticker.startswith('O:') or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.' for c in ticker):
                raise CheckError('Unexpected option ticker format.')
            sample = get_json(f'/v2/aggs/ticker/{ticker}/range/1/day/2024-06-03/2024-06-07', key,
                              {'adjusted': 'false', 'sort': 'asc', 'limit': 10})
            save_private('development_bar_sample.json', sample, key)
            report['checks']['development_bar_sample_rows'] = len(rows(sample))
            print(f'Historical bars accessible: {len(rows(sample))} sample rows.')
        else:
            report['checks']['development_bar_sample_rows'] = 0
        counts = [report['checks'][k] for k in (
            'taxonomy_rows', 'development_disclosure_sample_rows',
            'development_contract_sample_rows', 'development_bar_sample_rows')]
        report['status'] = 'ACCESS_CONFIRMED_FOR_SAMPLE' if all(counts) else 'INCOMPLETE_SAMPLE'
        print(report['status'] + ': full-window coverage still needs an audit.')
        return 0 if all(counts) else 2
    except CheckError as exc:
        report.update(status='ACCESS_CHECK_INCOMPLETE', reason=str(exc))
        raise
    finally:
        save_private('access_report.json', report, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Check local readiness without loading a key or making requests.')
    args = parser.parse_args()
    if args.offline:
        print('Local checker ready. Python ' + '.'.join(map(str, sys.version_info[:3])))
        print('No credentials loaded, no requests made, no backtest run. API access remains unverified.')
        return 0
    try:
        return check_access(read_key())
    except CheckError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
