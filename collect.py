#!/usr/bin/env python3
"""Collect an evidenced Irish-economics authorship graph from OpenAlex.

RePEc's public HTML is deliberately not scraped. See README for source limits.
"""

import csv
import gzip
import hashlib
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "openalex"
BACKFILL = RAW / "backfill-2012"
UK_RAW = RAW / "uk"
OUT = Path(os.environ.get("ECON_GRAPH_OUTPUT", ROOT / "output"))
START = "2012-01-01"
END = "2026-11-18"
ORIGINAL_START = "2016-11-18"
BACKFILL_END = "2016-11-17"
BASE = "https://api.openalex.org"

# Institution IDs are OpenAlex identities, not name matches. Historical TU
# predecessors are included because the query covers the preceding decade.
INSTITUTIONS = {
    "I100930933": "University College Dublin",
    "I205274468": "Trinity College Dublin",
    "I27577105": "University College Cork",
    "I188760350": "University of Galway",
    "I230495080": "University of Limerick",
    "I42934936": "Dublin City University",
    "I157286207": "Maynooth University",
    "I142762351": "Royal College of Surgeons in Ireland",
    "I4210144925": "Technological University Dublin",
    "I4387153685": "Dublin Institute of Technology",
    "I4387153671": "Institute of Technology Tallaght",
    "I4387155068": "Institute of Technology Blanchardstown",
    "I4387152698": "Atlantic Technological University",
    "I63871047": "Galway-Mayo Institute of Technology",
    "I82288201": "Institute of Technology Sligo",
    "I18452974": "Letterkenny Institute of Technology",
    "I4387156359": "South East Technological University",
    "I4387152804": "Technological University of the Shannon",
    "I151939572": "Athlone Institute of Technology",
    "I882645478": "Limerick Institute of Technology",
    "I4210100923": "Munster Technological University",
    "I4387155865": "Institute of Technology Tralee",
    "I4387154713": "Cork Institute of Technology",
    "I7478328": "Waterford Institute of Technology",
    "I70277191": "Institute of Technology Carlow",
    "I126231945": "Queen's University Belfast",
    "I138801177": "Ulster University",
    "I4405260289": "Ulster University, Derry-Londonderry Campus",
    "I132389103": "Economic and Social Research Institute",
    "I29745156": "Central Bank of Ireland",
}
EXTRA_IDS = {"I4387154713", "I7478328", "I70277191", "I4405260289"}


