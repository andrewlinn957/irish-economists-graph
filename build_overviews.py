#!/usr/bin/env python3
"""Refresh just the country overview snapshots without rebuilding detail shards."""
import gc
import gzip
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'ui'))
import server

DATA = ROOT / 'docs' / 'data'


def write(path, graph):
    temporary = path.with_suffix(path.suffix + '.tmp')
    payload = json.dumps(graph, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with gzip.open(temporary, 'wb', compresslevel=6) as output:
        output.write(payload)
    os.replace(temporary, path)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    server.overview()
    for country in ('island', 'Ireland', 'Northern Ireland', 'England', 'Scotland', 'Wales', 'uk', 'all'):
        graph = server.country_overview(country)
        write(DATA / f'overview-{country}.json.gz', graph)
        write(DATA / f'overview-{country}-people.json.gz', server.people_view(graph))
        print(f'{country}: {len(graph["nodes"])} nodes, {len(graph["links"])} links', flush=True)
        server._country_overviews.pop(country, None)
        gc.collect()


if __name__ == '__main__':
    main()
