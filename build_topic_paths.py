#!/usr/bin/env python3
"""Build the compact, source-backed topic network used by the path explorer."""
import csv
import gzip
import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get('ECON_GRAPH_OUTPUT', ROOT / 'output'))
DEST = Path(os.environ.get('ECON_GRAPH_SITE', ROOT / 'docs')) / 'data' / 'topic-path.json.gz'


def rows(name):
    with (OUTPUT / name).open(newline='', encoding='utf-8') as source:
        yield from csv.DictReader(source)


def main():
    counts = Counter()
    papers = set()
    seen = set()
    for row in rows('paper_topics.csv'):
        key = (row['paper_id'], row['topic_id'])
        if key in seen:
            continue
        seen.add(key)
        papers.add(row['paper_id'])
        counts[row['topic_id']] += 1
    topics = [{'id': row['topic_id'], 'name': row['name'], 'papers': counts[row['topic_id']]}
              for row in rows('topics.csv')]
    links = [{'a': row['topic_a'], 'b': row['topic_b'], 'papers': int(row['paper_count']),
              'examples': row['paper_ids'].split('|')[:5]}
             for row in rows('topic_cooccurs.csv')]
    payload = {'total_papers': len(papers), 'topics': topics, 'links': links,
               'scope': 'Included OpenAlex economics-primary papers, 2012 to 18 November 2026.'}
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DEST, 'wt', encoding='utf-8', compresslevel=6) as target:
        json.dump(payload, target, ensure_ascii=False, separators=(',', ':'))
    print(f'{len(topics)} topics, {len(links)} supported topic pairs, {len(papers)} papers')


if __name__ == '__main__':
    main()
