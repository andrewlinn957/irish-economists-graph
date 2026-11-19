// Isolated Irish labels: these queries do not touch the China graph's GraphRun/GraphNode labels.
CREATE CONSTRAINT irish_person_id IF NOT EXISTS FOR (n:IrishPerson) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT irish_paper_id IF NOT EXISTS FOR (n:IrishPaper) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT irish_institution_id IF NOT EXISTS FOR (n:IrishInstitution) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT irish_topic_id IF NOT EXISTS FOR (n:IrishTopic) REQUIRE n.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/people.csv' AS row
CALL (row) {
  MERGE (p:IrishPerson {id: row.person_id})
  SET p.name = row.name, p.openalex_id = row.openalex_id,
      p.orcid = row.orcid, p.qualifying = (row.qualifying = '1')
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/institutions.csv' AS row
CALL (row) {
  MERGE (i:IrishInstitution {id: row.institution_id})
  SET i.name = row.name, i.ror = row.ror,
      i.country_code = row.country_code, i.target = (row.target = '1')
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/papers.csv' AS row
CALL (row) {
  MERGE (p:IrishPaper {id: row.paper_id})
  SET p.title = row.title, p.publication_date = date(row.publication_date),
      p.type = row.type, p.doi = row.doi,
      p.openalex_id = row.openalex_id,
      p.primary_field = row.primary_field,
      p.author_count = toInteger(row.author_count)
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/authorships.csv' AS row
CALL (row) {
  MATCH (a:IrishPerson {id: row.person_id}), (p:IrishPaper {id: row.paper_id})
  MERGE (a)-[r:IRISH_AUTHORED {position: toInteger(row.position)}]->(p)
  SET r.raw_name = row.raw_name,
      r.target_institution_ids = split(row.target_institution_ids, '|')
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/paper_affiliations.csv' AS row
CALL (row) {
  MATCH (a:IrishPerson {id: row.person_id}), (i:IrishInstitution {id: row.institution_id})
  MERGE (a)-[r:IRISH_AFFILIATED_ON_PAPER {paper_id: row.paper_id, position: toInteger(row.position)}]->(i)
  SET r.publication_date = date(row.publication_date),
      r.raw_affiliation = row.raw_affiliation, r.source = row.source
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/coauthored.csv' AS row
CALL (row) {
  MATCH (a:IrishPerson {id: row.person_a}), (b:IrishPerson {id: row.person_b})
  MERGE (a)-[r:IRISH_COAUTHORED]->(b)
  SET r.paper_count = toInteger(row.paper_count),
      r.paper_ids = split(row.paper_ids, '|'), r.years = split(row.years, '|')
} IN TRANSACTIONS OF 500 ROWS;

// This means both authors published with the same institutional byline in
// at least one common calendar year, NOT verified overlapping employment.
LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/shared_institution_year.csv' AS row
CALL (row) {
  MATCH (a:IrishPerson {id: row.person_a}), (b:IrishPerson {id: row.person_b})
  MERGE (a)-[r:IRISH_SHARED_INSTITUTION_YEAR {institution_id: row.institution_id}]->(b)
  SET r.years = split(row.years, '|'),
      r.paper_ids_a = split(row.paper_ids_a, '|'),
      r.paper_ids_b = split(row.paper_ids_b, '|')
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/topics.csv' AS row
CALL (row) {
  MERGE (t:IrishTopic {id: row.topic_id})
  SET t.name = row.name, t.openalex_id = row.openalex_id,
      t.field = row.field, t.subfield = row.subfield
} IN TRANSACTIONS OF 500 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/paper_topics.csv' AS row
CALL (row) {
  MATCH (p:IrishPaper {id: row.paper_id}), (t:IrishTopic {id: row.topic_id})
  MERGE (p)-[r:IRISH_HAS_TOPIC]->(t)
  SET r.score = toFloat(row.score), r.primary = (row.primary = '1')
} IN TRANSACTIONS OF 500 ROWS;

// Derived projection: each link retains all papers carrying both topics.
LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/topic_cooccurs.csv' AS row
CALL (row) {
  MATCH (a:IrishTopic {id: row.topic_a}), (b:IrishTopic {id: row.topic_b})
  MERGE (a)-[r:IRISH_TOPIC_COOCCURS]->(b)
  SET r.paper_count = toInteger(row.paper_count),
      r.paper_ids = split(row.paper_ids, '|')
} IN TRANSACTIONS OF 500 ROWS;
