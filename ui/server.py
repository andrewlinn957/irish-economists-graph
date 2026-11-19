#!/usr/bin/env python3
"""Read-only, Tailscale-bound UK and Ireland economists graph viewer."""
import base64
import csv
import gzip
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
AUTH_FILE = Path('/root/.config/china-pra-neo4j/auth.env')
NEO4J = 'http://100.116.32.107:7474/db/neo4j/query/v2'
HOST = os.environ.get('UKIE_GRAPH_HOST', '100.116.32.107')
PORT = int(os.environ.get('UKIE_GRAPH_PORT', '8127'))
OUTPUT = Path(os.environ.get('ECON_GRAPH_OUTPUT', HERE.parent / 'output'))
OVERVIEW_FILE = OUTPUT / 'irish-economists.graphml'
SNAPSHOT_DIR = HERE.parent / 'docs' / 'data'
SNAPSHOT_INPUTS = (OVERVIEW_FILE, OUTPUT / 'topics.csv', OUTPUT / 'topic_cooccurs.csv',
                   OUTPUT / 'paper_topics.csv', OUTPUT / 'authorships.csv', Path(__file__))
SNAPSHOT_COUNTRIES = {'island', 'Ireland', 'Northern Ireland', 'England', 'Scotland', 'Wales', 'uk', 'all'}
_overview = None
_country_overviews = {}
_matchmaker_data = None


def snapshot_file(country, view='full'):
    if country not in SNAPSHOT_COUNTRIES or view not in {'full', 'people'}:
        return None
    suffix = '-people' if view == 'people' else ''
    path = SNAPSHOT_DIR / f'overview-{country}{suffix}.json.gz'
    if not path.is_file():
        return None
    try:
        if any(path.stat().st_mtime_ns < source.stat().st_mtime_ns for source in SNAPSHOT_INPUTS):
            return None
    except FileNotFoundError:
        return None
    return path


def people_view(graph):
    return {'nodes': [node for node in graph['nodes'] if node['kind'] != 'topic'],
            'links': [edge for edge in graph['links'] if edge['type'] in {'coauthor', 'affiliation'}]}


def add_clusters(nodes, links):
    """Three independent, deterministic weighted label-propagation partitions.

    Each lens clusters on its own evidence edges. Other node kinds inherit the
    most strongly connected community for display only, not as a graph fact.
    """
    by_id = {n['id']: n for n in nodes}
    lenses = {
        'coauthor': ({'coauthor'}, 'person'),
        'topic': ({'topic', 'topic_pair'}, 'topic'),
        'institution': ({'affiliation'}, 'institution'),
    }
    for lens, (types, representative_kind) in lenses.items():
        adjacency = defaultdict(list)
        all_neighbours = defaultdict(list)
        degree = Counter()
        for edge in links:
            a, b = edge['source'], edge['target']
            if a == b or a not in by_id or b not in by_id:
                continue
            weight = min(float(edge.get('weight') or 1), 12) ** .5
            all_neighbours[a].append((b, weight))
            all_neighbours[b].append((a, weight))
            if edge['type'] in types:
                adjacency[a].append((b, weight))
                adjacency[b].append((a, weight))
                degree[a] += weight
                degree[b] += weight
        core = set(adjacency)
        labels = {nid: nid for nid in core}
        order = sorted(core, key=lambda nid: (-degree[nid], nid))
        for _ in range(15):
            changed = 0
            for nid in order:
                votes = Counter()
                for other, weight in adjacency[nid]:
                    votes[labels[other]] += weight / max(degree[other], 1) ** .75
                winner = min(votes, key=lambda label: (-votes[label], label))
                if winner != labels[nid]:
                    labels[nid] = winner
                    changed += 1
            if not changed:
                break
        groups = defaultdict(list)
        for nid, label in labels.items():
            groups[label].append(nid)
        group_name = {}
        for label, group in groups.items():
            options = [nid for nid in group if by_id[nid]['kind'] == representative_kind]
            representative = max(options or group, key=lambda nid: (degree[nid], nid))
            group_name[label] = by_id[representative]['label']
        for nid in by_id:
            if nid in labels:
                label = labels[nid]
                derived = False
            else:
                votes = Counter()
                for other, weight in all_neighbours[nid]:
                    if other in labels:
                        votes[labels[other]] += weight
                label = min(votes, key=lambda key: (-votes[key], key)) if votes else None
                derived = True
            by_id[nid].setdefault('communities', {})[lens] = {
                'id': label or 'unconnected',
                'label': group_name.get(label, 'Unconnected'),
                'derived': derived,
            }


