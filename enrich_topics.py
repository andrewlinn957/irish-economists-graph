#!/usr/bin/env python3
"""Derive OpenAlex paper-topic and topic-pair evidence from the preserved works."""
import csv
import gzip
import hashlib
import json
import os
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'raw' / 'openalex'
BACKFILL = RAW / 'backfill-2012'
UK_RAW = RAW / 'uk'
OUT = Path(os.environ.get('ECON_GRAPH_OUTPUT', ROOT / 'output'))


def read_work(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def write_csv(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    eligible = {r['paper_id'] for r in csv.DictReader((OUT / 'papers.csv').open())}
    seen, topics, links = set(), {}, []
    pairs = defaultdict(set)
    raw_files = (sorted(RAW.glob('works-*.json.gz')) + sorted(RAW.glob('extra-*.json.gz')) +
                 sorted(BACKFILL.glob('works-*.json.gz')) + sorted(BACKFILL.glob('extra-*.json.gz')) +
                 sorted(UK_RAW.glob('[0-9][0-9][0-9][0-9]/works-*.json.gz')))
    for path in raw_files:
        payload = read_work(path)
        for work in payload['results']:
            pid = work['id'].rsplit('/', 1)[-1]
            if pid not in eligible or pid in seen:
                continue
            seen.add(pid)
            full = path.parent / 'full' / f'{pid}.json.gz'
            if full.exists():
                work = read_work(full)['work']
            ids = set()
            primary = (work.get('primary_topic') or {}).get('id', '').rsplit('/', 1)[-1]
            for item in work.get('topics') or []:
                tid = (item.get('id') or '').rsplit('/', 1)[-1]
                if not tid or tid in ids:
                    continue
                ids.add(tid)
                topics[tid] = {'topic_id': tid, 'name': item.get('display_name') or tid,
                               'openalex_id': item['id'],
                               'field': (item.get('field') or {}).get('display_name') or '',
                               'subfield': (item.get('subfield') or {}).get('display_name') or ''}
                links.append({'paper_id': pid, 'topic_id': tid,
                              'score': item.get('score') or 0, 'primary': int(tid == primary)})
            for pair in combinations(sorted(ids), 2):
                pairs[pair].add(pid)
    if seen != eligible:
        raise RuntimeError(f'Missing topic source records for {len(eligible - seen)} papers')
    pair_rows = [{'topic_a': a, 'topic_b': b, 'paper_count': len(papers),
                  'paper_ids': '|'.join(sorted(papers))} for (a, b), papers in sorted(pairs.items())]
    write_csv(OUT / 'topics.csv', ['topic_id', 'name', 'openalex_id', 'field', 'subfield'],
              [topics[k] for k in sorted(topics)])
    write_csv(OUT / 'paper_topics.csv', ['paper_id', 'topic_id', 'score', 'primary'], links)
    write_csv(OUT / 'topic_cooccurs.csv', ['topic_a', 'topic_b', 'paper_count', 'paper_ids'], pair_rows)
    summary = {'papers': len(seen), 'topics': len(topics),
               'paper_topic_edges': len(links), 'topic_pairs': len(pair_rows)}
    summary['sha256'] = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                         for name in ('topics.csv', 'paper_topics.csv', 'topic_cooccurs.csv')}
    (OUT / 'topic-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'sha256'}))


if __name__ == '__main__':
    main()
