// Upgrade the initial affiliation relationships to byline-position identity.
// This modifies only relationships created by this Irish graph import.
LOAD CSV WITH HEADERS FROM 'file:///irish-economists-graph/paper_affiliations.csv' AS row
CALL (row) {
  MATCH (a:IrishPerson {id: row.person_id})-[r:IRISH_AFFILIATED_ON_PAPER {paper_id: row.paper_id}]->
        (i:IrishInstitution {id: row.institution_id})
  WHERE r.position IS NULL
  SET r.position = toInteger(row.position)
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
