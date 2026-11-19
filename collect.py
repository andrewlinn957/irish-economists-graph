#!/usr/bin/env python3
"""Collect an evidenced Irish-economics authorship graph from OpenAlex.

RePEc's public HTML is deliberately not scraped. See README for source limits.
"""

import csv
import gzip
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "openalex"
BACKFILL = RAW / "backfill-2012"
OUT = ROOT / "output"
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


def short_id(uri):
    return (uri or "").rsplit("/", 1)[-1]


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    target_ids = set(INSTITUTIONS)
    people = {}
    institutions = {}
    papers = {}
    authorships = []
    paper_affiliations = []
    coauthored = defaultdict(lambda: {"papers": set(), "years": set()})
    shared = defaultdict(lambda: {"papers": set(), "years": set()})
    raw_files = sorted(RAW.glob("works-*.json.gz")) + sorted(RAW.glob("extra-*.json.gz")) + sorted(BACKFILL.glob("works-*.json.gz")) + sorted(BACKFILL.glob("extra-*.json.gz"))
    if not raw_files:
        raise RuntimeError("No downloaded OpenAlex work pages")
    api_counts = {}
    seen_work = set()
    affiliation_year_members = defaultdict(lambda: defaultdict(set))
    for raw_file in raw_files:
        with gzip.open(raw_file, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        prefix = ("backfill-" if raw_file.parent == BACKFILL else "") + raw_file.name.split("-", 1)[0]
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
            year = dt[:4]
            paper_authors = []
            qualifying_authors = defaultdict(set)
            for pos, a in enumerate(work.get("authorships") or []):
                author = a.get("author") or {}
                person_id = short_id(author.get("id")) or f"unresolved:{pid}:{pos}"
                name = a.get("raw_author_name") or author.get("display_name") or "Unknown"
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
                    institutions[iid] = {"institution_id": iid,
                                         "name": inst.get("display_name") or INSTITUTIONS.get(iid, ""),
                                         "ror": inst.get("ror") or "",
                                         "country_code": inst.get("country_code") or "",
                                         "target": int(iid in target_ids)}
                    if iid in target_ids:
                        matched.add(iid)
                        people[person_id]["qualifying"] = 1
                        qualifying_authors[iid].add(person_id)
                        affiliation_year_members[(iid, year)][person_id].add(pid)
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
            for pair in combinations(sorted(set(paper_authors)), 2):
                coauthored[pair]["papers"].add(pid)
                coauthored[pair]["years"].add(year)
            for iid, members in qualifying_authors.items():
                for pair in combinations(sorted(members), 2):
                    shared[(pair[0], pair[1], iid)]["papers"].add(pid)
                    shared[(pair[0], pair[1], iid)]["years"].add(year)

    valid_papers = set(papers)
    authorships = [r for r in authorships if r["paper_id"] in valid_papers]
    paper_affiliations = [r for r in paper_affiliations if r["paper_id"] in valid_papers]
    valid_people = {r["person_id"] for r in authorships}
    valid_institutions = {r["institution_id"] for r in paper_affiliations}
    people = {k: v for k, v in people.items() if k in valid_people}
    institutions = {k: v for k, v in institutions.items() if k in valid_institutions}
    co_rows = [{"person_a": a, "person_b": b, "paper_count": len(v["papers"]),
                "paper_ids": "|".join(sorted(v["papers"])), "years": "|".join(sorted(v["years"]))}
               for (a, b), v in sorted(coauthored.items())]
    # Same year is a co-observed publication affiliation, NOT proof of
    # overlapping employment dates. Retain each author's supporting papers.
    affiliation_pairs = defaultdict(lambda: {"years": set(), "papers_a": set(), "papers_b": set()})
    for (iid, year), members in affiliation_year_members.items():
        for a, b in combinations(sorted(members), 2):
            row = affiliation_pairs[(a, b, iid)]
            row["years"].add(year)
            row["papers_a"].update(members[a])
            row["papers_b"].update(members[b])
    shared_rows = [{"person_a": a, "person_b": b, "institution_id": iid,
                    "years": "|".join(sorted(v["years"])),
                    "paper_ids_a": "|".join(sorted(v["papers_a"])),
                    "paper_ids_b": "|".join(sorted(v["papers_b"]))}
                   for (a, b, iid), v in sorted(affiliation_pairs.items())]
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
        ("relation", "edge", "relation", "string"),
        ("weight", "edge", "weight", "int"),
        ("paper_ids", "edge", "paper_ids", "string"),
    ]:
        ET.SubElement(root, f"{{{ns}}}key", id=kid, **{"for": scope, "attr.name": name, "attr.type": typ})
    graph = ET.SubElement(root, f"{{{ns}}}graph", id="irish-economists", edgedefault="undirected")

    def item(parent, key, value):
        ET.SubElement(parent, f"{{{ns}}}data", key=key).text = str(value)

    qpeople = {pid for pid, person in people.items() if person["qualifying"]}
    for pid in sorted(qpeople):
        n = ET.SubElement(graph, f"{{{ns}}}node", id="person:" + pid)
        item(n, "label", people[pid]["name"])
        item(n, "kind", "person")
    for iid in sorted(target_ids & set(institutions)):
        n = ET.SubElement(graph, f"{{{ns}}}node", id="institution:" + iid)
        item(n, "label", institutions[iid]["name"])
        item(n, "kind", "institution")
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
    hashes.update({"full/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((RAW / "full").glob("*.json.gz"))})
    hashes.update({"backfill-2012/full/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((BACKFILL / "full").glob("*.json.gz"))})
    summary = {"period_start": START, "period_end": END, "source": "OpenAlex API",
               "inclusion": "primary topic field 20: Economics, Econometrics and Finance; article/preprint/report; target institution in individual authorship",
               "source_query": [json.loads(p.read_text()) for p in sorted(RAW.glob("query-*.json")) + sorted(BACKFILL.glob("query-*.json"))],
               "api_query_counts": api_counts, "raw_pages": len(raw_files),
               "raw_sha256": hashes, "papers": len(papers), "people": len(people),
               "qualifying_people": sum(v["qualifying"] for v in people.values()),
               "institutions": len(institutions), "authorships": len(authorships),
               "paper_affiliations": len(paper_affiliations), "coauthor_pairs": len(co_rows),
               "same_year_same_institution_pairs": len(shared_rows)}
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
    p.add_argument("stage", choices=["fetch", "fetch_extra", "fetch_backfill", "fetch_backfill_extra", "build"])
    args = p.parse_args()
    if args.stage.startswith("fetch"):
        fetch(extra="extra" in args.stage, backfill="backfill" in args.stage)
    else:
        build()
