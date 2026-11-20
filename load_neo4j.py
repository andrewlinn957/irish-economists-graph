#!/usr/bin/env python3
"""Replace only the Irish graph layer from a validated CSV build."""
import argparse
import base64
import csv
import json
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
AUTH_FILE = Path('/root/.config/china-pra-neo4j/auth.env')
ENDPOINT = 'http://100.116.32.107:7474/db/neo4j/query/v2'
CONTAINER = 'china-pra-neo4j'
IMPORT_DIR = '/var/lib/neo4j/import/irish-economists-graph'
FILES = ['people', 'papers', 'institutions', 'authorships', 'paper_affiliations',
         'coauthored', 'shared_institution_year', 'topics', 'paper_topics', 'topic_cooccurs']
LABELS = ['IrishPerson', 'IrishPaper', 'IrishInstitution', 'IrishTopic']
COUNTS = {
    'IrishPerson': 'people', 'IrishPaper': 'papers',
    'IrishInstitution': 'institutions', 'IrishTopic': 'topics',
}


def query(statement, auth):
    req = Request(ENDPOINT, json.dumps({'statement': statement}).encode(),
                  {'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'})
    with urlopen(req, timeout=1800) as response:
        payload = json.load(response)
    if payload.get('errors'):
        raise RuntimeError(payload['errors'])
    data = payload['data']
    return [dict(zip(data['fields'], row)) for row in data['values']]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output')
    parser.add_argument('--namespace', choices=['Irish', 'UKIE'], default='Irish',
                        help='Keep the UK and Ireland candidate separate from the existing Irish layer')
    parser.add_argument('--replace', action='store_true', help='Explicitly replace Irish labels and edges')
    args = parser.parse_args()
    labels = [label.replace('Irish', args.namespace) for label in LABELS]
    counts = {label.replace('Irish', args.namespace): source for label, source in COUNTS.items()}
    if not args.replace:
        parser.error('Pass --replace to modify Neo4j')
    output = args.output_dir.resolve()
    expected = {}
    for name in FILES:
        path = output / f'{name}.csv'
        with path.open(newline='', encoding='utf-8') as fh:
            expected[name] = sum(1 for _ in csv.DictReader(fh))
    if not expected['people'] or not expected['papers']:
        raise RuntimeError('Refusing empty Irish graph replacement')
    user, password = next(line.removeprefix('NEO4J_AUTH=').split('/', 1)
                          for line in AUTH_FILE.read_text().splitlines()
                          if line.startswith('NEO4J_AUTH='))
    auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
    subprocess.run(['docker', 'exec', CONTAINER, 'mkdir', '-p', IMPORT_DIR], check=True)
    for name in FILES:
        subprocess.run(['docker', 'cp', str(output / f'{name}.csv'),
                        f'{CONTAINER}:{IMPORT_DIR}/{name}.csv'], check=True)
    print('Staged CSV counts:', expected, flush=True)
    relations = {
        'IRISH_AUTHORED': 'authorships',
        'IRISH_AFFILIATED_ON_PAPER': 'paper_affiliations',
        'IRISH_COAUTHORED': 'coauthored',
        'IRISH_SHARED_INSTITUTION_YEAR': 'shared_institution_year',
        'IRISH_HAS_TOPIC': 'paper_topics',
        'IRISH_TOPIC_COOCCURS': 'topic_cooccurs',
    }
    # Delete bounded relationship batches before nodes. A high-degree author
    # can otherwise make even a 500-node DETACH DELETE exceed Neo4j's
    # transaction memory pool on this VPS.
    for relation in relations:
        relation = relation.replace('IRISH_', f'{args.namespace.upper()}_')
        removed = 0
        while True:
            count = query(f'MATCH ()-[r:{relation}]->() WITH r LIMIT 2000 DELETE r RETURN count(*) AS count', auth)[0]['count']
            removed += count
            if count < 2000:
                break
        print(f'Cleared {relation}: {removed} relationships', flush=True)
    for label in labels:
        before = query(f'MATCH (n:{label}) RETURN count(n) AS count', auth)[0]['count']
        print(f'Replacing {label}: {before} existing', flush=True)
        while True:
            deleted = query(f'MATCH (n:{label}) WITH n LIMIT 500 DETACH DELETE n RETURN count(*) AS count', auth)[0]['count']
            if not deleted:
                break
        print(f'Cleared {label}', flush=True)
    script = (ROOT / 'neo4j-import.cypher').read_text()
    if args.namespace == 'UKIE':
        script = script.replace('Irish', 'UKIE').replace('IRISH_', 'UKIE_').replace('irish_', 'ukie_')
    statements = [part.strip() for part in script.split(';') if part.strip()]
    for number, statement in enumerate(statements, 1):
        query(statement, auth)
        print(f'Imported statement {number}/{len(statements)}', flush=True)
    for label, source in counts.items():
        actual = query(f'MATCH (n:{label}) RETURN count(n) AS count', auth)[0]['count']
        if actual != expected[source]:
            raise RuntimeError(f'{label}: expected {expected[source]}, got {actual}')
    for rel, source in relations.items():
        if args.namespace == 'UKIE':
            rel = rel.replace('IRISH_', 'UKIE_')
        actual = query(f'MATCH ()-[r:{rel}]->() RETURN count(r) AS count', auth)[0]['count']
        if actual != expected[source]:
            raise RuntimeError(f'{rel}: expected {expected[source]}, got {actual}')
    print(f'All {args.namespace} node and relationship counts reconcile.', flush=True)


if __name__ == '__main__':
    main()
