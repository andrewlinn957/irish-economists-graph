// Topic co-occurrence traversal. The same frozen evidence is used on Pages and Tailscale.
(() => {
  const $ = selector => document.querySelector(selector);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const selected = new Map();
  let network, adjacency, loading;

  async function loadNetwork() {
    if (network) return network;
    if (loading) return loading;
    loading = (async () => {
      const data = window.staticGraphGet
        ? await window.staticGraphGet('/api/topic-path-data')
        : await fetch('/api/topic-path-data').then(response => {
            if (!response.ok) throw Error('Unable to load topic evidence');
            return response.json();
          });
      network = data;
      adjacency = new Map(data.topics.map(topic => [topic.id, []]));
      for (const link of data.links) {
        if (!adjacency.has(link.a) || !adjacency.has(link.b)) continue;
        adjacency.get(link.a).push({to: link.b, link});
        adjacency.get(link.b).push({to: link.a, link});
      }
      for (const neighbours of adjacency.values()) neighbours.sort((a,b) => b.link.papers-a.link.papers || a.to.localeCompare(b.to));
      return data;
    })();
    try { return await loading; } catch (error) { loading = null; throw error; }
  }

  // Breadth-first traversal guarantees the fewest topic-to-topic steps.
  // Among routes of equal length, favour more supporting papers on the bridges.
  function shortestFrom(start) {
    const distance = new Map([[start, 0]]), strength = new Map([[start, 0]]), previous = new Map();
    const queue = [start];
    for (let i = 0; i < queue.length; i++) {
      const from = queue[i];
      for (const {to, link} of adjacency.get(from) || []) {
        const nextDistance = distance.get(from) + 1;
        const nextStrength = strength.get(from) + Math.log1p(link.papers);
        if (!distance.has(to)) {
          distance.set(to, nextDistance);
          strength.set(to, nextStrength);
          previous.set(to, {from, link});
          queue.push(to);
        } else if (distance.get(to) === nextDistance && nextStrength > strength.get(to)) {
          strength.set(to, nextStrength);
          previous.set(to, {from, link});
        }
      }
    }
    return {distance, strength, previous};
  }

  function connection(a, b, traversal) {
    if (!traversal.distance.has(b)) return null;
    const nodes = [b], links = [];
    let cursor = b;
    while (cursor !== a) {
      const step = traversal.previous.get(cursor);
      if (!step) return null;
      links.unshift(step.link);
      cursor = step.from;
      nodes.unshift(cursor);
    }
    return {a, b, nodes, links, hops: links.length, strength: traversal.strength.get(b)};
  }

  function connectingRoutes(ids) {
    const candidates = [];
    for (let i = 0; i < ids.length; i++) {
      const traversal = shortestFrom(ids[i]);
      for (let j = i + 1; j < ids.length; j++) {
        const route = connection(ids[i], ids[j], traversal);
        if (route) candidates.push(route);
      }
    }
    candidates.sort((a,b) => a.hops-b.hops || b.strength-a.strength || a.a.localeCompare(b.a) || a.b.localeCompare(b.b));
    const parent = new Map(ids.map(id => [id, id]));
    const root = id => { while (parent.get(id) !== id) id = parent.get(id); return id; };
    const routes = [];
    for (const route of candidates) {
      const a = root(route.a), b = root(route.b);
      if (a !== b) { parent.set(b, a); routes.push(route); }
    }
    const connected = new Set(routes.flatMap(route => [route.a, route.b]));
    return {routes, disconnected: ids.filter(id => !connected.has(id))};
  }

  function updateSelected() {
    $('#topic-path-selected').innerHTML = [...selected.values()].map(topic =>
      `<button type="button" data-remove-topic="${safe(topic.id)}" title="Remove ${safe(topic.name)}">${safe(topic.name)} <span aria-hidden="true">×</span></button>`).join('');
    $('#topic-path-run').disabled = selected.size < 2;
  }

  function showPicks() {
    if (!network) return;
    if (selected.size >= 8) { $('#topic-path-picks').hidden = true; return; }
    const term = $('#topic-path-search').value.trim().toLocaleLowerCase();
    if (term.length < 2) { $('#topic-path-picks').hidden = true; return; }
    const matches = network.topics.filter(topic => !selected.has(topic.id) && topic.name.toLocaleLowerCase().includes(term))
      .sort((a,b) => Number(!a.name.toLocaleLowerCase().startsWith(term))-Number(!b.name.toLocaleLowerCase().startsWith(term))
        || b.papers-a.papers || a.name.localeCompare(b.name)).slice(0,20);
    $('#topic-path-picks').innerHTML = matches.map(topic =>
      `<button type="button" data-add-topic="${safe(topic.id)}">${safe(topic.name)}<span>${topic.papers.toLocaleString()} papers</span></button>`).join('')
      || '<p>No matching topics</p>';
    $('#topic-path-picks').hidden = false;
  }

  function renderRoute(route, topics) {
    const weaker = route.links.map((link,i) => ({link,i, ratio: link.papers / Math.max(1, Math.min(topics.get(route.nodes[i]).papers, topics.get(route.nodes[i+1]).papers))}))
      .sort((a,b) => a.ratio-b.ratio || a.link.papers-b.link.papers)[0];
    const steps = route.nodes.map((id,i) => {
      const topic = topics.get(id);
      const bridge = i ? route.links[i-1] : null;
      return `${bridge ? `<div class="topic-bridge ${weaker?.i===i-1?'thin':''}"><span>↓ ${bridge.papers.toLocaleString()} shared paper${bridge.papers===1?'':'s'}</span>
        ${bridge.examples?.length ? `<span class="bridge-evidence">${bridge.examples.map(paper => `<a href="https://openalex.org/${encodeURIComponent(paper)}" target="_blank" rel="noopener">${safe(paper)}</a>`).join(' · ')}</span>` : ''}</div>` : ''}
        <div class="topic-step"><strong>${safe(topic.name)}</strong><span>${topic.papers.toLocaleString()} paper${topic.papers===1?'':'s'}</span></div>`;
    }).join('');
    return `<article class="topic-route"><h2>${safe(topics.get(route.a).name)} → ${safe(topics.get(route.b).name)}</h2>
      <p>${route.hops} topic link${route.hops===1?'':'s'} · fewest-hop route; ties favour better-supported links</p>${steps}
      <p class="topic-path-note">Thinnest bridge on this route: ${weaker.link.papers.toLocaleString()} shared papers, ${Math.round(weaker.ratio*100)}% of the less prevalent topic's papers. This is a lead to inspect, not proof of a research gap.</p></article>`;
  }

  function run() {
    const ids = [...selected.keys()];
    if (ids.length < 2 || !network) return;
    const topics = new Map(network.topics.map(topic => [topic.id, topic]));
    const {routes, disconnected} = connectingRoutes(ids);
    $('#topic-path-results').innerHTML = `<h2>Connecting topics</h2><p>${safe(network.scope)} Each topic count is distinct papers tagged with that topic; each link count is papers tagged with both topics.</p>
      ${routes.map(route => renderRoute(route, topics)).join('') || '<p>No supported route connects these topics in this corpus.</p>'}
      ${disconnected.length ? `<p class="topic-path-note">No supported route found for: ${disconnected.map(id => safe(topics.get(id).name)).join(', ')}.</p>` : ''}
      <p class="topic-path-note">For three or more selected topics, this is a compact network of pairwise shortest routes, not a unique shortest path or an exact minimum Steiner tree. OpenAlex topic assignments and the corpus boundary can create or hide apparent gaps.</p>`;
  }

  window.hideTopicPathView = () => {
    document.body.classList.remove('topic-path-mode');
    $('main').classList.remove('topic-path-mode');
    $('#topic-path-view').hidden = true;
    $('#topic-path-tab').classList.remove('active');
    $('#topic-path-tab').setAttribute('aria-pressed', 'false');
  };
  window.showTopicPathView = async () => {
    document.body.classList.remove('matchmaker-mode');
    $('main').classList.remove('matchmaker-mode');
    $('#matchmaker-view').hidden = true;
    $('#matchmaker-tab').classList.remove('active');
    $('#matchmaker-tab').setAttribute('aria-pressed','false');
    $('#overview').classList.remove('active');
    $('#overview').setAttribute('aria-pressed','false');
    document.body.classList.add('topic-path-mode');
    $('main').classList.add('topic-path-mode');
    $('#topic-path-view').hidden = false;
    $('#topic-path-tab').classList.add('active');
    $('#topic-path-tab').setAttribute('aria-pressed','true');
    $('#topic-path-results').innerHTML = network ? $('#topic-path-results').innerHTML : '<p>Loading topic evidence…</p>';
    try {
      await loadNetwork();
      if ($('#topic-path-results').textContent === 'Loading topic evidence…') $('#topic-path-results').innerHTML = '';
      $('#topic-path-search').focus();
    } catch (error) { $('#topic-path-results').innerHTML = `<p class="error">${safe(error.message)}</p>`; }
  };

  $('#topic-path-search').addEventListener('input', showPicks);
  $('#topic-path-picks').addEventListener('click', event => {
    const button = event.target.closest('[data-add-topic]');
    if (!button || selected.size >= 8) return;
    const topic = network.topics.find(item => item.id === button.dataset.addTopic);
    if (!topic) return;
    selected.set(topic.id, topic);
    $('#topic-path-search').value = '';
    $('#topic-path-picks').hidden = true;
    updateSelected();
  });
  $('#topic-path-selected').addEventListener('click', event => {
    const button = event.target.closest('[data-remove-topic]');
    if (!button) return;
    selected.delete(button.dataset.removeTopic);
    updateSelected();
  });
  $('#topic-path-run').addEventListener('click', run);
})();
