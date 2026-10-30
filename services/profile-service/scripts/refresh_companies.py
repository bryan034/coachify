"""Explicit Wikidata refresh. Runtime searches use bundled JSON, never external APIs."""
import argparse
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import requests

DATA = Path(__file__).resolve().parents[1] / 'app' / 'data'
ENDPOINT = 'https://query.wikidata.org/sparql'
TYPES = ('Q4830453', 'Q783794', 'Q891723', 'Q6881511', 'Q167037', 'Q726870', 'Q18127', 'Q2085381', 'Q134161')
# Withhold conspicuous single-observation outliers pending source review; names remain searchable.
HEADCOUNTS_PENDING_REVIEW = {'Q12099588', 'Q4163110', 'Q20073341', 'Q12093389'}
CANDIDATES = '''SELECT ?company (MAX(?count) AS ?employees) WHERE {
  VALUES ?type { %s }
  ?company wdt:P31 ?type; wdt:P1128 ?count. FILTER(?count > 0)
  FILTER NOT EXISTS { ?company wdt:P576 ?dissolved }
} GROUP BY ?company ORDER BY DESC(?employees) LIMIT 7000''' % ' '.join('wd:' + item for item in TYPES)


def download(query):
    response = requests.get(ENDPOINT, params={'query': query, 'format': 'json'},
                            headers={'User-Agent': 'eloReferenceSnapshot/1.0', 'Accept': 'application/sparql-results+json'}, timeout=60)
    response.raise_for_status()
    return response.json()


def detail_query(ids):
    return '''SELECT ?company ?companyLabel ?count ?asOf ?rank ?countryCode WHERE {
      VALUES ?company { %s }
      OPTIONAL { ?company p:P1128 ?statement.
        ?statement ps:P1128 ?count; wikibase:rank ?rank.
        FILTER(?rank != wikibase:DeprecatedRank) OPTIONAL { ?statement pq:P585 ?asOf }
      }
      OPTIONAL { ?company wdt:P17/wdt:P297 ?countryCode }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul" }
    }''' % ' '.join('wd:' + item for item in ids)