def overview():
    global _overview
    if _overview is not None:
        return _overview
    snapshot = snapshot_file('all')
    if snapshot:
        with gzip.open(snapshot, 'rt', encoding='utf-8') as source:
            _overview = json.load(source)
        return _overview
    ns = {'g': 'http://graphml.graphdrawing.org/xmlns'}
    root = ET.parse(OVERVIEW_FILE).getroot()
    nodes, links = [], []
    for node in root.findall('.//g:node', ns):
        values = {d.attrib['key']: d.text or '' for d in node.findall('g:data', ns)}
        nodes.append({'id': node.attrib['id'].split(':', 1)[1], 'label': values.get('label', ''),
                      'kind': values.get('kind', 'person'), 'country': values.get('country', ''),
                      'countries': values.get('countries', '').split('|') if values.get('countries') else []})
    for edge in root.findall('.//g:edge', ns):
        values = {d.attrib['key']: d.text or '' for d in edge.findall('g:data', ns)}
        links.append({'source': edge.attrib['source'].split(':', 1)[1],
                      'target': edge.attrib['target'].split(':', 1)[1],
                      'type': 'affiliation' if values.get('relation') == 'affiliated_on_paper' else 'coauthor',
                      'weight': int(values.get('weight') or 1),
                      'paper_ids': [x for x in values.get('paper_ids', '').split('|') if x]})
    by_id = {n['id'] for n in nodes}
    with (OUTPUT / 'topics.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            nodes.append({'id': row['topic_id'], 'label': row['name'], 'kind': 'topic',
                          'field': row['field'], 'subfield': row['subfield']})
    with (OUTPUT / 'topic_cooccurs.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            links.append({'source': row['topic_a'], 'target': row['topic_b'], 'type': 'topic_pair',
                          'weight': int(row['paper_count']), 'paper_ids': row['paper_ids'].split('|')[:30]})
    paper_topics = defaultdict(list)
    with (OUTPUT / 'paper_topics.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            paper_topics[row['paper_id']].append(row['topic_id'])
    author_topic_papers = defaultdict(set)
    with (OUTPUT / 'authorships.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['person_id'] in by_id:
                for tid in paper_topics[row['paper_id']]:
                    author_topic_papers[(row['person_id'], tid)].add(row['paper_id'])
    for (pid, tid), papers in sorted(author_topic_papers.items()):
        links.append({'source': pid, 'target': tid, 'type': 'topic',
                      'weight': len(papers), 'paper_ids': sorted(papers)[:30]})
    add_clusters(nodes, links)
    _overview = {'nodes': nodes, 'links': links}
    return _overview


def country_overview(country='island'):
    if country in _country_overviews:
        return _country_overviews[country]
    graph = overview()
    if country == 'all':
        return graph
    choices = {
        'island': {'Ireland', 'Northern Ireland'},
        'uk': {'England', 'Scotland', 'Wales', 'Northern Ireland', 'United Kingdom (unclassified)'},
    }
    allowed = choices.get(country, {country})
    institutions = {n['id'] for n in graph['nodes'] if n['kind'] == 'institution' and n.get('country') in allowed}
    people = {n['id'] for n in graph['nodes'] if n['kind'] == 'person' and set(n.get('countries', [])) & allowed}
    topics = set()
    for edge in graph['links']:
        if edge['type'] == 'topic':
            if edge['source'] in people:
                topics.add(edge['target'])
            if edge['target'] in people:
                topics.add(edge['source'])
    ids = people | institutions | topics
    result = {'nodes': [n for n in graph['nodes'] if n['id'] in ids],
              'links': [e for e in graph['links'] if e['source'] in ids and e['target'] in ids]}
    _country_overviews[country] = result
    return result


def topic_overview():
    graph = overview()
    return {'nodes': [n for n in graph['nodes'] if n['kind'] == 'topic'],
            'links': [e for e in graph['links'] if e['type'] == 'topic_pair']}


def matchmaker_data():
    global _matchmaker_data
    if _matchmaker_data is not None:
        return _matchmaker_data
    graph = overview()
    people = {n['id']: n for n in graph['nodes'] if n['kind'] == 'person'}
    topics = {n['id']: n['label'] for n in graph['nodes'] if n['kind'] == 'topic'}
    paper_topics = defaultdict(set)
    with (OUTPUT / 'paper_topics.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            paper_topics[row['paper_id']].add(row['topic_id'])
    person_papers = defaultdict(set)
    person_topics = defaultdict(Counter)
    with (OUTPUT / 'authorships.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            pid, paper = row['person_id'], row['paper_id']
            if pid in people and paper not in person_papers[pid]:
                person_papers[pid].add(paper)
                person_topics[pid].update(paper_topics[paper])
    affiliations = defaultdict(Counter)
    for edge in graph['links']:
        if edge['type'] != 'affiliation':
            continue
        pid, iid = edge['source'], edge['target']
        if pid not in people:
            pid, iid = iid, pid
        if pid in people:
            affiliations[pid][iid] += edge['weight']
    _matchmaker_data = (people, topics, person_papers, person_topics, affiliations)
    return _matchmaker_data


def matchmaker_search(term):
    term = term.strip().lower()[:100]
    if len(term) < 2:
        return []
    people, _, _, _, affiliations = matchmaker_data()
    institutions = {n['id']: n['label'] for n in overview()['nodes'] if n['kind'] == 'institution'}
    matches = [n for n in people.values() if term in n['label'].lower()]
    matches.sort(key=lambda n: (not n['label'].lower().startswith(term), n['label'].lower(), n['id']))
    return [{'id': n['id'], 'name': n['label'],
             'institution': institutions.get(affiliations[n['id']].most_common(1)[0][0]) if affiliations[n['id']] else None}
            for n in matches[:20]]


def matchmaker(person_id):
    people, topics, person_papers, person_topics, affiliations = matchmaker_data()
    source = people.get(person_id)
    if source is None:
        return None
    source_papers = person_papers[person_id]
    source_topics = person_topics[person_id]
    source_clusters = source['communities']
    candidates = []
    for candidate in people.values():
        cid = candidate['id']
        if cid == person_id or source_papers.intersection(person_papers[cid]):
            continue
        clusters = candidate['communities']
        shared_topic_cluster = (source_clusters['topic']['id'] != 'unconnected' and
                                source_clusters['topic']['id'] == clusters['topic']['id'])
        shared_coauthor_cluster = (source_clusters['coauthor']['id'] != 'unconnected' and
                                   source_clusters['coauthor']['id'] == clusters['coauthor']['id'])
        shared_institution_cluster = (source_clusters['institution']['id'] != 'unconnected' and
                                      source_clusters['institution']['id'] == clusters['institution']['id'])
        shared_topics = set(source_topics).intersection(person_topics[cid])
        if not (shared_topic_cluster or shared_topics):
            continue
        topic_rank = sorted(shared_topics, key=lambda tid: (-min(source_topics[tid], person_topics[cid][tid]), topics.get(tid, tid)))
        score = (5 * shared_topic_cluster + 2 * shared_coauthor_cluster + shared_institution_cluster +
                 min(len(shared_topics), 4) + min(sum(min(source_topics[t], person_topics[cid][t]) for t in shared_topics), 8) / 4)
        reasons = []
        if shared_topic_cluster:
            reasons.append('Same topic-network cluster')
        if shared_coauthor_cluster:
            reasons.append('Same co-author-network cluster')
        if shared_institution_cluster:
            reasons.append('Same publication-affiliation cluster')
        if shared_topics:
            reasons.append('Research topics in common')
        candidates.append((score, candidate['label'].lower(), cid, {
            'id': cid, 'name': candidate['label'], 'reasons': reasons,
            'shared_topics': [topics.get(tid, tid) for tid in topic_rank[:5]],
            'paper_count': len(person_papers[cid]),
        }))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return {'person': {'id': person_id, 'name': source['label'], 'paper_count': len(source_papers)},
            'suggestions': [item[3] for item in candidates[:10]],
            'scope': 'No shared authored paper in this included OpenAlex corpus; not a claim about all publications.'}


def query(statement, parameters=None):
    line = next(x for x in AUTH_FILE.read_text().splitlines() if x.startswith('NEO4J_AUTH='))
    user, password = line.removeprefix('NEO4J_AUTH=').split('/', 1)
    auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
    request = Request(NEO4J, json.dumps({'statement': statement, 'parameters': parameters or {}}).encode(),
                      {'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'})
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if payload.get('errors'):
        raise RuntimeError('Neo4j query failed')
    fields = payload['data']['fields']
    return [dict(zip(fields, values)) for values in payload['data']['values']]


def search(term, kind):
    term = term.strip()[:100].lower()
    if len(term) < 2:
        return []
    label = {'institution': 'UKIEInstitution', 'topic': 'UKIETopic'}.get(kind, 'UKIEPerson')
    qualifier = 'n.target' if kind == 'institution' else ('null' if kind == 'topic' else 'n.qualifying')
    condition = 'true'
    return query(f'''MATCH (n:{label}) WHERE {condition} AND toLower(n.name) CONTAINS $q
                   RETURN n.id AS id, n.name AS name, {qualifier} AS qualifying
                   ORDER BY CASE WHEN toLower(n.name) STARTS WITH $q THEN 0 ELSE 1 END, n.name LIMIT 30''', {'q': term})


def person(person_id, include_shared=False):
    centre = query('MATCH (p:UKIEPerson {id:$id}) RETURN p.id AS id,p.name AS name,p.orcid AS orcid,p.qualifying AS qualifying', {'id': person_id})
    if not centre:
        return None
    collaborators = query('''MATCH (p:UKIEPerson {id:$id})-[r:UKIE_COAUTHORED]-(n:UKIEPerson)
        RETURN n.id AS id,n.name AS name,n.qualifying AS qualifying,r.paper_count AS weight,
               r.paper_ids AS paper_ids,r.years AS years ORDER BY weight DESC,n.name LIMIT 65''', {'id': person_id})
    affiliations = query('''MATCH (p:UKIEPerson {id:$id})-[r:UKIE_AFFILIATED_ON_PAPER]->(i:UKIEInstitution)
        RETURN i.id AS id,i.name AS name,i.target AS target, count(DISTINCT r.paper_id) AS weight,
               collect(DISTINCT r.paper_id)[0..25] AS paper_ids, collect(DISTINCT toString(r.publication_date))[0..25] AS dates,
               collect(DISTINCT r.raw_affiliation)[0..10] AS raw_affiliations
        ORDER BY weight DESC LIMIT 35''', {'id': person_id})
    topics = query('''MATCH (p:UKIEPerson {id:$id})-[:UKIE_AUTHORED]->(w:UKIEPaper)-[:UKIE_HAS_TOPIC]->(t:UKIETopic)
        RETURN t.id AS id,t.name AS name,count(DISTINCT w.id) AS weight,
               collect(DISTINCT w.id)[0..25] AS paper_ids
        ORDER BY weight DESC,t.name LIMIT 20''', {'id': person_id})
    papers = query('''MATCH (p:UKIEPerson {id:$id})-[:UKIE_AUTHORED]->(w:UKIEPaper)
        RETURN DISTINCT w.id AS id,w.title AS title,toString(w.publication_date) AS date,
               w.doi AS doi,w.openalex_id AS openalex ORDER BY date DESC LIMIT 35''', {'id': person_id})
    shared = query('''MATCH (p:UKIEPerson {id:$id})-[a:UKIE_AFFILIATED_ON_PAPER]->(i:UKIEInstitution)<-[b:UKIE_AFFILIATED_ON_PAPER]-(n:UKIEPerson)
        WHERE i.target = true AND n <> p AND a.publication_date.year = b.publication_date.year
        WITH n,i,collect(DISTINCT toString(a.publication_date.year)) AS years,
             collect(DISTINCT a.paper_id) AS papers_a,collect(DISTINCT b.paper_id) AS papers_b
        RETURN n.id AS id,n.name AS name,i.name AS institution,years,
               papers_a[0..25] AS paper_ids_a,papers_b[0..25] AS paper_ids_b
        ORDER BY size(years) DESC,n.name LIMIT 55''', {'id': person_id}) if include_shared else []
    return {'centre': centre[0], 'collaborators': collaborators, 'affiliations': affiliations,
            'topics': topics, 'papers': papers, 'shared': shared}


def institution(institution_id):
    centre = query('MATCH (i:UKIEInstitution {id:$id}) RETURN i.id AS id,i.name AS name,i.ror AS ror,i.country AS country,i.target AS target', {'id': institution_id})
    if not centre:
        return None
    people = query('''MATCH (p:UKIEPerson)-[r:UKIE_AFFILIATED_ON_PAPER]->(i:UKIEInstitution {id:$id})
        RETURN p.id AS id,p.name AS name,count(DISTINCT r.paper_id) AS weight,
               collect(DISTINCT r.paper_id)[0..25] AS paper_ids,
               collect(DISTINCT toString(r.publication_date))[0..25] AS dates,
               collect(DISTINCT r.raw_affiliation)[0..10] AS raw_affiliations
        ORDER BY weight DESC,p.name LIMIT 75''', {'id': institution_id})
    papers = query('''MATCH (p:UKIEPerson)-[r:UKIE_AFFILIATED_ON_PAPER]->(i:UKIEInstitution {id:$id})
        MATCH (w:UKIEPaper {id:r.paper_id})
        RETURN DISTINCT w.id AS id,w.title AS title,toString(w.publication_date) AS date,
               w.doi AS doi,w.openalex_id AS openalex ORDER BY date DESC LIMIT 35''', {'id': institution_id})
    return {'centre': centre[0], 'people': people, 'papers': papers}


def topic(topic_id):
    centre = query('MATCH (t:UKIETopic {id:$id}) RETURN t.id AS id,t.name AS name,t.field AS field,t.subfield AS subfield,t.openalex_id AS openalex', {'id': topic_id})
    if not centre:
        return None
    related = query('''MATCH (t:UKIETopic {id:$id})-[r:UKIE_TOPIC_COOCCURS]-(n:UKIETopic)
        RETURN n.id AS id,n.name AS name,n.field AS field,r.paper_count AS weight,r.paper_ids AS paper_ids
        ORDER BY weight DESC,n.name LIMIT 60''', {'id': topic_id})
    papers = query('''MATCH (w:UKIEPaper)-[r:UKIE_HAS_TOPIC]->(t:UKIETopic {id:$id})
        RETURN w.id AS id,w.title AS title,toString(w.publication_date) AS date,
               w.doi AS doi,w.openalex_id AS openalex,r.score AS score,r.primary AS primary
        ORDER BY score DESC,date DESC LIMIT 40''', {'id': topic_id})
    return {'centre': centre[0], 'related': related, 'papers': papers}


def paper(paper_id):
    rows = query('''MATCH (w:UKIEPaper {id:$id})
        OPTIONAL MATCH (p:UKIEPerson)-[a:UKIE_AUTHORED]->(w)
        RETURN w.id AS id,w.title AS title,toString(w.publication_date) AS date,w.doi AS doi,
               w.openalex_id AS openalex,p.id AS person_id,p.name AS person_name,a.position AS position
        ORDER BY position LIMIT 300''', {'id': paper_id})
    if not rows:
        return None
    topics = query('''MATCH (w:UKIEPaper {id:$id})-[r:UKIE_HAS_TOPIC]->(t:UKIETopic)
        RETURN t.id AS id,t.name AS name,r.score AS score,r.primary AS primary
        ORDER BY score DESC''', {'id': paper_id})
    return {'authors': rows, 'topics': topics}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith('/api/'):
                params = parse_qs(parsed.query)
                parts = path.strip('/').split('/')
                if parts[1] == 'search':
                    body = search(params.get('q', [''])[0], params.get('kind', ['person'])[0])
                elif parts[1] == 'overview' and len(parts) == 2:
                    country = params.get('country', ['island'])[0]
                    view = params.get('view', ['full'])[0]
                    snapshot = snapshot_file(country, view)
                    if snapshot:
                        data = snapshot.read_bytes()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Content-Encoding', 'gzip')
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    full = country_overview(country)
                    body = people_view(full) if view == 'people' else full
                elif parts[1] == 'topic-overview' and len(parts) == 2:
                    body = topic_overview()
                elif parts[1] == 'matchmaker' and len(parts) == 3 and parts[2] == 'search':
                    body = matchmaker_search(params.get('q', [''])[0])
                elif parts[1] == 'matchmaker' and len(parts) == 3:
                    body = matchmaker(parts[2])
                elif len(parts) == 3 and parts[1] == 'person':
                    body = person(parts[2], params.get('shared', ['0'])[0] == '1')
                elif len(parts) == 3 and parts[1] == 'institution':
                    body = institution(parts[2])
                elif len(parts) == 3 and parts[1] == 'topic':
                    body = topic(parts[2])
                elif len(parts) == 3 and parts[1] == 'paper':
                    body = paper(parts[2])
                else:
                    return self.send_error(404)
                data = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(200 if body is not None else 404)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
            else:
                files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                         '/style.css': ('style.css', 'text/css'),
                         '/force-graph.js': ('../../../qbit-mini-ui/china-graph/foam-graph.js', 'text/javascript')}
                if path not in files:
                    return self.send_error(404)
                file, mime = files[path]
                data = (HERE / file).resolve().read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_error(500, 'Graph service error')

    def log_message(self, format, *args):
        if not self.path.startswith('/api/search'):
            super().log_message(format, *args)


if __name__ == '__main__':
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
