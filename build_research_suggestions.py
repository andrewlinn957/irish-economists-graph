#!/usr/bin/env python3
"""Derive exploratory weak bridges and emerging topic combinations from source CSVs."""
import csv
import gzip
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get('ECON_GRAPH_OUTPUT', ROOT / 'output'))
DEST = Path(os.environ.get('ECON_GRAPH_SITE', ROOT / 'docs')) / 'data' / 'research-suggestions.json.gz'


def rows(name):
    with (OUTPUT / name).open(newline='', encoding='utf-8') as source:
        yield from csv.DictReader(source)


def partition(topics, pairs, counts):
    """Deterministic, degree-corrected local modularity optimisation on topic pairs."""
    neighbours = defaultdict(dict)
    for pair in pairs:
        a, b = pair['a'], pair['b']
        weight = pair['count'] / math.sqrt(max(1, counts[a] * counts[b]))
        neighbours[a][b] = weight
        neighbours[b][a] = weight
    degree = {tid: sum(neighbours[tid].values()) for tid in topics}
    total = sum(degree.values()) or 1
    groups = {tid: tid for tid in topics}
    volume = dict(degree)
    for _ in range(25):
        moves = 0
        for tid in sorted(topics, key=lambda key: (-degree[key], key)):
            old = groups[tid]
            volume[old] -= degree[tid]
            votes = Counter()
            for other, weight in neighbours[tid].items():
                votes[groups[other]] += weight
            # A modestly low resolution allows research-scale, not paper-scale, groups.
            def gain(group):
                return votes[group] - .8 * degree[tid] * volume[group] / total
            choices = set(votes) | {old}
            best = max(choices, key=lambda group: (gain(group), group == old, group))
            if best != old:
                groups[tid] = best
                moves += 1
            volume[groups[tid]] += degree[tid]
        if not moves:
            break
    return groups, neighbours