def build(rows, seeds, snapshot_date):
    """Choose latest dated non-deprecated headcount, then sort descending."""
    cutoff = date.fromisoformat(snapshot_date)
    grouped = defaultdict(list)
    for row in rows:
        identifier = row['company']['value'].rsplit('/', 1)[-1]
        if not re.fullmatch(r'Q[1-9]\d*', identifier):
            raise ValueError('Unexpected Wikidata identifier')
        grouped[identifier].append(row)
    companies = []
    seed_ids = {row['id'] for row in seeds}
    singapore_ids = {row['id'] for row in seeds if row.get('singapore_based')}
    for identifier, statements in grouped.items():
        names = sorted({s['companyLabel']['value'].strip() for s in statements
                        if s['companyLabel']['value'].strip() != identifier})
        if not names or any(ord(c) < 32 for c in names[0]):
            continue
        counts = []
        countries = sorted({s['countryCode']['value'] for s in statements if 'countryCode' in s})
        for statement in statements:
            if 'count' not in statement or statement.get('rank', {}).get('value', '').endswith('DeprecatedRank'):
                continue
            try:
                value = Decimal(statement['count']['value'])
                if not value.is_finite() or value < 0 or value != value.to_integral_value():
                    continue
                as_of = statement.get('asOf', {}).get('value')
                as_of = date.fromisoformat(as_of[:10]) if as_of else None
                if as_of and as_of > cutoff:
                    continue
            except (ValueError, InvalidOperation):
                continue
            preferred = statement.get('rank', {}).get('value', '').endswith('PreferredRank')
            counts.append((as_of is not None, as_of or date.min, preferred, int(value)))
        chosen = max(counts) if counts else None
        if (chosen is None or chosen[3] == 0) and identifier not in seed_ids:
            continue
        note = None
        if chosen:
            earlier = [count for count in counts if count[0] and count[1] < chosen[1] and count[3] > 0]
            prior = max(earlier) if earlier else None
            if identifier in HEADCOUNTS_PENDING_REVIEW or chosen[3] > 5_000_000 or (prior and chosen[3] > prior[3] * 10):
                note = 'Headcount withheld pending review of an outlier observation or unusually large change.'
                chosen = None
        companies.append({'id': identifier, 'name': names[0], 'source_url': f'https://www.wikidata.org/wiki/{identifier}',
                          'employees': chosen[3] if chosen else None,
                          'employees_as_of': chosen[1].isoformat() if chosen and chosen[0] else None,
                          'country_codes': countries, **({'singapore_based': True} if identifier in singapore_ids else {}),
                          **({'employee_count_note': note} if note else {})})
    ranked = sorted(companies, key=lambda row: (-(row['employees'] or 0), row['name'].casefold(), row['id']))
    # The UI saves a declared name; identical display names need only one suggestion.
    unique = {}
    for row in ranked:
        unique.setdefault(' '.join(row['name'].casefold().split()), row)
    return list(unique.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates-file', type=Path, help='Optional downloaded SPARQL candidate JSON')
    parser.add_argument('--details-dir', type=Path, help='Optional directory of downloaded SPARQL detail batches')
    parser.add_argument('--snapshot-date', default=datetime.now().astimezone().date().isoformat())
    args = parser.parse_args()
    seeds = json.loads((DATA / 'employment-seeds.json').read_text())
    candidates = json.loads(args.candidates_file.read_text()) if args.candidates_file else download(CANDIDATES)
    candidate_ids = [row['company']['value'].rsplit('/', 1)[-1] for row in candidates['results']['bindings']]
    ids = list(dict.fromkeys(candidate_ids + [row['id'] for row in seeds]))
    if any(not re.fullmatch(r'Q[1-9]\d*', identifier) for identifier in ids):
        raise ValueError('Invalid input identifier')
    if args.details_dir:
        rows = [row for path in sorted(args.details_dir.glob('*.json'))
                for row in json.loads(path.read_text())['results']['bindings']]
    else:
        rows = [row for start in range(0, len(ids), 150)
                for row in download(detail_query(ids[start:start + 150]))['results']['bindings']]
    received = {row['company']['value'].rsplit('/', 1)[-1] for row in rows}
    if set(ids) != received:
        raise ValueError('Incomplete or mismatched detail download; existing snapshot unchanged')
    companies = build(rows, seeds, args.snapshot_date)
    ranked_count = sum(row['employees'] is not None and row['employees'] > 0 for row in companies)
    if ranked_count < 5000:
        raise ValueError('Fewer than 5,000 named employers with positive employee counts; existing snapshot unchanged')
    current = json.loads((DATA / 'employment.json').read_text())
    current.update(snapshot_date=args.snapshot_date, companies=companies,
                   coverage_note='Employee-ranked Wikidata company suggestions plus retained seed organisations. Not a complete registry or a live global ranking. Counts are dated where available and may be stale or undated. Manual names are always accepted. Industries are editorial suggestions.',
                   selection={'candidate_limit':7000,'company_types':list(TYPES),'candidate_query':CANDIDATES,
                              'ranking':'Latest dated non-deprecated headcount; undated only if no dated count. Ties prefer preferred rank, then higher count. Descending employee count; unknown counts last.',
                              'sanity_rules':'Withhold manually flagged outliers, counts above 5 million or more than tenfold the preceding dated positive count; retain employer as unranked pending review. Deduplicate identical display names.',
                              'employee_count_source':'https://www.wikidata.org/wiki/Property:P1128',
                              'ranked_company_count':ranked_count,
                              'singapore_supplement_count':sum(bool(row.get('singapore_based')) for row in companies),
                              'singapore_selection':'Retained seed businesses with Singapore country or headquarters; conflicting non-Singapore headquarters excluded during seed review.'})
    target = DATA / 'employment.json'
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(target)
    print(f'Saved {len(companies)} employer suggestions ({ranked_count} with positive headcounts).')


if __name__ == '__main__':
    main()
