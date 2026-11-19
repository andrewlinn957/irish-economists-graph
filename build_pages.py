#!/usr/bin/env python3
"""Build a read-only GitHub Pages snapshot from the preserved graph CSVs."""
import csv
import gzip
import heapq
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get('ECON_GRAPH_OUTPUT', ROOT / 'output'))
SITE = Path(os.environ.get('ECON_GRAPH_SITE', ROOT / 'docs'))
DATA = SITE / 'data'


def rows(name):
    with (OUT / f'{name}.csv').open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def ids(value):
    return [part for part in (value or '').split('|') if part]


def flag(value):
    return value in ('1', 'true', 'True')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with gzip.open(str(path) + '.gz', 'wb', compresslevel=6) as fh:
        fh.write(payload)


def bucket(key):
    return sum(map(ord, key)) % 32


class Shards:
    def __init__(self, kind):
        directory = DATA / kind
        directory.mkdir(parents=True, exist_ok=True)
        self.files = [gzip.open(directory / f'{n}.json.gz', 'wb', compresslevel=6) for n in range(32)]
        self.first = [True] * 32
        self.count = 0
        for file in self.files:
            file.write(b'{')

    def add(self, key, value):
        n = bucket(key)
        file = self.files[n]
        if not self.first[n]:
            file.write(b',')
        self.first[n] = False
        file.write(json.dumps(key, ensure_ascii=False).encode('utf-8'))
        file.write(b':')
        file.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        self.count += 1

    def close(self):
        for file in self.files:
            file.write(b'}')
            file.close()


