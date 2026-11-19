// Read-only GitHub Pages adapter. The same UI remains Neo4j-backed on Tailscale.
(() => {
  const cache = new Map();
  async function data(path) {
    if (!cache.has(path)) cache.set(path, fetch(`./data/${path}`).then(r => {
      if (!r.ok) throw Error('Unable to load graph data');
      return r.json();
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
  window.staticGraphGet = async path => {
    const url = new URL(path, location.href);
    const parts = url.pathname.split('/').filter(Boolean);
    const kind = parts[1];
    if (kind === 'overview') return data('overview.json');
    if (kind === 'topic-overview') return data('topic-overview.json');
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
    const records = await data(`${kind}/${bucket(id)}.json`);
    const record = records[id];
    if (!record) throw Error('Graph record not found');
    if (kind === 'person' && url.searchParams.get('shared') !== '1') return {...record, shared: []};
    return record;
  };
})();
