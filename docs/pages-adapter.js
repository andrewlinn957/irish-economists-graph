// Read-only GitHub Pages adapter. The same UI remains Neo4j-backed on Tailscale.
(() => {
  const cache = new Map();
  async function data(path) {
    if (path.startsWith('overview-')) {
      const country = path.slice('overview-'.length).replace(/(-people)?\.json$/, '');
      for (const key of cache.keys()) {
        if (key.startsWith('overview-') && !key.startsWith(`overview-${country}.`) && !key.startsWith(`overview-${country}-people.`)) cache.delete(key);
      }
    }
    if (!cache.has(path)) cache.set(path, fetch(`./data/${path}.gz`).then(async r => {
      if (!r.ok) throw Error('Unable to load graph data');
      if (!window.DecompressionStream) throw Error('This browser cannot read the compressed graph snapshot');
      const result = await new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).json();
      if (path.startsWith('overview-') && !path.endsWith('-people.json')) cache.delete(path.replace(/\.json$/, '-people.json'));
      return result;
    }));
    return cache.get(path);
  }
  function bucket(id) {
    let total = 0;
    for (const char of id) total += char.codePointAt(0);
    return total % 32;
  }
  function matches(rows, term, limit) {
    term = term.trim().toLowerCase().slice(0, 100);
    if (term.length < 2) return [];
    return rows.filter(row => row.name.toLowerCase().includes(term))
      .sort((a, b) => Number(!a.name.toLowerCase().startsWith(term)) - Number(!b.name.toLowerCase().startsWith(term))
        || a.name.localeCompare(b.name) || a.id.localeCompare(b.id)).slice(0, limit);
  }
  async function recommend(id) {
    const index = await data('matchmaker-index.json');
    const source = index.people[id];
    if (!source) throw Error('Researcher not found');
    const sourcePapers = new Set(source.papers), sourceTopics = source.topics;
    const candidates = [];
    for (const [cid, candidate] of Object.entries(index.people)) {
      if (cid === id || candidate.papers.some(p => sourcePapers.has(p))) continue;
      const sharedTopics = Object.keys(sourceTopics).filter(t => candidate.topics[t]);
      const a=source.communities,b=candidate.communities;
      const sameTopic=a.topic.id!=='unconnected'&&a.topic.id===b.topic.id;
      if (!sameTopic && !sharedTopics.length) continue;
      const sameCoauthor=a.coauthor.id!=='unconnected'&&a.coauthor.id===b.coauthor.id;
      const sameInstitution=a.institution.id!=='unconnected'&&a.institution.id===b.institution.id;
      const score=5*Number(sameTopic)+2*Number(sameCoauthor)+Number(sameInstitution)+
        Math.min(sharedTopics.length,4)+Math.min(sharedTopics.reduce((n,t)=>n+Math.min(sourceTopics[t],candidate.topics[t]),0),8)/4;
      sharedTopics.sort((x,y)=>Math.min(sourceTopics[y],candidate.topics[y])-Math.min(sourceTopics[x],candidate.topics[x])||
        (index.topics[x]||x).localeCompare(index.topics[y]||y));
      const reasons=[];
      if(sameTopic)reasons.push('Same topic-network cluster');
      if(sameCoauthor)reasons.push('Same co-author-network cluster');
      if(sameInstitution)reasons.push('Same publication-affiliation cluster');
      if(sharedTopics.length)reasons.push('Research topics in common');
      candidates.push({score,id:cid,name:candidate.name,reasons,
        shared_topics:sharedTopics.slice(0,5).map(t=>index.topics[t]||t),paper_count:candidate.papers.length});
    }
    candidates.sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
    return {person:{id,name:source.name,paper_count:source.papers.length},
      suggestions:candidates.slice(0,10).map(({score,...rest})=>rest),
      scope:'No shared authored paper in this included OpenAlex corpus; not a claim about all publications.'};
  }
  window.staticGraphGet = async path => {
    const url = new URL(path, location.href);
    const parts = url.pathname.split('/').filter(Boolean);
    const kind = parts[1];
    if (kind === 'overview') {
      const country = url.searchParams.get('country') || 'island';
      const suffix = url.searchParams.get('view') === 'people' ? '-people' : '';
      return data(`overview-${country}${suffix}.json`);
    }
    if (kind === 'topic-overview') return data('topic-overview.json');
    if (kind === 'topic-path-data') return data('topic-path.json');
    if (kind === 'search') {
      const catalogue = await data('catalogue.json');
      return matches(catalogue[url.searchParams.get('kind') || 'person'] || [], url.searchParams.get('q') || '', 30);
    }
    if (kind === 'matchmaker' && parts[2] === 'search') {
      const catalogue = await data('catalogue.json');
      return matches(catalogue.matchmaker, url.searchParams.get('q') || '', 20);
    }
    const id = decodeURIComponent(parts[2] || '');
    if (!id || !['person', 'institution', 'topic', 'paper', 'matchmaker'].includes(kind)) throw Error('Unknown graph record');
    if (kind === 'matchmaker') return recommend(id);
    const records = await data(`${kind}/${bucket(id)}.json`);
    const record = records[id];
    if (!record) throw Error('Graph record not found');
    if (kind === 'person' && url.searchParams.get('shared') !== '1') return {...record, shared: []};
    return record;
  };
})();