def api_get(session, path, params):
    for attempt in range(7):
        response = session.get(BASE + path, params=params, timeout=90)
        if response.status_code == 200:
            return response.json(), response.url
        if response.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"OpenAlex HTTP {response.status_code}: {response.text[:300]}")
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"OpenAlex HTTP {response.status_code} after retries")


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def fetch(extra=False, backfill=False):
    source_dir = BACKFILL if backfill else RAW
    source_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "IrishEconomistsGraph/0.1 (research metadata; polite sequential requests)"
    ids = "|".join(sorted(EXTRA_IDS) if extra else [x for x in INSTITUTIONS if x not in EXTRA_IDS])
    filters = (
        f"from_publication_date:{START if backfill else ORIGINAL_START},"
        f"to_publication_date:{BACKFILL_END if backfill else END},"
        f"authorships.institutions.id:{ids},topics.field.id:20,"
        "type:article|preprint|report"
    )
    query = {"filter": filters, "per-page": 200, "page": 1, "select":
             "id,title,publication_date,doi,type,authorships,primary_topic,topics,ids,is_retracted"}
    prefix = "extra" if extra else "works"
    save_json(source_dir / f"query-{prefix}.json", {"endpoint": BASE + "/works", "params": query,
                                   "retrieved": date.today().isoformat()})
    page = 1
    while True:
        target = source_dir / f"{prefix}-{page:04d}.json.gz"
        if target.exists():
            with gzip.open(target, "rt") as fh:
                payload = json.load(fh)
        else:
            payload, url = api_get(session, "/works", query)
            payload["_retrieval_url"] = url
            with gzip.open(target, "wt", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            print(f"fetched page {page}: {len(payload['results'])} works", flush=True)
        total = payload.get("meta", {}).get("count", 0)
        if page * 200 >= total or not payload.get("results"):
            break
        page += 1
        query["page"] = page
        time.sleep(0.15)
    print(f"fetch complete: {page} pages", flush=True)


def fetch_uk():
    """Archive UK-affiliated economics-primary works, partitioned by year."""
    session = requests.Session()
    session.headers["User-Agent"] = "UKIrelandEconomistsGraph/0.1 (research metadata; polite sequential requests)"
    for year in range(2012, 2027):
        folder = UK_RAW / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        query = {"filter": (
            f"from_publication_date:{year}-01-01,"
            f"to_publication_date:{END if year == 2026 else str(year) + '-12-31'},"
            "authorships.institutions.country_code:GB,primary_topic.field.id:20,"
            "type:article|preprint|report"),
            "per-page": 200, "page": 1,
            "select": "id,title,publication_date,doi,type,authorships,primary_topic,topics,ids,is_retracted"}
        manifest = folder / "query.json"
        frozen = {"endpoint": BASE + "/works", "params": query}
        if manifest.exists():
            recorded = json.loads(manifest.read_text())
            if recorded.get("endpoint") != frozen["endpoint"] or recorded.get("params") != query:
                raise RuntimeError(f"UK query changed for {year}; use a new archive directory")
        else:
            save_json(manifest, {**frozen, "retrieved": date.today().isoformat()})
        page = 1
        while True:
            target = folder / f"works-{page:04d}.json.gz"
            if target.exists():
                with gzip.open(target, "rt", encoding="utf-8") as fh:
                    payload = json.load(fh)
            else:
                payload, url = api_get(session, "/works", query)
                payload["_retrieval_url"] = url
                with gzip.open(target, "wt", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False)
                print(f"UK {year} page {page}: {len(payload['results'])} works", flush=True)
            total = payload.get("meta", {}).get("count", 0)
            if total > 10000:
                raise RuntimeError(f"UK {year}: {total} results exceed page pagination limit")
            if page * 200 >= total or not payload.get("results"):
                break
            page += 1
            query["page"] = page
            time.sleep(0.15)
        print(f"UK {year}: {total} candidate works archived", flush=True)


def fetch_uk_institutions():
    """Archive OpenAlex UK institution geography to classify the four nations."""
    folder = UK_RAW / "institutions"
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "UKIrelandEconomistsGraph/0.1 (research metadata; polite sequential requests)"
    query = {"filter": "country_code:GB", "per-page": 200, "page": 1,
             "select": "id,display_name,ror,geo,country_code"}
    manifest = folder / "query.json"
    if manifest.exists():
        recorded = json.loads(manifest.read_text())
        if recorded.get("params") != query:
            raise RuntimeError("UK institution query changed; use a new archive directory")
    else:
        save_json(manifest, {"endpoint": BASE + "/institutions", "params": query,
                             "retrieved": date.today().isoformat()})
    page = 1
    while True:
        target = folder / f"institutions-{page:04d}.json.gz"
        if target.exists():
            with gzip.open(target, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        else:
            payload, url = api_get(session, "/institutions", query)
            payload["_retrieval_url"] = url
            with gzip.open(target, "wt", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            print(f"UK institutions page {page}", flush=True)
        total = payload.get("meta", {}).get("count", 0)
        if page * 200 >= total or not payload.get("results"):
            break
        page += 1
        query["page"] = page
        time.sleep(0.15)
    print(f"UK institutions: {total} archived", flush=True)


def fetch_uk_full_authorships():
    """Preserve full work records where list results truncate at 100 bylines."""
    session = requests.Session()
    session.headers["User-Agent"] = "UKIrelandEconomistsGraph/0.1 (research metadata; polite sequential requests)"
    count = 0
    for page in sorted(UK_RAW.glob("[0-9][0-9][0-9][0-9]/works-*.json.gz")):
        with gzip.open(page, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        for work in payload.get("results", []):
            if len(work.get("authorships") or []) < 100:
                continue
            wid = short_id(work["id"])
            target = page.parent / "full" / f"{wid}.json.gz"
            if target.exists():
                continue
            full, url = api_get(session, f"/works/{wid}", {})
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(target, "wt", encoding="utf-8") as fh:
                json.dump({"work": full, "_retrieval_url": url}, fh, ensure_ascii=False)
            count += 1
            time.sleep(0.15)
    print(f"Archived {count} full UK work records", flush=True)


def short_id(uri):
    return (uri or "").rsplit("/", 1)[-1]


def write_csv(path, fields, rows):
    def neo4j_csv_safe(row):
        # OpenAlex occasionally supplies literal backslash-quote escapes or a
        # trailing backslash. Neo4j's LOAD CSV treats those as quote escapes,
        # whereas Python's CSV writer uses doubled quotes. Keep the untouched
        # source response in raw/ and normalise only the import projection.
        return {key: (value.replace('\\"', '"').replace("\\'", "'").rstrip('\\')
                      if isinstance(value, str) else value)
                for key, value in row.items()}
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(neo4j_csv_safe(row) for row in rows)


def uk_institution_geography():
    pages = sorted((UK_RAW / "institutions").glob("institutions-*.json.gz"))
    if not pages:
        raise RuntimeError("UK institution geography archive is missing")
    metadata = {}
    expected = None
    for page in pages:
        with gzip.open(page, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        expected = payload.get("meta", {}).get("count")
        for inst in payload.get("results", []):
            metadata[short_id(inst.get("id"))] = inst
    if len(metadata) != expected:
        raise RuntimeError(f"UK institution archive incomplete: {len(metadata)} of {expected}")
    return metadata


def person_name_key(name):
    """Comparable first/last name, never by itself sufficient for a merge."""
    plain = ''.join(c for c in unicodedata.normalize('NFKD', name.casefold())
                    if not unicodedata.combining(c))
    words = re.findall(r"[a-z]+", plain)
    if len(words) < 2:
        return None
    return words[0], words[-1]


def institution_graph_label(name, country_code, city):
    """Short display label only when the university's name is its city."""
    prefix = 'University of '
    if not name.startswith(prefix) or country_code not in {'GB', 'IE'}:
        return name
    suffix = name[len(prefix):]
    irish_cities = {'Dublin', 'Galway', 'Limerick', 'Cork', 'Belfast'}
    if (city and suffix.casefold() == city.strip().casefold()) or (country_code == 'IE' and suffix in irish_cities):
        return suffix
    return name


def middle_names_compatible(a, b):
    def middle(name):
        plain = ''.join(c for c in unicodedata.normalize('NFKD', name.casefold())
                        if not unicodedata.combining(c))
        return re.findall(r'[a-z]+', plain)[1:-1]
    left, right = middle(a), middle(b)
    return not left or not right or (len(left) == len(right) and
                                     all(x[0] == y[0] for x, y in zip(left, right)))


def resolve_person_identities(people, authorships, affiliations):
    """Merge only evidenced duplicate IDs; retain an alias receipt for audit."""
    by_paper = defaultdict(list)
    papers_by_person = defaultdict(set)
    institutions_by_person = defaultdict(set)
    email_by_person = defaultdict(set)
    byline_names = defaultdict(set)
    for row in authorships:
        by_paper[row['paper_id']].append(row['person_id'])
        papers_by_person[row['person_id']].add(row['paper_id'])
        byline_names[row['person_id']].add(row['raw_name'].strip().casefold())
    for row in affiliations:
        pid = row['person_id']
        institutions_by_person[pid].add(row['institution_id'])
        for address in re.findall(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}', row['raw_affiliation'].casefold()):
            if any(part in address.split('@')[0] for part in person_name_key(people[pid]['name']) or ()):
                email_by_person[pid].add(address)
    coauthors_by_person = defaultdict(set)
    for members in by_paper.values():
        for pid in members:
            coauthors_by_person[pid].update(
                person_name_key(people[other]['name']) for other in members
                if other != pid and person_name_key(people[other]['name']))

    parent = {pid: pid for pid in people}
    component_papers = {pid: set(papers_by_person[pid]) for pid in people}
    component_orcids = {pid: ({people[pid]['orcid']} if people[pid]['orcid'] else set()) for pid in people}
    reasons = {}

    def root(pid):
        while parent[pid] != pid:
            parent[pid] = parent[parent[pid]]
            pid = parent[pid]
        return pid

    def merge(a, b, reason):
        a, b = root(a), root(b)
        if (a == b or component_papers[a] & component_papers[b] or
                len(component_orcids[a] | component_orcids[b]) > 1):
            return
        if b < a:
            a, b = b, a
        parent[b] = a
        component_papers[a].update(component_papers[b])
        component_orcids[a].update(component_orcids[b])
        reasons[b] = reason

    groups = defaultdict(list)
    for pid, person in people.items():
        key = person_name_key(person['name'])
        if key:
            groups[key].append(pid)
    for ids in groups.values():
        for a, b in combinations(sorted(ids), 2):
            if not middle_names_compatible(people[a]['name'], people[b]['name']):
                continue
            if people[a]['orcid'] and people[b]['orcid'] and people[a]['orcid'] != people[b]['orcid']:
                continue
            if not (a.startswith('unresolved:') or b.startswith('unresolved:')):
                # Preserve distinct OpenAlex identities unless a stable identifier agrees.
                if not (people[a]['orcid'] and people[a]['orcid'] == people[b]['orcid']):
                    continue
            shared_orcid = people[a]['orcid'] and people[a]['orcid'] == people[b]['orcid']
            shared_email = email_by_person[a] & email_by_person[b]
            shared_coauthor = coauthors_by_person[a] & coauthors_by_person[b]
            shared_institution = institutions_by_person[a] & institutions_by_person[b]
            if shared_orcid:
                merge(a, b, 'same byline ORCID')
            elif shared_email:
                merge(a, b, 'same byline email')
            elif shared_institution and shared_coauthor:
                merge(a, b, 'same first/last name, publication institution and co-author name')

    for ids in groups.values():
        resolved_roots = {root(pid) for pid in ids if people[pid]['openalex_id']}
        if len(resolved_roots) != 1:
            continue
        anchor_root = next(iter(resolved_roots))
        if not component_orcids[anchor_root]:
            continue
        anchor = next(pid for pid in ids if root(pid) == anchor_root and people[pid]['orcid'])
        for pid in ids:
            if pid == anchor or not pid.startswith('unresolved:'):
                continue
            if (middle_names_compatible(people[anchor]['name'], people[pid]['name']) and
                    institutions_by_person[anchor] & institutions_by_person[pid] and
                    (not people[pid]['orcid'] or people[pid]['orcid'] == people[anchor]['orcid'])):
                merge(anchor, pid, 'unique ORCID-bearing OpenAlex identity with matching name and publication institution')

    # An OpenAlex display name may be an initial even when its paper bylines
    # spell out the full name. Link an unresolved full-name byline only when
    # publication institution AND a named coauthor also agree, and the
    # full-name alias identifies exactly one resolved candidate.
    aliases = defaultdict(set)
    for pid, person in people.items():
        if person['openalex_id']:
            for name in byline_names[pid]:
                if len(re.findall(r'[a-z]+', name)) >= 2:
                    aliases[name].add(pid)
    for pid, person in people.items():
        if not pid.startswith('unresolved:'):
            continue
        candidates = [other for other in aliases[person['name'].strip().casefold()]
                      if institutions_by_person[pid] & institutions_by_person[other]
                      and coauthors_by_person[pid] & coauthors_by_person[other]
                      and not papers_by_person[pid] & papers_by_person[other]]
        roots = {root(other) for other in candidates}
        if len(roots) == 1:
            merge(pid, next(iter(roots)), 'full-name byline alias, shared publication institution and coauthor')

    override_groups = json.loads((ROOT / 'identity-overrides.json').read_text())['groups']
    explicit = {}
    for group in override_groups:
        present = [pid for pid in group['source_ids'] if pid in people]
        if not present:
            continue
        name_keys = {person_name_key(people[pid]['name']) for pid in present}
        if len(name_keys) != 1:
            preferred = group['preferred_name'].strip().casefold()
            if not all(preferred in byline_names[pid] for pid in present):
                raise ValueError(f"Override has incompatible names without matching full bylines: {group['canonical_id']}")
            shared_institutions = set.intersection(*(institutions_by_person[pid] for pid in present))
            if not shared_institutions:
                raise ValueError(f"Override lacks a shared publication institution: {group['canonical_id']}")
        if len(set(present)) != len(present):
            raise ValueError(f"Override repeats a source ID: {group['canonical_id']}")
        paper_sets = [papers_by_person[pid] for pid in present]
        if any(x & y for x, y in combinations(paper_sets, 2)):
            raise ValueError(f"Override contains same-paper bylines: {group['canonical_id']}")
        for pid in present:
            if pid in explicit:
                raise ValueError(f"Overlapping identity overrides: {pid}")
            explicit[pid] = group
        for pid in present[1:]:
            merge(present[0], pid, 'reviewed identity override')
        if len({root(pid) for pid in present}) != 1:
            raise ValueError(f"Override could not merge all source IDs: {group['canonical_id']}")

    components = defaultdict(list)
    for pid in people:
        components[root(pid)].append(pid)
    mapping, audit = {}, []
    for ids in components.values():
        orcids = {people[pid]['orcid'] for pid in ids if people[pid]['orcid']}
        if len(orcids) > 1:
            raise ValueError(f"Identity component joins conflicting ORCIDs: {ids}")
        overrides = {explicit[pid]['canonical_id'] for pid in ids if pid in explicit}
        if len(overrides) > 1:
            raise ValueError(f"Identity component joins conflicting overrides: {sorted(overrides)}")
        canonical = next(iter(overrides)) if overrides else min(ids, key=lambda pid: (pid.startswith('unresolved:'), pid))
        for pid in ids:
            mapping[pid] = canonical
            if pid != canonical:
                audit.append({'source_person_id': pid, 'canonical_person_id': canonical,
                              'name': people[pid]['name'],
                              'reason': explicit[pid]['reason'] if pid in explicit else reasons.get(pid, 'evidence-linked component')})
    resolved_people = {}
    for pid, person in people.items():
        canonical = mapping[pid]
        if canonical not in resolved_people:
            resolved_people[canonical] = {**person, 'person_id': canonical}
        other = resolved_people[canonical]
        other['qualifying'] = int(bool(other['qualifying']) or bool(person['qualifying']))
        if not other['openalex_id'] and person['openalex_id']:
            other['openalex_id'] = person['openalex_id']
        if not other['orcid'] and person['orcid']:
            other['orcid'] = person['orcid']
    for group in override_groups:
        if group['canonical_id'] in resolved_people:
            resolved_people[group['canonical_id']]['name'] = group['preferred_name']
    for row in authorships:
        row['person_id'] = mapping[row['person_id']]
    for row in affiliations:
        row['person_id'] = mapping[row['person_id']]
    write_csv(OUT / 'identity-resolution.csv',
              ['source_person_id', 'canonical_person_id', 'name', 'reason'],
              sorted(audit, key=lambda row: row['source_person_id']))
    return resolved_people, mapping, len(audit)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    uk_metadata = uk_institution_geography()
    target_ids = set(INSTITUTIONS) | set(uk_metadata)
    people = {}
    institutions = {}
    papers = {}
    authorships = []
    paper_affiliations = []
    raw_files = (sorted(RAW.glob("works-*.json.gz")) + sorted(RAW.glob("extra-*.json.gz")) +
                 sorted(BACKFILL.glob("works-*.json.gz")) + sorted(BACKFILL.glob("extra-*.json.gz")) +
                 sorted(UK_RAW.glob("[0-9][0-9][0-9][0-9]/works-*.json.gz")))
    if not raw_files:
        raise RuntimeError("No downloaded OpenAlex work pages")
    for year in range(2012, 2027):
        pages = sorted((UK_RAW / str(year)).glob("works-*.json.gz"))
        if not pages:
            raise RuntimeError(f"UK {year} archive is missing")
        if [p.name for p in pages] != [f"works-{i:04d}.json.gz" for i in range(1, len(pages) + 1)]:
            raise RuntimeError(f"UK {year} archive has a missing page")
        with gzip.open(pages[-1], "rt", encoding="utf-8") as fh:
            last = json.load(fh)
        if len(pages) * 200 < last.get("meta", {}).get("count", 0):
            raise RuntimeError(f"UK {year} archive is incomplete")
    api_counts = {}
    seen_work = set()
    for raw_file in raw_files:
        with gzip.open(raw_file, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        prefix = ("uk-" + raw_file.parent.name + "-" if raw_file.parent.parent == UK_RAW else
                  "backfill-" if raw_file.parent == BACKFILL else "") + raw_file.name.split("-", 1)[0]
        api_counts.setdefault(prefix, payload.get("meta", {}).get("count", 0))
        for work in payload["results"]:
            if work.get("is_retracted"):
                continue
            pid = short_id(work["id"])
            if pid in seen_work:
                continue
            seen_work.add(pid)
            if short_id(((work.get("primary_topic") or {}).get("field") or {}).get("id")) != "20":
                continue
            full_path = raw_file.parent / "full" / f"{pid}.json.gz"
            if full_path.exists():
                with gzip.open(full_path, "rt", encoding="utf-8") as full_fh:
                    work = json.load(full_fh)["work"]
            dt = work.get("publication_date") or ""
            if not (START <= dt <= END):
                continue
            paper_authors = []
            qualifying_authors = defaultdict(set)
            for pos, a in enumerate(work.get("authorships") or []):
                author = a.get("author") or {}
                name = a.get("raw_author_name") or author.get("display_name") or "Unknown"
                # OpenAlex occasionally encodes the institute acronym as a
                # person byline (sometimes repeatedly on one work).
                if name.strip().casefold() in {'esri', 'economic and social research institute'}:
                    continue
                person_id = short_id(author.get("id")) or f"unresolved:{pid}:{pos}"
                if person_id not in people:
                    people[person_id] = {"person_id": person_id, "name": name,
                                         "openalex_id": author.get("id") or "",
                                         "orcid": author.get("orcid") or "",
                                         "qualifying": 0}
                matched = set()
                for inst in a.get("institutions") or []:
                    iid = short_id(inst.get("id"))
                    if not iid:
                        continue
                    geo = (uk_metadata.get(iid) or {}).get("geo") or {}
                    country_code = inst.get("country_code") or geo.get("country_code") or ""
                    country = (geo.get("region") or "United Kingdom (unclassified)") if country_code == "GB" else (
                        "Ireland" if country_code == "IE" else "Other")
                    institutions[iid] = {"institution_id": iid,
                                         "name": inst.get("display_name") or INSTITUTIONS.get(iid, ""),
                                         "graph_label": institution_graph_label(
                                             inst.get("display_name") or INSTITUTIONS.get(iid, ""),
                                             country_code, geo.get("city") or ""),
                                         "ror": inst.get("ror") or "",
                                         "country_code": country_code,
                                         "country": country,
                                         "target": int(iid in target_ids or country_code == "GB")}
                    if iid in target_ids or country_code == "GB":
                        target_ids.add(iid)
                        matched.add(iid)
                        people[person_id]["qualifying"] = 1
                        qualifying_authors[iid].add(person_id)
                    paper_affiliations.append({"person_id": person_id, "paper_id": pid,
                                               "institution_id": iid, "position": pos + 1,
                                               "publication_date": dt,
                                               "raw_affiliation": " | ".join(a.get("raw_affiliation_strings") or []),
                                               "source": "OpenAlex authorship"})
                authorships.append({"person_id": person_id, "paper_id": pid,
                                    "position": pos + 1, "raw_name": name,
                                    "target_institution_ids": "|".join(sorted(matched))})
                paper_authors.append(person_id)
            # API filter matches any authorship. Do not qualify all co-authors.
            if not qualifying_authors:
                continue
            papers[pid] = {"paper_id": pid, "title": work.get("title") or "",
                           "publication_date": dt, "type": work.get("type") or "",
                           "doi": work.get("doi") or "", "openalex_id": work["id"],
                           "primary_field": ((work.get("primary_topic") or {}).get("field") or {}).get("display_name") or "",
                           "author_count": len(paper_authors)}

    valid_papers = set(papers)
    authorships = [r for r in authorships if r["paper_id"] in valid_papers]
    paper_affiliations = [r for r in paper_affiliations if r["paper_id"] in valid_papers]
    valid_people = {r["person_id"] for r in authorships}
    valid_institutions = {r["institution_id"] for r in paper_affiliations}
    people = {k: v for k, v in people.items() if k in valid_people}
    institutions = {k: v for k, v in institutions.items() if k in valid_institutions}
    people, _, merged_id_count = resolve_person_identities(people, authorships, paper_affiliations)
    coauthored = defaultdict(lambda: {"papers": set(), "years": set()})
    authors_by_paper = defaultdict(set)
    for row in authorships:
        authors_by_paper[row['paper_id']].add(row['person_id'])
    for pid, members in authors_by_paper.items():
        for pair in combinations(sorted(members), 2):
            coauthored[pair]['papers'].add(pid)
            coauthored[pair]['years'].add(papers[pid]['publication_date'][:4])
    co_rows = [{"person_a": a, "person_b": b, "paper_count": len(v["papers"]),
                "paper_ids": "|".join(sorted(v["papers"])), "years": "|".join(sorted(v["years"]))}
               for (a, b), v in sorted(coauthored.items())]
    # A UK-wide institution-year clique can contain millions of derived pairs.
    # Preserve the publication-affiliation edges; compute this optional view
    # for a selected person on demand instead of materialising a misleading clique.
    shared_rows = []
    write_csv(OUT / "people.csv", list(next(iter(people.values()))), people.values())
    write_csv(OUT / "institutions.csv", list(next(iter(institutions.values()))), institutions.values())
    write_csv(OUT / "papers.csv", list(next(iter(papers.values()))), papers.values())
    write_csv(OUT / "authorships.csv", list(authorships[0]), authorships)
    write_csv(OUT / "paper_affiliations.csv", list(paper_affiliations[0]), paper_affiliations)
    write_csv(OUT / "coauthored.csv", ["person_a", "person_b", "paper_count", "paper_ids", "years"], co_rows)
    write_csv(OUT / "shared_institution_year.csv", ["person_a", "person_b", "institution_id", "years", "paper_ids_a", "paper_ids_b"], shared_rows)
    # Manageable visual projection for Gephi/yEd: qualifying people,
    # their target institutions and coauthorships among qualifying people.
    ns = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}graphml")
    for kid, scope, name, typ in [
        ("label", "node", "label", "string"),
        ("kind", "node", "kind", "string"),
        ("country", "node", "country", "string"),
        ("countries", "node", "countries", "string"),
        ("relation", "edge", "relation", "string"),
        ("weight", "edge", "weight", "int"),
        ("paper_ids", "edge", "paper_ids", "string"),
    ]:
        ET.SubElement(root, f"{{{ns}}}key", id=kid, **{"for": scope, "attr.name": name, "attr.type": typ})
    graph = ET.SubElement(root, f"{{{ns}}}graph", id="uk-ireland-economists", edgedefault="undirected")

    def item(parent, key, value):
        ET.SubElement(parent, f"{{{ns}}}data", key=key).text = str(value)

    qpeople = {pid for pid, person in people.items() if person["qualifying"]}
    person_countries = defaultdict(set)
    for affiliation in paper_affiliations:
        iid = affiliation["institution_id"]
        if iid in target_ids and iid in institutions:
            person_countries[affiliation["person_id"]].add(institutions[iid]["country"])
    for pid in sorted(qpeople):
        n = ET.SubElement(graph, f"{{{ns}}}node", id="person:" + pid)
        item(n, "label", people[pid]["name"])
        item(n, "kind", "person")
        item(n, "countries", "|".join(sorted(person_countries[pid])))
    for iid in sorted(target_ids & set(institutions)):
        n = ET.SubElement(graph, f"{{{ns}}}node", id="institution:" + iid)
        item(n, "label", institutions[iid]["graph_label"])
        item(n, "kind", "institution")
        item(n, "country", institutions[iid]["country"])
    for row in co_rows:
        if row["person_a"] not in qpeople or row["person_b"] not in qpeople:
            continue
        e = ET.SubElement(graph, f"{{{ns}}}edge", source="person:" + row["person_a"],
                          target="person:" + row["person_b"])
        item(e, "relation", "coauthored")
        item(e, "weight", row["paper_count"])
        item(e, "paper_ids", row["paper_ids"])
    affiliations_by_person = defaultdict(set)
    for row in paper_affiliations:
        if row["person_id"] in qpeople and row["institution_id"] in target_ids:
            affiliations_by_person[(row["person_id"], row["institution_id"])].add(row["paper_id"])
    for (pid, iid), paper_ids in sorted(affiliations_by_person.items()):
        e = ET.SubElement(graph, f"{{{ns}}}edge", source="person:" + pid,
                          target="institution:" + iid)
        item(e, "relation", "affiliated_on_paper")
        item(e, "weight", len(paper_ids))
        item(e, "paper_ids", "|".join(sorted(paper_ids)))
    ET.ElementTree(root).write(OUT / "irish-economists.graphml", encoding="utf-8", xml_declaration=True)
    hashes = {str(p.relative_to(RAW)): hashlib.sha256(p.read_bytes()).hexdigest() for p in raw_files}
    hashes.update({str(p.relative_to(RAW)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((UK_RAW / "institutions").glob("institutions-*.json.gz"))})
    hashes.update({"full/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((RAW / "full").glob("*.json.gz"))})
    hashes.update({"backfill-2012/full/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((BACKFILL / "full").glob("*.json.gz"))})
    hashes.update({str(p.relative_to(RAW)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(UK_RAW.glob("[0-9][0-9][0-9][0-9]/full/*.json.gz"))})
    summary = {"period_start": START, "period_end": END, "source": "OpenAlex API",
               "inclusion": "primary topic field 20: Economics, Econometrics and Finance; article/preprint/report; target institution in individual authorship",
               "source_query": [json.loads(p.read_text()) for p in (sorted(RAW.glob("query-*.json")) +
                                sorted(BACKFILL.glob("query-*.json")) + sorted(UK_RAW.glob("*/query.json")))],
               "api_query_counts": api_counts, "raw_pages": len(raw_files),
               "raw_sha256": hashes, "papers": len(papers), "people": len(people),
               "identity_aliases": merged_id_count,
               "qualifying_people": sum(v["qualifying"] for v in people.values()),
               "institutions": len(institutions), "authorships": len(authorships),
               "paper_affiliations": len(paper_affiliations), "coauthor_pairs": len(co_rows),
               "same_year_same_institution_pairs": len(shared_rows),
               "shared_institution_year_mode": "derived_on_demand"}
    summary["graphml_qualified_coauthor_pairs"] = sum(
        x["person_a"] in qpeople and x["person_b"] in qpeople for x in co_rows)
    summary["graphml_affiliation_pairs"] = len(affiliations_by_person)
    save_json(OUT / "summary.json", summary)
    from enrich_topics import main as enrich_topics
    enrich_topics()
    print(json.dumps({k: v for k, v in summary.items() if k not in ("raw_sha256", "source_query")}, indent=2))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["fetch", "fetch_extra", "fetch_backfill", "fetch_backfill_extra", "fetch_uk", "fetch_uk_institutions", "fetch_uk_full", "build"])
    args = p.parse_args()
    if args.stage == "fetch_uk":
        fetch_uk()
    elif args.stage == "fetch_uk_institutions":
        fetch_uk_institutions()
    elif args.stage == "fetch_uk_full":
        fetch_uk_full_authorships()
    elif args.stage.startswith("fetch"):
        fetch(extra="extra" in args.stage, backfill="backfill" in args.stage)
    else:
        build()
