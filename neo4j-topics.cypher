CREATE CONSTRAINT irish_topic_id IF NOT EXISTS FOR (n:IrishTopic) REQUIRE n.id IS UNIQUE;

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
