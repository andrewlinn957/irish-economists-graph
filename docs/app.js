const $ = s => document.querySelector(s);
const details = $('#details'), results = $('#results'), search = $('#search');
const kind = $('#kind'), host = $('#graph');
const matchSearch = $('#match-search'), matchPicks = $('#match-picks'), matchResults = $('#match-results');
let graph, selectedEdge = null, current = null, debounce, fitTimer, prominent = new Set();
let visibleNodes = new Set(['person']);
let visibleLabels = new Set(['person','institution','topic']);
let visibleEdges = new Set(['coauthor','affiliation','topic','topic_pair','shared']);
let currentNodes = [], currentLinks = [], currentNodeMap = new Map(), overviewClusters = new Map(), activeCluster = null, featuredClusters = new Set();
let overviewData = null, overviewMode = false;
const palette = ['#2e7d5b','#be6a42','#5c76b7','#9a669f','#a88727','#408d9b','#8c694d','#6b8d40','#b45271','#4b7691','#9067b0','#b2784d','#418078','#967a35','#6576a1','#907c69'];
function nodeId(n) { return typeof n === 'object' ? n.id : n; }
function communityFields(id) { const n=overviewClusters.get(id); return n ? {communities:n.communities} : {}; }
function clusterOf(n) { return n.communities?.[$('#cluster-lens').value]?.id || 'unconnected'; }
function clusterLabel(n) { return n.communities?.[$('#cluster-lens').value]?.label || 'Unconnected'; }
function hash(s) { let h=2166136261; for(const ch of s) h=Math.imul(h^ch.charCodeAt(0),16777619); return h>>>0; }
function clusterColour(n) {
  if ($('#cluster-lens').value === 'none') return {person:'#2e7d5b',institution:'#5c76b7',topic:'#be6a42'}[n.kind] || '#718277';
  return clusterOf(n)==='unconnected' ? '#aeb8b2' : palette[hash(clusterOf(n))%palette.length];
}
function clusterAbbreviation(label) {
  const words = String(label || '').split(/[^\p{L}\p{N}]+/u).filter(word => word && !/^(and|of|the|in|on|for|at|with)$/i.test(word));
  return words.slice(0, 5).map(word => word[0].toUpperCase()).join('') || '?';
}
function shortTopicTitle(title) {
  const first = String(title || '').split(/,|\s+and\s+/i)[0].trim();
  const phrase = first.split(/\s+/).length >= 2 ? first : String(title || '').split(',')[0].trim();
  if (phrase.length <= 28) return phrase;
  const words = phrase.split(/\s+/);
  let shortened = '';
  for (const word of words) {
    if (`${shortened} ${word}`.trim().length > 28) break;
    shortened = `${shortened} ${word}`.trim();
  }
  return shortened || phrase.slice(0, 28);
}
let clusterFrameLabels = [];
function drawClusterAreas(ctx, scale) {
  clusterFrameLabels = [];
  if (!overviewMode || $('#cluster-lens').value === 'none') return;
  const lens = $('#cluster-lens').value;
  const groups = new Map();
  for (const n of currentNodes) {
    const membership = n.communities?.[lens];
    if (!nodeVisible(n) || !membership || membership.derived || membership.id === 'unconnected' || !Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
    if (!groups.has(membership.id)) groups.set(membership.id, []);
    groups.get(membership.id).push(n);
  }
  const overview = scale < 1.2;
  for (const [id, members] of groups) {
    if (members.length < 2) continue;
    if (overview && !featuredClusters.has(id) && id !== activeCluster) continue;
    const cx = members.reduce((sum, n) => sum + n.x, 0) / members.length;
    const cy = members.reduce((sum, n) => sum + n.y, 0) / members.length;
    const distances = members.map(n => Math.hypot(n.x - cx, n.y - cy)).sort((a,b) => a-b);
    const radius = Math.max(22 / scale, distances[Math.floor((distances.length - 1) * .9)] + 15 / scale);
    const colour = clusterColour(members[0]);
    const selected = activeCluster === id;
    ctx.beginPath(); ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
    ctx.fillStyle = `${colour}${selected ? '20' : '0c'}`; ctx.fill();
    ctx.strokeStyle = `${colour}${selected ? 'b8' : '58'}`;
    ctx.lineWidth = (selected ? 2.5 : 1.3) / scale; ctx.stroke();
    if ((members.length < 5 || radius * scale < 32) && !selected && !(overview && featuredClusters.has(id))) continue;
    const cue = members[0].communities[lens].label;
    const label = lens === 'topic' ? shortTopicTitle(cue) : lens === 'coauthor' ? cue : clusterAbbreviation(cue);
    clusterFrameLabels.push({id, x:cx, y:cy, radius, label, colour, count:members.length});
  }
}
function drawClusterLabels(ctx, scale) {
  if (!clusterFrameLabels.length) return;
  ctx.save();
  const placed = [];
  const ordered = [...clusterFrameLabels].sort((a,b) => (a.id===activeCluster ? -1 : 0) - (b.id===activeCluster ? -1 : 0) || b.count-a.count);
  const limit = scale < 1.2 ? Math.min(30, Number($('#cluster-count').value)) : scale < 2.5 ? 40 : 80;
  let shown = 0;
  for (const {id,x,y,radius,label,colour} of ordered) {
    if (shown >= limit && id !== activeCluster) continue;
    ctx.font = `700 ${13 / scale}px sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    const width = ctx.measureText(label).width;
    const height = 21 / scale;
    const gap = 7 / scale;
    const positions = [[x,y-radius-gap],[x+radius+width/2+gap,y],[x-radius-width/2-gap,y],[x,y+radius+height+gap]];
    const position = positions.find(([px,py]) => {
      const box = {left:px-width/2-6/scale,right:px+width/2+6/scale,top:py-17/scale,bottom:py+4/scale};
      if (placed.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) return false;
      return true;
    });
    if (!position) continue;
    const [px,py] = position;
    placed.push({left:px-width/2-6/scale,right:px+width/2+6/scale,top:py-17/scale,bottom:py+4/scale});
    ctx.fillStyle = '#ffffffed';
    ctx.fillRect(px - width/2 - 6/scale, py - 17/scale, width + 12/scale, height);
    ctx.strokeStyle = `${colour}99`;
    ctx.lineWidth = 1 / scale;
    ctx.strokeRect(px - width/2 - 6/scale, py - 17/scale, width + 12/scale, height);
    ctx.fillStyle = '#294236';
    ctx.fillText(label, px, py, width);
    shown++;
  }
  ctx.restore();
}
function nodeColour(n) { return activeCluster && clusterOf(n)!==activeCluster ? '#d1d9d1' : clusterColour(n); }
function nodeVisible(n) { return visibleNodes.has(n.kind); }
function endNode(n) { return typeof n==='object'?n:currentNodeMap.get(n); }
function edgeVisible(l) { const a=endNode(l.source),b=endNode(l.target);return Boolean(a&&b&&visibleEdges.has(l.type)&&visibleNodes.has(a.kind)&&visibleNodes.has(b.kind)); }
function edgeColour(l) {
  if (selectedEdge===l) return '#b65f20';
  const a=endNode(l.source), b=endNode(l.target);
  if (activeCluster && a && b && clusterOf(a)!==activeCluster && clusterOf(b)!==activeCluster) return '#d5ddd526';
  if (overviewMode) {
    const lens=$('#cluster-lens').value;
    const same=a && b && clusterOf(a)===clusterOf(b);
    const inLens=(lens==='coauthor' && l.type==='coauthor') || (lens==='topic' && (l.type==='topic' || l.type==='topic_pair')) || (lens==='institution' && l.type==='affiliation');
    return lens === 'none' ? '#83a39470' : inLens ? same ? '#769b8160' : '#8ca99b1c' : '#9daeba0b';
  }
  return l.type==='topic_pair'||l.type==='topic'?'#b3c3d9':l.type==='shared'?'#c6b5cd':'#bdcfc0';
}
function updateLegend() {
  if ($('#cluster-lens').value === 'none') {
    $('#cluster-heading').textContent = 'No clustering';
    $('#legend-list').replaceChildren();
    return;
  }
  const counts=new Map(); for(const n of currentNodes) if(nodeVisible(n)&&clusterOf(n)!=='unconnected') counts.set(clusterOf(n),(counts.get(clusterOf(n))||0)+1);
  const rows=[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  const lens=$('#cluster-lens').selectedOptions[0].text;
  $('#cluster-heading').textContent=`${lens} · ${counts.size} clusters`;
  const limit = overviewMode ? Math.min(40, Math.max(12, Number($('#cluster-count').value))) : 12;
  $('#legend-list').innerHTML=rows.slice(0,limit).map(([name,count])=>{
    const n=currentNodes.find(n=>nodeVisible(n)&&clusterOf(n)===name);
    return `<button data-cluster="${safe(name)}" class="${name===activeCluster?'active':''}"><span class="swatch" style="background:${clusterColour(n)}"></span><span>${safe(clusterLabel(n))}</span><span class="legend-count">${count}</span></button>`;
  }).join('')+(rows.length>limit?`<div class="meta">${rows.length-limit} more communities</div>`:'');
}
function updateStyle() {
  if(!graph) return;
  graph.nodeVisibility(nodeVisible).linkVisibility(edgeVisible).nodeColor(nodeColour).linkColor(edgeColour);
  graph.nodeCanvasObject(graph.nodeCanvasObject());
  updateLegend();
}
function applyClusterLayout(reheat = true) {
  if (!graph || !window.FoamForces) return;
  const lens = $('#cluster-lens').value;
  if (lens === 'none') {
    featuredClusters = new Set();
    graph.d3Force('clusterX', null).d3Force('clusterY', null);
    const linkForce = graph.d3Force('link');
    if (linkForce) linkForce.strength(l => edgeVisible(l) ? 0.045 : 0);
    if (reheat) graph.d3ReheatSimulation();
    return;
  }
  const networkTypes = {
    coauthor: new Set(['coauthor']),
    topic: new Set(['topic', 'topic_pair']),
    institution: new Set(['affiliation'])
  }[lens];
  const linkForce = graph.d3Force('link');
  if (linkForce) linkForce.strength(l => !edgeVisible(l) ? 0 : networkTypes.has(l.type) ? 0.045 : 0.0005);
  if (!overviewMode) {
    featuredClusters = new Set();
    graph.d3Force('clusterX', null).d3Force('clusterY', null);
  } else {
    const sizes = new Map();
    for (const n of currentNodes) if (nodeVisible(n) && !n.communities?.[lens]?.derived) sizes.set(clusterOf(n), (sizes.get(clusterOf(n)) || 0) + 1);
    const groups = [...sizes].filter(([id]) => id !== 'unconnected').sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0]));
    featuredClusters = new Set(groups.map(([id]) => id));
    const centres = new Map();
    groups.forEach(([id], i) => {
      const angle = i * 2.399963229728653;
      const radius = i < 8 ? 600 : 1350 + 180 * Math.sqrt(i - 8);
      centres.set(id, {x:radius * Math.cos(angle), y:radius * Math.sin(angle)});
    });
    centres.set('unconnected', {x:1850, y:0});
    graph.d3Force('clusterX', window.FoamForces.forceX(n => centres.get(clusterOf(n))?.x || 0).strength(n => nodeVisible(n) ? featuredClusters.has(clusterOf(n)) ? 0.7 : 0.35 : 0));
    graph.d3Force('clusterY', window.FoamForces.forceY(n => centres.get(clusterOf(n))?.y || 0).strength(n => nodeVisible(n) ? featuredClusters.has(clusterOf(n)) ? 0.7 : 0.35 : 0));
  }
  if (reheat) graph.d3ReheatSimulation();
}
const safe = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const approvedUrl = s => /^https:\/\/(doi\.org|openalex\.org|orcid\.org|ror\.org)\//.test(s || '') ? s : null;
async function get(path) {
  if (window.staticGraphGet) return window.staticGraphGet(path);
  const r = await fetch(path);
  if (!r.ok) throw Error('Unable to load graph data');
  return r.json();
}
function showGraphView() {
  document.body.classList.remove('matchmaker-mode');
  $('main').classList.remove('matchmaker-mode');
  $('#matchmaker-view').hidden = true;
  $('#overview').classList.add('active');
  $('#overview').setAttribute('aria-pressed','true');
  $('#matchmaker-tab').classList.remove('active');
  $('#matchmaker-tab').setAttribute('aria-pressed','false');
  requestAnimationFrame(() => { if (graph) graph.width(host.clientWidth).height(host.clientHeight); });
}
function showMatchmakerView() {
  document.body.classList.add('matchmaker-mode');
  $('main').classList.add('matchmaker-mode');
  $('#matchmaker-view').hidden = false;
  $('#overview').classList.remove('active');
  $('#overview').setAttribute('aria-pressed','false');
  $('#matchmaker-tab').classList.add('active');
  $('#matchmaker-tab').setAttribute('aria-pressed','true');
  matchSearch.focus();
}
async function loadMatches(id) {
  matchPicks.hidden = true;
  matchResults.innerHTML = '<p>Finding potential collaborators…</p>';
  try {
    const data = await get(`/api/matchmaker/${encodeURIComponent(id)}`);
    matchResults.innerHTML = `<h2>Suggested for ${safe(data.person.name)}</h2>
      <p class="match-scope">${safe(data.scope)}</p>
      <div class="match-list">${data.suggestions.map((person,i) => `<article class="match-card">
        <div class="match-rank">${i+1}</div><div><h3>${safe(person.name)}</h3>
        <p>${person.reasons.map(safe).join(' · ')}</p>
        ${person.shared_topics.length ? `<p class="match-topics">Shared topics: ${person.shared_topics.map(safe).join(', ')}</p>` : ''}
        <button data-match-person="${safe(person.id)}">View researcher</button></div></article>`).join('') || '<p>No suitable candidate found in this corpus.</p>'}</div>`;
  } catch(e) { matchResults.innerHTML = `<p class="error">${safe(e.message)}</p>`; }
}
function error(e) { details.innerHTML = `<p class="error">${safe(e.message)}</p>`; $('#loading').hidden = true; }
function paperList(papers) {
  return `<h2>Papers</h2>${papers.map(p => `<button class="item" data-paper="${safe(p.id)}">${safe(p.title)}<span class="meta">${safe(p.date)} · ${safe(p.id)}</span></button>`).join('') || '<p>No papers in this selection.</p>'}`;
}
function renderGraph(nodes, links, overview = false) {
  $('#empty').hidden = true;
  clearTimeout(fitTimer);
  if (graph?._destructor) graph._destructor();
  graph = null; host.innerHTML = ''; selectedEdge = null; overviewMode = overview;
  currentNodes=nodes; currentLinks=links; currentNodeMap=new Map(nodes.map(n=>[n.id,n])); activeCluster=null;
  const degrees = new Map(nodes.map(n => [n.id, 0]));
  for (const l of links) { degrees.set(l.source, (degrees.get(l.source) || 0) + 1); degrees.set(l.target, (degrees.get(l.target) || 0) + 1); }
  prominent = new Set([...degrees].sort((a,b) => b[1] - a[1]).slice(0, 20).map(x => x[0]));
  graph = window.FoamGraph()(host).width(host.clientWidth).height(host.clientHeight)
    .graphData({nodes,links}).nodeId('id').backgroundColor('#f7f8f5').nodeRelSize(6)
    .onRenderFramePre(drawClusterAreas)
    .onRenderFramePost(drawClusterLabels)
    .nodeVisibility(nodeVisible).linkVisibility(edgeVisible).nodeColor(nodeColour)
    .nodeLabel(n => $('#cluster-lens').value === 'none' ? n.label : `${n.label} · ${$('#cluster-lens').value} cluster: ${clusterLabel(n)}${n.communities?.[$('#cluster-lens').value]?.derived?' (associated)':''}`).nodeCanvasObjectMode(() => 'after')
    .nodeCanvasObject((n, ctx, scale) => {
      if(!nodeVisible(n) || !visibleLabels.has(n.kind)) return;
      if(overviewMode && scale < 1.2) return;
      if(activeCluster && clusterOf(n)!==activeCluster && scale<1.7) return;
      if (overviewMode && scale < 1.15 && n.kind !== 'institution' && !prominent.has(n.id)) return;
      ctx.font = `${11 / scale}px sans-serif`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillStyle = '#263c2e';
      ctx.fillText(n.label, n.x + 7 / scale, n.y);
    })
    .linkColor(edgeColour)
    .linkLineDash(l => l.type === 'shared' ? [5,3] : [])
    .linkWidth(l => selectedEdge === l ? 5 : overviewMode ? Math.max(0.5, Math.min(1.4, Math.sqrt(l.weight || 1) * 0.6)) : Math.max(1, Math.min(2.5, Math.sqrt(l.weight || 1))))
    .onNodeClick(n => open(n.kind, n.id)).onLinkClick(l => {
      selectedEdge = l; graph.linkColor(graph.linkColor()); graph.linkWidth(graph.linkWidth()); showEdge(l);
    }).onEngineStop(() => graph.zoomToFit(350, 45));
  applyClusterLayout();
  updateLegend();
  const rendered = graph;
  fitTimer = setTimeout(() => { if (graph === rendered && overviewMode) graph.zoomToFit(650, 90); }, 2500);
}
function showEdge(l) {
  setInspector(true);
  const a = l.source.label, b = l.target.label, evidence = (l.paper_ids || []).slice(0, 30);
  const label = {affiliation:'Publication-time affiliation', shared:'Shared institution and publication year',
                 topic:'Papers by this author on this topic', topic_pair:'Topics on the same papers',
                 coauthor:'Co-authored papers'}[l.type] || 'Supporting papers';
  details.innerHTML = `<div class="edge"><h1>${safe(a)} ↔ ${safe(b)}</h1><p>${label} · ${safe(l.weight)} paper${l.weight === 1 ? '' : 's'}</p>
    ${l.institution ? `<p>${safe(l.institution)}. This does not prove overlapping employment.</p>` : ''}
    ${l.dates?.length ? `<p>Byline dates: ${safe(l.dates.join(', '))}</p>` : ''}
    ${l.raw_affiliations?.length ? `<p>Source byline: ${safe(l.raw_affiliations.filter(Boolean).join(' | '))}</p>` : ''}</div>
    <h2>Supporting papers</h2>${evidence.map(id => `<button class="item" data-paper="${safe(id)}">${safe(id)}</button>`).join('')}
    ${(l.paper_ids || []).length > 30 ? '<p>Showing first 30 paper IDs.</p>' : ''}`;
}
function renderOverviewSlice() {
  if (!overviewData) return;
  const lens = $('#cluster-lens').value;
  $('#cluster-count-control').hidden = lens === 'none';
  if (lens === 'none') {
    const nodes = overviewData.nodes.filter(n => visibleNodes.has(n.kind)).map(n => ({...n}));
    const selectedIds = new Set(nodes.map(n => n.id));
    const links = overviewData.links.filter(l => selectedIds.has(nodeId(l.source)) && selectedIds.has(nodeId(l.target)))
      .map(l => ({...l, source:nodeId(l.source), target:nodeId(l.target)}));
    renderGraph(nodes, links, true);
    details.innerHTML = `<h1>Irish economics research</h1><p>Unclustered network · ${nodes.length.toLocaleString()} visible nodes · ${links.length.toLocaleString()} evidence-backed links.</p><p>Use the left panel to show institutions or topics, or select a clustering lens. Select a node or link to inspect its evidence.</p><p class="caution">Source: OpenAlex publication bylines, not a complete RePEc census.</p>`;
    return;
  }
  const sizes = new Map();
  for (const n of overviewData.nodes) {
    const membership = n.communities?.[lens];
    if (!membership || membership.derived || membership.id === 'unconnected') continue;
    sizes.set(membership.id, (sizes.get(membership.id) || 0) + 1);
  }
  const ranked = [...sizes].sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0]));
  const slider = $('#cluster-count');
  slider.max = String(Math.max(1, ranked.length));
  slider.value = String(Math.min(Number(slider.value), Number(slider.max)));
  const count = Number(slider.value);
  $('#cluster-count-value').textContent = `${count} of ${ranked.length}`;
  const chosen = new Set(ranked.slice(0, count).map(([id]) => id));
  const nodes = overviewData.nodes.filter(n => visibleNodes.has(n.kind) && chosen.has(n.communities?.[lens]?.id)).map(n => ({...n}));
  const ids = new Set(nodes.map(n => n.id));
  const links = overviewData.links.filter(l => ids.has(nodeId(l.source)) && ids.has(nodeId(l.target)))
    .map(l => ({...l, source:nodeId(l.source), target:nodeId(l.target)}));
  renderGraph(nodes, links, true);
  details.innerHTML = `<h1>Irish economics research</h1><p>Showing ${count} of ${ranked.length} ${safe(lens)} communities, with ${nodes.length.toLocaleString()} people, institutions and topics and ${links.length.toLocaleString()} evidence-backed links.</p><p>Use the left slider to change how many communities appear. Search and focused views still cover the full dataset. Select a node or link to inspect its evidence. Colours and circles show algorithmic communities, not asserted group membership.</p><p class="caution">Source: OpenAlex publication bylines, not a complete RePEc census.</p>`;
}
async function openOverview(mode = 'people') {
  showGraphView();
  results.hidden = true; $('#loading').hidden = false;
  try {
    const d = await get(mode === 'topics' ? '/api/topic-overview' : '/api/overview');
    current = null;
    if(mode==='people') {
      overviewData = d;
      overviewClusters = new Map(d.nodes.map(n=>[n.id,n]));
      renderOverviewSlice();
    } else {
      renderGraph(d.nodes, d.links);
    }
    if (mode === 'topics') details.innerHTML = `<h1>Research topics</h1><p>${d.nodes.length.toLocaleString()} topics · ${d.links.length.toLocaleString()} co-occurrence links</p><p>Two topics are linked when they appear on the same included paper. Click a line for supporting paper IDs.</p>`;
  } catch(e) { error(e); } finally { $('#loading').hidden = true; }
}
async function open(type, id) {
  showGraphView();
  setInspector(true);
  results.hidden = true; $('#loading').hidden = false;
  try {
    const d = await get(`/api/${type}/${encodeURIComponent(id)}${type === 'person' && $('#shared').checked ? '?shared=1' : ''}`);
    current = {type,id}; let nodes = [], links = [];
    if (type === 'person') {
      nodes = [{id:d.centre.id,label:d.centre.name,kind:'person',...communityFields(d.centre.id)},
        ...d.collaborators.map(x => ({id:x.id,label:x.name,kind:'person',...communityFields(x.id)})),
        ...d.affiliations.map(x => ({id:x.id,label:x.name,kind:'institution',...communityFields(x.id)})),
        ...d.topics.map(x => ({id:x.id,label:x.name,kind:'topic',...communityFields(x.id)})),
        ...d.shared.filter(x => !d.collaborators.some(c => c.id === x.id)).map(x => ({id:x.id,label:x.name,kind:'person',...communityFields(x.id)}))];
      links = [...d.collaborators.map(x => ({source:d.centre.id,target:x.id,type:'coauthor',weight:x.weight,paper_ids:x.paper_ids})),
        ...d.affiliations.map(x => ({source:d.centre.id,target:x.id,type:'affiliation',weight:x.weight,paper_ids:x.paper_ids,dates:x.dates,raw_affiliations:x.raw_affiliations})),
        ...d.topics.map(x => ({source:d.centre.id,target:x.id,type:'topic',weight:x.weight,paper_ids:x.paper_ids})),
        ...d.shared.map(x => ({source:d.centre.id,target:x.id,type:'shared',weight:x.years.length,institution:x.institution,paper_ids:[...new Set([...x.paper_ids_a,...x.paper_ids_b])]}))];
      details.innerHTML = `<h1>${safe(d.centre.name)}</h1>${d.centre.orcid && approvedUrl(d.centre.orcid) ? `<a class="link" href="${safe(d.centre.orcid)}" target="_blank" rel="noopener">ORCID ↗</a>` : ''}
        <p>${d.collaborators.length} displayed collaborators · ${d.affiliations.length} publication affiliations · ${d.topics.length} topics</p>
        ${paperList(d.papers)}<h2>Affiliations on papers</h2>${d.affiliations.map(x => `<button class="item" data-open="institution" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">${x.target ? 'Irish target · ' : ''}${safe(x.weight)} papers</span></button>`).join('') || '<p>No resolved institution in these authorships.</p>'}
        <h2>Topics</h2>${d.topics.map(x => `<button class="item" data-open="topic" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">${safe(x.weight)} papers</span></button>`).join('')}`;
    } else if (type === 'institution') {
      nodes = [{id:d.centre.id,label:d.centre.name,kind:'institution',...communityFields(d.centre.id)},...d.people.map(x => ({id:x.id,label:x.name,kind:'person',...communityFields(x.id)}))];
      links = d.people.map(x => ({source:d.centre.id,target:x.id,type:'affiliation',weight:x.weight,paper_ids:x.paper_ids,dates:x.dates,raw_affiliations:x.raw_affiliations}));
      details.innerHTML = `<h1>${safe(d.centre.name)}</h1>${d.centre.ror && approvedUrl(d.centre.ror) ? `<a class="link" href="${safe(d.centre.ror)}" target="_blank" rel="noopener">ROR ↗</a>` : ''}
        <p>${d.people.length} displayed publication-affiliated authors${d.centre.target ? ' · Irish target institution' : ''}</p>${paperList(d.papers)}
        <h2>People</h2>${d.people.map(x => `<button class="item" data-open="person" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">${safe(x.weight)} papers</span></button>`).join('')}`;
    } else if (type === 'topic') {
      nodes = [{id:d.centre.id,label:d.centre.name,kind:'topic',...communityFields(d.centre.id)},...d.related.map(x => ({id:x.id,label:x.name,kind:'topic',...communityFields(x.id)}))];
      links = d.related.map(x => ({source:d.centre.id,target:x.id,type:'topic_pair',weight:x.weight,paper_ids:x.paper_ids}));
      details.innerHTML = `<h1>${safe(d.centre.name)}</h1><p>${safe(d.centre.field)}${d.centre.subfield ? ' · ' + safe(d.centre.subfield) : ''}</p>
        ${d.centre.openalex && approvedUrl(d.centre.openalex) ? `<a class="link" href="${safe(d.centre.openalex)}" target="_blank" rel="noopener">OpenAlex topic ↗</a>` : ''}
        ${paperList(d.papers)}<h2>Co-occurring topics</h2>${d.related.map(x => `<button class="item" data-open="topic" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">${safe(x.weight)} shared papers</span></button>`).join('')}`;
    }
    renderGraph(nodes, links);
  } catch(e) { error(e); } finally { $('#loading').hidden = true; }
}
async function showPaper(id) {
  setInspector(true);
  try {
    const d = await get(`/api/paper/${encodeURIComponent(id)}`), p = d.authors[0];
    details.innerHTML = `<h1>${safe(p.title)}</h1><p>${safe(p.date)}</p><p>${p.doi && approvedUrl(p.doi) ? `<a class="link" href="${safe(p.doi)}" target="_blank" rel="noopener">DOI ↗</a> · ` : ''}
      ${p.openalex && approvedUrl(p.openalex) ? `<a class="link" href="${safe(p.openalex)}" target="_blank" rel="noopener">OpenAlex ↗</a>` : ''}</p>
      <h2>Topics</h2>${d.topics.map(x => `<button class="item" data-open="topic" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">Score ${Number(x.score).toFixed(2)}${x.primary ? ' · primary' : ''}</span></button>`).join('')}
      <h2>Authors</h2>${d.authors.filter(x => x.person_id).map(x => `<button class="item" data-open="person" data-id="${safe(x.person_id)}">${safe(x.person_name)}<span class="meta">Byline ${safe(x.position)}</span></button>`).join('')}`;
  } catch(e) { error(e); }
}
search.addEventListener('input', () => {
  clearTimeout(debounce);
  debounce = setTimeout(async () => {
    const q = search.value.trim(); if (q.length < 2) { results.hidden = true; return; }
    try {
      const rows = await get(`/api/search?q=${encodeURIComponent(q)}&kind=${kind.value}`);
      results.innerHTML = rows.map(x => `<button data-id="${safe(x.id)}">${safe(x.name)}</button>`).join('') || '<p>No matching records</p>';
      results.hidden = false;
    } catch(e) { error(e); }
  }, 220);
});
matchSearch.addEventListener('input', () => {
  clearTimeout(debounce);
  const q = matchSearch.value.trim();
  if (q.length < 2) { matchPicks.hidden = true; return; }
  debounce = setTimeout(async () => {
    try {
      const rows = await get(`/api/matchmaker/search?q=${encodeURIComponent(q)}`);
      if (matchSearch.value.trim() !== q) return;
      matchPicks.innerHTML = rows.map(x => `<button data-match-id="${safe(x.id)}">${safe(x.name)}<span>${safe(x.institution || x.id)}</span></button>`).join('') || '<p>No matching researcher</p>';
      matchPicks.hidden = false;
    } catch(e) { matchPicks.innerHTML = `<p class="error">${safe(e.message)}</p>`; matchPicks.hidden = false; }
  }, 220);
});
matchPicks.addEventListener('click',e => {
  const b=e.target.closest('[data-match-id]');if(!b)return;
  matchSearch.value=b.firstChild.textContent;loadMatches(b.dataset.matchId);
});
matchResults.addEventListener('click',e => {
  const b=e.target.closest('[data-match-person]');if(b)open('person',b.dataset.matchPerson);
});
kind.addEventListener('change', () => search.dispatchEvent(new Event('input')));
results.addEventListener('click', e => { const b = e.target.closest('button[data-id]'); if (b) { search.value = b.textContent; open(kind.value, b.dataset.id); } });
details.addEventListener('click', e => { const p = e.target.closest('[data-paper]'), b = e.target.closest('[data-open]'); if (p) showPaper(p.dataset.paper); else if (b) open(b.dataset.open,b.dataset.id); });
window.addEventListener('resize', () => { if (graph) graph.width(host.clientWidth).height(host.clientHeight); });
function setMenu(open) {
  $('#controls').hidden = !open;
  $('#menu-scrim').hidden = !open;
  $('#menu-toggle').setAttribute('aria-expanded',String(open));
  $('#menu-toggle').setAttribute('aria-label',open?'Close graph controls':'Open graph controls');
  if (open) $('#menu-close').focus(); else $('#menu-toggle').focus();
}
function setInspector(open) {
  if ($('#inspector').hidden === !open) return;
  $('#inspector').hidden = !open;
  $('main').classList.toggle('inspector-minimised', !open);
  const button = $('#inspector-toggle');
  button.hidden = open;
  button.setAttribute('aria-expanded', String(open));
  requestAnimationFrame(() => {
    if (graph) graph.width(host.clientWidth).height(host.clientHeight).zoomToFit(300, 45);
  });
}
$('#inspector-toggle').addEventListener('click', () => setInspector($('#inspector').hidden));
$('#inspector-close').addEventListener('click', () => setInspector(false));
$('#menu-toggle').addEventListener('click',()=>setMenu($('#controls').hidden));
$('#menu-close').addEventListener('click',()=>setMenu(false));
$('#menu-scrim').addEventListener('click',()=>setMenu(false));
document.addEventListener('keydown', e => { if (e.key === 'Escape') { results.hidden = true; if(!$('#controls').hidden) setMenu(false); } });
$('#shared').addEventListener('change', () => { if (current?.type === 'person') open('person', current.id); });
$('#overview').addEventListener('click', () => openOverview());
$('#matchmaker-tab').addEventListener('click', showMatchmakerView);
$('#cluster-lens').addEventListener('change',()=>{activeCluster=null;if(overviewMode)renderOverviewSlice();else{updateStyle();applyClusterLayout()}});
$('#cluster-count').addEventListener('input',e=>{$('#cluster-count-value').textContent=`${e.target.value} of ${overviewData ? new Set(overviewData.nodes.map(n=>n.communities?.[$('#cluster-lens').value]).filter(c=>c && !c.derived && c.id!=='unconnected').map(c=>c.id)).size : 0}`});
$('#cluster-count').addEventListener('change',()=>{if(overviewMode)renderOverviewSlice()});
$('#legend').addEventListener('click',e=>{const b=e.target.closest('[data-cluster]');if(!b)return;activeCluster=activeCluster===b.dataset.cluster?null:b.dataset.cluster;updateStyle();if(window.innerWidth<=850)setMenu(false)});
document.querySelectorAll('[data-node-type]').forEach(input=>input.addEventListener('change',()=>{
  input.checked?visibleNodes.add(input.dataset.nodeType):visibleNodes.delete(input.dataset.nodeType);
  if(overviewMode) renderOverviewSlice(); else {updateStyle();applyClusterLayout()}
}));
document.querySelectorAll('[data-label-type]').forEach(input=>input.addEventListener('change',()=>{input.checked?visibleLabels.add(input.dataset.labelType):visibleLabels.delete(input.dataset.labelType);updateStyle()}));
document.querySelectorAll('[data-edge-type]').forEach(input=>input.addEventListener('change',()=>{input.checked?visibleEdges.add(input.dataset.edgeType):visibleEdges.delete(input.dataset.edgeType);updateStyle();applyClusterLayout()}));
openOverview();