def main():
    sys.path.insert(0, str(ROOT / 'ui'))
    from server import overview, country_overview, topic_overview, matchmaker_data

    people_rows, paper_rows = rows('people'), rows('papers')
    inst_rows, topic_rows = rows('institutions'), rows('topics')
    authorships, affiliations = rows('authorships'), rows('paper_affiliations')
    shared = rows('shared_institution_year')
    paper_topics, topic_pairs = rows('paper_topics'), rows('topic_cooccurs')
    people = {r['person_id']: r for r in people_rows}
    papers = {r['paper_id']: r for r in paper_rows}
    institutions = {r['institution_id']: r for r in inst_rows}
    topics = {r['topic_id']: r for r in topic_rows}
    graph = overview()
    for country in ('island', 'Ireland', 'Northern Ireland', 'England', 'Scotland', 'Wales', 'uk', 'all'):
        write(DATA / f'overview-{country}.json', country_overview(country))
    write(DATA / 'topic-overview.json', topic_overview())

    catalogue = {
        'person': [{'id': k, 'name': r['name'], 'qualifying': flag(r['qualifying'])} for k, r in people.items()],
        'institution': [{'id': k, 'name': r['name'], 'country': r.get('country', ''),
                         'qualifying': flag(r['target'])} for k, r in institutions.items()],
        'topic': [{'id': k, 'name': r['name']} for k, r in topics.items()],
    }
    mm_people, mm_topics, mm_papers, mm_person_topics, mm_affiliations = matchmaker_data()
    catalogue['matchmaker'] = [
        {'id': pid, 'name': n['label'],
         'institution': institutions[mm_affiliations[pid].most_common(1)[0][0]]['name'] if mm_affiliations[pid] else None}
        for pid, n in mm_people.items()
    ]
    write(DATA / 'catalogue.json', catalogue)

    by_person = defaultdict(list)
    by_paper = defaultdict(list)
    for row in authorships:
        by_person[row['person_id']].append(row)
        by_paper[row['paper_id']].append(row)
    pt_by_paper, pt_by_topic = defaultdict(list), defaultdict(list)
    for row in paper_topics:
        pt_by_paper[row['paper_id']].append(row)
        pt_by_topic[row['topic_id']].append(row)
    aff_by_person_inst, aff_by_inst_person = defaultdict(list), defaultdict(list)
    for row in affiliations:
        aff_by_person_inst[(row['person_id'], row['institution_id'])].append(row)
        aff_by_inst_person[(row['institution_id'], row['person_id'])].append(row)
    aff_groups_person, aff_groups_inst = defaultdict(list), defaultdict(list)
    for (pid, iid), group in aff_by_person_inst.items():
        aff_groups_person[pid].append((iid, group))
        aff_groups_inst[iid].append((pid, group))
    # A hyper-authored paper generates many valid pairwise relationships. Keep
    # the complete CSV/Neo4j evidence, but retain only a bounded set of links
    # per person in the bounded static detail view.
    co_by_person = defaultdict(list)
    with (OUT / 'coauthored.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            weight = int(row['paper_count'])
            for person, other in ((row['person_a'], row['person_b']),
                                  (row['person_b'], row['person_a'])):
                if person not in people or other not in people:
                    continue
                heap = co_by_person[person]
                item = (weight, other, row)
                limit = 25 if flag(people[person]['qualifying']) else 10
                if len(heap) < limit:
                    heapq.heappush(heap, item)
                elif item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, item)
    shared_by_person = defaultdict(list)
    for row in shared:
        shared_by_person[row['person_a']].append((row['person_b'], row))
        shared_by_person[row['person_b']].append((row['person_a'], row))
    related_by_topic = defaultdict(list)
    for row in topic_pairs:
        related_by_topic[row['topic_a']].append((row['topic_b'], row))
        related_by_topic[row['topic_b']].append((row['topic_a'], row))

    def paper_card(pid):
        p = papers[pid]
        return {'id': pid, 'title': p['title'], 'date': p['publication_date'],
                'doi': p['doi'], 'openalex': p['openalex_id']}

    def group_affiliation(group):
        paper_ids = list(dict.fromkeys(r['paper_id'] for r in group))
        dates = list(dict.fromkeys(r['publication_date'] for r in group))
        raw = list(dict.fromkeys(r['raw_affiliation'] for r in group))
        return {'weight': len(paper_ids), 'paper_ids': paper_ids[:25],
                'dates': dates[:25], 'raw_affiliations': raw[:10]}

    person_details = Shards('person')
    for pid, p in people.items():
        collaborators = []
        for _, other, row in co_by_person[pid]:
            if other in people:
                collaborators.append({'id': other, 'name': people[other]['name'],
                                      'qualifying': flag(people[other]['qualifying']),
                                      'weight': int(row['paper_count']), 'paper_ids': ids(row['paper_ids']),
                                      'years': ids(row['years'])})
        collaborators.sort(key=lambda x: (-x['weight'], x['name']))
        affiliated = []
        for iid, group in aff_groups_person[pid]:
            if iid in institutions:
                i = institutions[iid]
                affiliated.append({'id': iid, 'name': i['name'], 'target': flag(i['target']),
                                   **group_affiliation(group)})
        affiliated.sort(key=lambda x: (-x['weight'], x['name']))
        topic_papers = defaultdict(set)
        for row in by_person[pid]:
            for pt in pt_by_paper[row['paper_id']]:
                topic_papers[pt['topic_id']].add(row['paper_id'])
        person_topics = [{'id': tid, 'name': topics[tid]['name'], 'weight': len(pids),
                          'paper_ids': sorted(pids)[:25]} for tid, pids in topic_papers.items() if tid in topics]
        person_topics.sort(key=lambda x: (-x['weight'], x['name']))
        authored_papers = sorted({r['paper_id'] for r in by_person[pid] if r['paper_id'] in papers},
                                 key=lambda x: papers[x]['publication_date'], reverse=True)
        shared_rows = []
        for other, row in shared_by_person[pid]:
            if other not in people or row['institution_id'] not in institutions or not flag(institutions[row['institution_id']]['target']):
                continue
            a, b = ('paper_ids_a', 'paper_ids_b') if pid == row['person_a'] else ('paper_ids_b', 'paper_ids_a')
            shared_rows.append({'id': other, 'name': people[other]['name'],
                                'institution': institutions[row['institution_id']]['name'],
                                'years': ids(row['years']), 'paper_ids_a': ids(row[a]), 'paper_ids_b': ids(row[b])})
        shared_rows.sort(key=lambda x: (-len(x['years']), x['name']))
        person_details.add(pid, {
            'centre': {'id': pid, 'name': p['name'], 'orcid': p['orcid'], 'qualifying': flag(p['qualifying'])},
            'collaborators': collaborators[:25], 'affiliations': affiliated[:35],
            'topics': person_topics[:20], 'papers': [paper_card(x) for x in authored_papers[:35]],
            'shared': shared_rows[:55],
        })
    person_details.close()

    inst_details = Shards('institution')
    for iid, inst in institutions.items():
        authors = []
        matching_papers = set()
        for pid, group in aff_groups_inst[iid]:
            if pid not in people:
                continue
            authors.append({'id': pid, 'name': people[pid]['name'], **group_affiliation(group)})
            matching_papers.update(r['paper_id'] for r in group)
        authors.sort(key=lambda x: (-x['weight'], x['name']))
        recent = sorted((x for x in matching_papers if x in papers), key=lambda x: papers[x]['publication_date'], reverse=True)
        inst_details.add(iid, {
            'centre': {'id': iid, 'name': inst['name'], 'ror': inst['ror'],
                       'country': inst.get('country', ''), 'target': flag(inst['target'])},
            'people': authors[:75], 'papers': [paper_card(x) for x in recent[:35]],
        })
    inst_details.close()

    topic_details = Shards('topic')
    for tid, topic in topics.items():
        related = []
        for other, row in related_by_topic[tid]:
            if other in topics:
                related.append({'id': other, 'name': topics[other]['name'], 'field': topics[other]['field'],
                                'weight': int(row['paper_count']), 'paper_ids': ids(row['paper_ids'])})
        related.sort(key=lambda x: (-x['weight'], x['name']))
        topic_papers = []
        for row in pt_by_topic[tid]:
            if row['paper_id'] in papers:
                topic_papers.append({**paper_card(row['paper_id']), 'score': float(row['score']), 'primary': flag(row['primary'])})
        topic_papers.sort(key=lambda x: (-x['score'], x['date']), reverse=False)
        topic_papers.sort(key=lambda x: x['date'], reverse=True)
        topic_papers.sort(key=lambda x: x['score'], reverse=True)
        topic_details.add(tid, {
            'centre': {'id': tid, 'name': topic['name'], 'field': topic['field'],
                       'subfield': topic['subfield'], 'openalex': topic['openalex_id']},
            'related': related[:60], 'papers': topic_papers[:40],
        })
    topic_details.close()

    paper_details = Shards('paper')
    for wid, paper in papers.items():
        author_rows = sorted(by_paper[wid], key=lambda r: int(r['position'] or 0))[:300]
        authors = [{**paper_card(wid), 'person_id': r['person_id'],
                    'person_name': people.get(r['person_id'], {}).get('name', r['raw_name']),
                    'position': int(r['position'] or 0)} for r in author_rows]
        if not authors:
            authors = [{**paper_card(wid), 'person_id': None, 'person_name': None, 'position': None}]
        paper_details.add(wid, {'authors': authors,
                              'topics': [{'id': r['topic_id'], 'name': topics[r['topic_id']]['name'],
                                          'score': float(r['score']), 'primary': flag(r['primary'])}
                                         for r in sorted(pt_by_paper[wid], key=lambda r: -float(r['score'])) if r['topic_id'] in topics]})
    paper_details.close()

    match_index = {'topics': mm_topics, 'people': {
        pid: {'name': n['label'], 'papers': sorted(mm_papers[pid]),
              'topics': dict(mm_person_topics[pid]), 'communities': n['communities'],
              'institution': institutions[mm_affiliations[pid].most_common(1)[0][0]]['name']
              if mm_affiliations[pid] else None}
        for pid, n in mm_people.items()}}
    write(DATA / 'matchmaker-index.json', match_index)

    for name in ('index.html', 'app.js', 'style.css', 'pages-adapter.js'):
        shutil.copy2(ROOT / 'ui' / name, SITE / name)
    vendor = ROOT.parent.parent / 'qbit-mini-ui' / 'china-graph' / 'foam-graph.js'
    shutil.copy2(vendor, SITE / 'force-graph.js')
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    for asset in ('style.css', 'app.js', 'force-graph.js'):
        html = html.replace(f'/{asset}', f'./{asset}')
    html = html.replace('<script src="./app.js" defer></script>',
                        '<script src="./pages-adapter.js" defer></script>\n  <script src="./app.js" defer></script>')
    (SITE / 'index.html').write_text(html, encoding='utf-8')
    (SITE / '.nojekyll').touch()
    print(json.dumps({'overview_nodes': len(graph['nodes']), 'overview_links': len(graph['links']),
                      'people': person_details.count, 'institutions': inst_details.count,
                      'topics': topic_details.count, 'papers': paper_details.count,
                      'matchmaker': len(match_index['people'])}))


if __name__ == '__main__':
    main()