def main():
    topics = {row['topic_id']: {'id': row['topic_id'], 'name': row['name'],
                                'field': row['field']} for row in rows('topics.csv')}
    years = {row['paper_id']: int(row['publication_date'][:4]) for row in rows('papers.csv')
             if row['publication_date'][:4].isdigit()}
    topic_papers = defaultdict(set)
    topic_period = defaultdict(Counter)
    paper_topics = defaultdict(set)
    for row in rows('paper_topics.csv'):
        paper, topic = row['paper_id'], row['topic_id']
        if paper not in years or topic not in topics or paper in topic_papers[topic]:
            continue
        topic_papers[topic].add(paper)
        paper_topics[paper].add(topic)
        year = years[paper]
        if 2018 <= year <= 2021:
            topic_period[topic]['earlier'] += 1
        elif 2022 <= year <= 2025:
            topic_period[topic]['recent'] += 1
    counts = {tid: len(topic_papers[tid]) for tid in topics}
    pairs = []
    by_pair = {}
    for row in rows('topic_cooccurs.csv'):
        a, b = row['topic_a'], row['topic_b']
        if a not in topics or b not in topics or a == b:
            continue
        papers = set(filter(None, row['paper_ids'].split('|')))
        pair = {'a': a, 'b': b, 'count': int(row['paper_count']), 'papers': papers,
                'recent': sum(2022 <= years.get(paper, 0) <= 2025 for paper in papers)}
        pairs.append(pair)
        by_pair[tuple(sorted((a, b)))] = pair
    groups, neighbours = partition(topics, pairs, counts)
    communities = defaultdict(set)
    for tid, group in groups.items():
        communities[group].add(tid)
    community_papers = {group: set().union(*(topic_papers[tid] for tid in members))
                        for group, members in communities.items()}
    community_name = {group: topics[max(members, key=lambda tid: (counts[tid], tid))]['name']
                      for group, members in communities.items()}
    crossing = defaultdict(set)
    examples = defaultdict(list)
    for pair in pairs:
        a, b = groups[pair['a']], groups[pair['b']]
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        crossing[key].update(pair['papers'])
        examples[key].append(pair)
    weak = []
    for (a, b), papers in crossing.items():
        if min(len(communities[a]), len(communities[b])) < 8:
            continue
        if min(len(community_papers[a]), len(community_papers[b])) < 200:
            continue
        count = len(papers)
        if count < 3:
            continue
        representative = max(examples[a, b], key=lambda pair: (pair['count'], pair['a'], pair['b']))
        score = math.sqrt(min(len(community_papers[a]), len(community_papers[b]))) / (count + 1)
        weak.append({'group_ids': (a, b), 'a': {'name': community_name[a], 'topics': len(communities[a]),
                           'papers': len(community_papers[a])},
                     'b': {'name': community_name[b], 'topics': len(communities[b]),
                           'papers': len(community_papers[b])},
                     'bridge_papers': count,
                     'representative': {'a': topics[representative['a']]['name'],
                                        'b': topics[representative['b']]['name'],
                                        'papers': representative['count']},
                     'examples': sorted(papers)[:5], 'score': score})
    weak.sort(key=lambda item: (-item['score'], item['bridge_papers'], item['a']['name']))

    relevant_fields = {'Economics, Econometrics and Finance', 'Business, Management and Accounting',
                       'Social Sciences', 'Environmental Science', 'Energy', 'Decision Sciences'}
    growing = [tid for tid in topics if topics[tid]['field'] in relevant_fields and counts[tid] >= 30
               and topic_period[tid]['recent'] >= 15
               and topic_period[tid]['recent'] >= topic_period[tid]['earlier'] * 1.2
               and topic_period[tid]['recent'] - topic_period[tid]['earlier'] >= 5]
    emerging = []
    for index, a in enumerate(growing):
        for b in growing[index + 1:]:
            pair = by_pair.get(tuple(sorted((a, b))))
            joint_recent = pair['recent'] if pair else 0
            if joint_recent > 3 or (pair and pair['count'] > 5):
                continue
            common = set(neighbours[a]) & set(neighbours[b])
            # Require at least two specific, independently evidenced intermediaries.
            bridges = [tid for tid in common
                       if min(neighbours[a][tid], neighbours[b][tid]) >= .002]
            if len(bridges) < 2:
                continue
            bridges.sort(key=lambda tid: -(min(neighbours[a][tid], neighbours[b][tid]) /
                                           math.log2(2 + len(neighbours[tid]))))
            proximity = sum(min(neighbours[a][tid], neighbours[b][tid]) /
                            math.log2(2 + len(neighbours[tid])) for tid in bridges[:8])
            growth = min(topic_period[a]['recent'] / max(1, topic_period[a]['earlier']),
                         topic_period[b]['recent'] / max(1, topic_period[b]['earlier']))
            score = proximity * math.log1p(min(topic_period[a]['recent'], topic_period[b]['recent'])) \
                * min(growth, 4) / (1 + joint_recent)
            emerging.append({'topic_ids': (a, b),
                             'field_pair': tuple(sorted((topics[a]['field'], topics[b]['field']))),
                             'a': {'name': topics[a]['name'], 'papers': counts[a],
                                   'earlier': topic_period[a]['earlier'], 'recent': topic_period[a]['recent']},
                             'b': {'name': topics[b]['name'], 'papers': counts[b],
                                   'earlier': topic_period[b]['earlier'], 'recent': topic_period[b]['recent']},
                             'joint_recent': joint_recent,
                             'joint_all': pair['count'] if pair else 0,
                             'shared_neighbours': [topics[tid]['name'] for tid in bridges[:3]],
                             'examples': sorted(pair['papers'])[:5] if pair else [],
                             'score': score})
    emerging.sort(key=lambda item: (-item['score'], item['joint_recent'], item['a']['name']))
    def diversified(items, key, cap=5):
        used = Counter()
        used_fields = Counter()
        selected = []
        for item in items:
            ids = item.pop(key)
            fields = item.pop('field_pair', None)
            if any(used[value] >= cap for value in ids):
                continue
            if fields and used_fields[fields] >= 6:
                continue
            selected.append(item)
            used.update(ids)
            if fields:
                used_fields[fields] += 1
            if len(selected) == 300:
                break
        return selected

    payload = {'scope': 'Included OpenAlex economics-primary papers, 2012 to 18 November 2026.',
               'windows': {'earlier': '2018–2021', 'recent': '2022–2025'},
               'total_papers': len(years), 'topic_count': len(topics), 'community_count': len(communities),
               'weak_bridges': diversified(weak, 'group_ids'),
               'emerging_combinations': diversified(emerging, 'topic_ids')}
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DEST, 'wt', encoding='utf-8', compresslevel=6) as target:
        json.dump(payload, target, ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({'topics': len(topics), 'communities': len(communities),
                      'weak_bridges': len(weak), 'emerging_combinations': len(emerging),
                      'published_weak': len(payload['weak_bridges']),
                      'published_emerging': len(payload['emerging_combinations'])}))


if __name__ == '__main__':
    main()
