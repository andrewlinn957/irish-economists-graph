# Irish economists' publication network

## What this is

A publication-evidenced graph for **1 January 2012 to 18 November 2026**. The qualifying set is people whose *individual paper authorship* lists at least one target institution: universities on the island of Ireland, the Economic and Social Research Institute (ESRI), or the Central Bank of Ireland. Authors outside those institutions are retained as collaborators.

The actual work-level source is **OpenAlex**, not a scrape of RePEc HTML. RePEc [discourages website scraping](https://ideas.repec.org/getdata.html), and its [API is not a bulk-download facility](https://ideas.repec.org/api.html). RePEc's [EDIRC Ireland directory](https://edirc.repec.org/ireland.html) informed institution scope. The RePEc Author Service's institution affiliations are generally author-maintained *current* affiliations, so they cannot establish affiliation at publication ([RePEc explanation](https://blog.repec.org/2011/04/26/about-author-affiliations/)). OpenAlex [authorship records](https://help.openalex.org/data/authorships/) retain byline affiliation strings and resolved institution IDs on each paper. No RePEc-handle crosswalk has yet been made, and this should not be described as a complete RePEc census.

## Inclusion and evidence

- OpenAlex works of type `article`, `preprint` or `report` within the date window, with primary topic field `Economics, Econometrics and Finance` (field ID `20`). This is an operational economics definition, not a claim that every RePEc paper is covered.
- A person qualifies only when their *own* authorship on an included work lists a target institution. Merely co-authoring with a qualifying person does not establish Irish affiliation.
- Publication-time affiliation means the institution shown or resolved on the work's authorship record. Its paper ID, date, raw affiliation string and institution ID are retained on `IRISH_AFFILIATED_ON_PAPER`; it is not inferred from a present-day profile. Missing or incorrect byline metadata remain possible.
- RePEc and OpenAlex can each omit papers, misclassify a topic, split or merge an author, or fail to resolve an institution. The graph is not an exhaustive list of every Irish economist.
- Historical predecessor institutions of technological universities are separate IDs. They have not been silently merged into successor institutions. The institution list is in `collect.py` and the exact API queries in `raw/openalex/query-*.json`.

## Graph model

`IrishPerson` —[`IRISH_AUTHORED`, with byline position]→ `IrishPaper`.

`IrishPerson` —[`IRISH_AFFILIATED_ON_PAPER`, with paper ID, date and raw affiliation]→ `IrishInstitution`.

This edge exists for **all** resolved publication-time affiliations, including external coauthors and non-Irish institutions. An unresolved byline string is not turned into an institution node.

`IrishPaper` —[`IRISH_HAS_TOPIC`, with OpenAlex score and primary flag]→ `IrishTopic`.

`IrishTopic` —[`IRISH_TOPIC_COOCCURS`, with count and supporting paper IDs]→ `IrishTopic` when the topics appear on the same included paper. This is a derived projection, not a semantic or causal claim.

`IRISH_COAUTHORED` is a derived person-to-person edge with all supporting paper IDs and a paper count. A large collaboration generates many pairwise edges, so centrality calculations should weight each shared paper by its team size if large consortia are not meant to dominate.

`IRISH_SHARED_INSTITUTION_YEAR` is a derived person-to-person edge only when both people have *publication bylines* naming the same institution in at least one common calendar year. It retains each person's supporting paper IDs. It does **not** prove their employment dates overlapped.

The paper and affiliation edges are the source of truth; the person-person edges are reproducible projections. OpenAlex author IDs are used where available. Because missing author IDs previously created one paper-scoped person per byline, the build now resolves only evidence-linked duplicates: a matching ORCID or byline email, or compatible names with a shared publication institution and co-author. An unresolved byline can also join a unique ORCID-bearing OpenAlex identity with a compatible name and publication institution. Conflicting ORCIDs or two bylines on the same paper block a merge. Reviewed exceptions are listed in `identity-overrides.json`; every applied alias and reason is exported in `output/identity-resolution.csv`. This is not a blanket same-name merge, and residual same-name records are not assumed to be one person. OpenAlex records that literally name `ESRI` as a person byline are excluded from the person graph; the raw source records remain archived.

## Artefacts and reproducibility

- `collect.py fetch` and `collect.py fetch_extra` are the preserved 2016–2026 series. `collect.py fetch_backfill` and `collect.py fetch_backfill_extra` collect 2012 to 17 November 2016 into the separate `raw/openalex/backfill-2012/` directory. `collect.py build` combines both periods. Fetching is sequential with retries; completed page files are reused. Re-run on a new date or with a changed query in a **new directory** rather than mixing cached pages from different queries.
- `raw/openalex/works-*.json.gz`, `extra-*.json.gz`, `backfill-2012/*.json.gz` and `full/*.json.gz` preserve source responses. The five original full-work records repair 100-author list truncations. Three backfill list records also hit the 100-author limit, but none had a primary economics field, so they are excluded by the same rule.
- `output-2016-2026/` preserves the prior derived export locally before the extended-period rebuild. It is excluded from GitHub because the current export and the source responses already cover the extended period.
- `output/summary.json` records counts, query parameters and raw-file SHA-256 hashes.
- `output/people.csv`, `papers.csv`, `institutions.csv`, `authorships.csv`, `paper_affiliations.csv`, `coauthored.csv`, and `shared_institution_year.csv` are the derived authorship graph. `topics.csv`, `paper_topics.csv` and `topic_cooccurs.csv` are the topic layer. `topic-summary.json` records their counts and hashes. `collect.py build` runs the topic derivation from the preserved work records.
- `output/irish-economists.graphml` is a manageable Gephi/yEd visual projection: qualifying people, target institutions, qualifying-person co-authorships and evidence-backed person–institution links. The full network, including external collaborators and shared-institution-year edges, remains in Neo4j and CSV.
- `neo4j-import.cypher` loads these into distinct `Irish*` labels and `IRISH_*` relationships; it does not touch China graph labels or run IDs.

## Private viewer

The read-only ForceGraph viewer runs at `http://100.116.32.107:8127/` on Tailscale, served by `irish-economists-ui.service`. Its overview combines qualifying people and target institutions from GraphML with topics and their links from the derived CSVs. It opens as an unclustered people-only co-authorship network. The left panel can add institution and topic nodes or select a co-authorship, topic or institution clustering lens; a slider then chooses how many of the largest algorithmic communities appear. Search and focused views continue to reach the full Neo4j graph, including external collaborators and their publication-time affiliations. Link inspection retains supporting paper IDs and available raw byline strings. The optional shared-institution-year layer is explicitly provisional evidence of publication bylines, not employment overlap.

Implementation: `ui/server.py`, `ui/index.html`, `ui/app.js`, and `ui/style.css`. The service binds only to the server's Tailscale IP and exposes no write API. It reads the existing root-owned Neo4j auth file at runtime; credentials are not copied into the UI project. This is an OpenAlex-backed graph, not yet a complete RePEc census.

The light-mode viewer computes three separate, deterministic weighted label-propagation partitions from co-authorship, author/topic and affiliation links. These are exploratory communities, not observed affiliations. The left panel controls the lens, cluster count, node/link visibility and label visibility. Institution community circles use abbreviations; person circles use full representative names and topic circles use short readable titles. The right-hand selection inspector is collapsible.

## GitHub Pages edition

Public snapshot: https://andrewlinn957.github.io/irish-economists-graph/

`python3 build_pages.py` generates `docs/`, a read-only snapshot of the same graph UI. It preserves the overview, search, focused person/institution/topic/paper views, and Matchmaker results without exposing Neo4j or requiring a public API. The snapshot is not live: rebuild and publish it after a corpus update. The `docs/data/` JSON files contain public bibliographic metadata, including source byline affiliation strings.

## Useful Cypher

```cypher
// Most frequent co-authorships involving a qualifying person
MATCH (a:IrishPerson)-[r:IRISH_COAUTHORED]-(b:IrishPerson)
WHERE a.qualifying AND a.id < b.id
RETURN a.name, b.name, r.paper_count, r.paper_ids
ORDER BY r.paper_count DESC LIMIT 25;

// Publication-evidenced ESRI authors
MATCH (p:IrishPerson)-[r:IRISH_AFFILIATED_ON_PAPER]->
      (i:IrishInstitution {id:'I132389103'})
RETURN p.name, collect(DISTINCT r.paper_id) AS supporting_papers
ORDER BY p.name;
```
