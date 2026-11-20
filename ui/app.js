const $ = s => document.querySelector(s);
const details = $('#details'), results = $('#results'), search = $('#search');
const kind = $('#kind'), host = $('#graph');
let activeLens = $('#cluster-lens').value;
const matchSearch = $('#match-search'), matchPicks = $('#match-picks'), matchResults = $('#match-results');
let graph, selectedEdge = null, current = null, debounce, fitTimer, prominent = new Set();
let visibleNodes = new Set(['person']);
let visibleLabels = new Set(['person','institution','topic']);
let visibleEdges = new Set(['coauthor','affiliation','topic','topic_pair','shared']);
let currentNodes = [], currentLinks = [], currentNodeMap = new Map(), overviewClusters = new Map(), activeCluster = null, featuredClusters = new Set();
let overviewData = null, overviewDataView = null, scopeData = null, scopeKey = null, overviewMode = false, clusterDetailsBackup = null;
let overviewRequest = 0;
let drillStack = [], drillChildren = [];
const selectedInstitutions = new Set();
const lensEdges = {coauthor:new Set(['coauthor']), topic:new Set(['topic','topic_pair']), institution:new Set(['affiliation'])};
const palette = ['#2e7d5b','#be6a42','#5c76b7','#9a669f','#a88727','#408d9b','#8c694d','#6b8d40','#b45271','#4b7691','#9067b0','#b2784d','#418078','#967a35','#6576a1','#907c69'];
function nodeId(n) { return typeof n === 'object' ? n.id : n; }
function communityFields(id) { const n=overviewClusters.get(id); return n ? {communities:n.communities} : {}; }
function clusterOf(n) { return n.communities?.[activeLens]?.id || 'unconnected'; }
function clusterLabel(n) { return n.communities?.[activeLens]?.label || 'Unconnected'; }
function countryMatches(country, choice=$('#country-filter').value) {
  if(choice==='all')return true;
  if(choice==='island')return country==='Ireland'||country==='Northern Ireland';
  if(choice==='uk')return ['England','Scotland','Wales','Northern Ireland','United Kingdom (unclassified)'].includes(country);
  return country===choice;
}
function refreshInstitutions() {
  if(!overviewData)return;
  const term=$('#institution-search').value.trim().toLocaleLowerCase();
  const institutions=overviewData.nodes.filter(n=>n.kind==='institution'&&countryMatches(n.country));
  const available=new Set(institutions.map(n=>n.id));
  for(const id of selectedInstitutions)if(!available.has(id))selectedInstitutions.delete(id);
  const matching=institutions.filter(n=>n.label.toLocaleLowerCase().includes(term))
    .sort((a,b)=>Number(selectedInstitutions.has(b.id))-Number(selectedInstitutions.has(a.id))||a.label.localeCompare(b.label)||a.id.localeCompare(b.id));
  $('#institution-filter').innerHTML=matching.map(n=>`<label class="institution-option"><input type="checkbox" value="${safe(n.id)}" ${selectedInstitutions.has(n.id)?'checked':''}><span>${safe(n.label)}</span></label>`).join('') || '<p class="control-hint">No matching institutions</p>';
  const count=selectedInstitutions.size;
  $('#institution-summary').textContent=count ? `${count} institution${count===1?'':'s'} selected` : 'All institutions in selected country';
  $('#institution-clear').hidden=!count;
  $('#institution-count').textContent=`${matching.length.toLocaleString()} of ${institutions.length.toLocaleString()} institutions${count?` · ${count} selected`:''}`;
}
function scopedOverview() {
  const institutionIds=[...selectedInstitutions].sort();
  const key=`${$('#country-filter').value}|${institutionIds.join('|')}|${overviewDataView}`;
  if (scopeData && scopeKey === key) return scopeData;
  if (!institutionIds.length) {
    scopeKey=key;
    scopeData=overviewData;
    return scopeData;
  }
  const institutions=new Set(institutionIds);
  const people=new Set();
  for(const edge of overviewData.links)if(edge.type==='affiliation'){
    const a=nodeId(edge.source),b=nodeId(edge.target);
    if(institutions.has(a))people.add(b);
    if(institutions.has(b))people.add(a);
  }
  const topics=new Set();
  for(const edge of overviewData.links)if(edge.type==='topic'){
    const a=nodeId(edge.source),b=nodeId(edge.target);
    if(people.has(a))topics.add(b);
    if(people.has(b))topics.add(a);
  }
  const ids=new Set([...institutions,...people,...topics]);
  scopeKey=key;
  scopeData={nodes:overviewData.nodes.filter(n=>ids.has(n.id)),
    links:overviewData.links.filter(e=>ids.has(nodeId(e.source))&&ids.has(nodeId(e.target)))};
  return scopeData;
}
function hash(s) { let h=2166136261; for(const ch of s) h=Math.imul(h^ch.charCodeAt(0),16777619); return h>>>0; }
function clusterColour(n) {
  if (activeLens === 'none') return {person:'#2e7d5b',institution:'#5c76b7',topic:'#be6a42'}[n.kind] || '#718277';
  return clusterOf(n)==='unconnected' ? '#aeb8b2' : palette[hash(clusterOf(n))%palette.length];
}
function clusterAbbreviation(label) {
  const words = String(label || '').split(/[^\p{L}\p{N}]+/u).filter(word => word && !/^(and|of|the|in|on|for|at|with)$/i.test(word));
  if (words.length === 1 && words[0].length <= 14) return words[0];
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
  if (overviewMode && activeLens === 'none') return '#83a39470';
  const a=endNode(l.source), b=endNode(l.target);
  if (activeCluster && a && b && clusterOf(a)!==activeCluster && clusterOf(b)!==activeCluster) return '#d5ddd526';
  if (overviewMode) {
    const lens=activeLens;
    const same=a && b && clusterOf(a)===clusterOf(b);
    const inLens=(lens==='coauthor' && l.type==='coauthor') || (lens==='topic' && (l.type==='topic' || l.type==='topic_pair')) || (lens==='institution' && l.type==='affiliation');
    if (inLens && !same && activeCluster && (clusterOf(a)===activeCluster || clusterOf(b)===activeCluster)) return '#365c4fc0';
    return inLens ? same ? '#769b8150' : '#526f628a' : '#9daeba0b';
  }
  return l.type==='topic_pair'||l.type==='topic'?'#b3c3d9':l.type==='shared'?'#c6b5cd':'#bdcfc0';
}
function updateLegend() {
  if (drillStack.length) {
    const parent=drillStack.at(-1);
    $('#cluster-heading').textContent=`Inside ${parent.label}`;
    $('#legend-list').innerHTML=`<button type="button" data-drill-back="1">← ${drillStack.length===1?'All clusters':'Parent cluster'}</button>`+
      drillChildren.map((g,i)=>`<button type="button" data-drill-child="${i}" title="Explore subcluster"><span class="swatch" style="background:${palette[hash(g.id)%palette.length]}"></span><span>${safe(g.label)}</span><span class="legend-count">${g.ids.length}</span></button>`).join('');
    return;
  }
  if ($('#cluster-lens').value === 'none') {
    $('#cluster-heading').textContent = 'No clustering';
    $('#legend-list').replaceChildren();
    return;
  }
  const counts=new Map(), representatives=new Map();
  for(const n of currentNodes) if(nodeVisible(n)&&clusterOf(n)!=='unconnected') {
    const id=clusterOf(n);
    counts.set(id,(counts.get(id)||0)+1);
    if(!representatives.has(id)) representatives.set(id,n);
  }
  const rows=[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  const lens=$('#cluster-lens').selectedOptions[0].text;
  $('#cluster-heading').textContent=`${lens} · ${counts.size} clusters`;
  $('#legend-list').innerHTML=rows.map(([name,count])=>{
    const n=representatives.get(name);
    return `<button type="button" data-cluster="${safe(name)}" class="${name===activeCluster?'active':''}" aria-pressed="${name===activeCluster}" title="View cluster details"><span class="swatch" style="background:${clusterColour(n)}"></span><span>${safe(clusterLabel(n))}</span><span class="legend-count">${count}</span></button>`;
  }).join('');
}
function renderClusterDetails(id) {
  const lens = $('#cluster-lens').value;
  const sourceNodes = scopeData?.nodes?.length ? scopeData.nodes : currentNodes;
  const members = sourceNodes.filter(n => n.communities?.[lens]?.id === id);
  const shown = currentNodes.filter(n => nodeVisible(n) && n.communities?.[lens]?.id === id);
  const core = members.filter(n => !n.communities[lens].derived);
  const representative = core[0] || members[0];
  const title = representative?.communities?.[lens]?.label || 'Cluster';
  const lensName = $('#cluster-lens').selectedOptions[0].text;
  const count = n => n.toLocaleString();
  const list = (kind, heading) => {
    const rows = members.filter(n => n.kind === kind).sort((a,b) =>
      Number(a.communities[lens].derived) - Number(b.communities[lens].derived) || a.label.localeCompare(b.label));
    if (!rows.length) return '';
    const item = n => `<button class="item" data-open="${kind}" data-id="${safe(n.id)}">${safe(n.label)}${n.communities[lens].derived ? '<span class="meta">Associated with this cluster</span>' : ''}</button>`;
    const first = rows.slice(0,20).map(item).join('');
    const rest = rows.length > 20 ? `<details class="cluster-more"><summary>Show ${count(rows.length-20)} more</summary>${rows.slice(20).map(item).join('')}</details>` : '';
    return `<h2>${heading} · ${count(rows.length)}</h2><div class="cluster-member-list">${first}${rest}</div>`;
  };
  details.innerHTML = `<div class="cluster-detail"><p class="eyebrow">${safe(lensName)} cluster</p><h1>${safe(title)}</h1>
    <p>${count(core.length)} core members · ${count(members.length - core.length)} associated nodes · ${count(shown.length)} currently shown</p>
    <p class="caution">This is an algorithmic grouping, not a verified institutional affiliation or research collaboration. Associated nodes are assigned from their links to core members.</p>
    ${core.length>=4 && overviewMode ? '<button class="drill-action" type="button" data-drill-start="1">Find clusters inside this cluster</button>' : ''}
    ${list('person','People')}${list('institution','Institutions')}${list('topic','Topics')}</div>`;
  setInspector(true);
}
function nestedCommunities(ids, lens, depth) {
  // Local modularity optimisation on the selected lens's induced subgraph.
  // A rising resolution exposes finer structure at each depth; IDs remain view-only.
  const vertices=[...ids].sort(), allowed=lensEdges[lens], adjacency=new Map(vertices.map(id=>[id,new Map()]));
  for(const e of scopeData.links) {
    const a=nodeId(e.source), b=nodeId(e.target);
    if(!allowed?.has(e.type)||a===b||!adjacency.has(a)||!adjacency.has(b))continue;
    const w=Math.sqrt(Math.min(Number(e.weight)||1,12));
    adjacency.get(a).set(b,(adjacency.get(a).get(b)||0)+w);
    adjacency.get(b).set(a,(adjacency.get(b).get(a)||0)+w);
  }
  const degree=new Map(vertices.map(id=>[id,[...adjacency.get(id).values()].reduce((a,b)=>a+b,0)]));
  const total=[...degree.values()].reduce((a,b)=>a+b,0);
  if(!total)return [];
  const group=new Map(vertices.map(id=>[id,id])), volume=new Map(degree), resolution=1.6+depth*0.8;
  const order=[...vertices].sort((a,b)=>degree.get(b)-degree.get(a)||a.localeCompare(b));
  for(let pass=0;pass<20;pass++) {
    let moves=0;
    for(const id of order) {
      const own=group.get(id), k=degree.get(id);
      if(!k)continue;
      volume.set(own,volume.get(own)-k);
      const weights=new Map();
      for(const [other,w] of adjacency.get(id))weights.set(group.get(other),(weights.get(group.get(other))||0)+w);
      let best=own, gain=(weights.get(own)||0)-resolution*k*(volume.get(own)||0)/total;
      for(const [candidate,inside] of weights) {
        const score=inside-resolution*k*(volume.get(candidate)||0)/total;
        if(score>gain+1e-8 || (Math.abs(score-gain)<1e-8 && candidate<best)){best=candidate;gain=score;}
      }
      group.set(id,best);volume.set(best,(volume.get(best)||0)+k);
      if(best!==own)moves++;
    }
    if(!moves)break;
  }
  const groups=new Map();
  for(const id of vertices){const key=group.get(id);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(id);}
  if(groups.size<2||groups.size>Math.max(20,vertices.length/2))return [];
  const records=new Map(scopeData.nodes.map(n=>[n.id,n]));
  const representativeKind={coauthor:'person',topic:'topic',institution:'institution'}[lens];
  return [...groups.values()].sort((a,b)=>b.length-a.length||a[0].localeCompare(b[0])).map((members,i)=>{
    const options=members.filter(id=>records.get(id)?.kind===representativeKind);
    const representative=[...(options.length?options:members)].sort((a,b)=>degree.get(b)-degree.get(a)||a.localeCompare(b))[0];
    return {id:`sub-${depth}-${i}`,label:records.get(representative)?.label||`Subcluster ${i+1}`,ids:members};
  });
}
function renderDrill() {
  const parent=drillStack.at(-1), lens=$('#cluster-lens').value;
  drillChildren=nestedCommunities(parent.ids,lens,drillStack.length);
  const assignment=new Map();
  drillChildren.forEach(g=>g.ids.forEach(id=>assignment.set(id,g)));
  const nodes=scopeData.nodes.filter(n=>parent.ids.has(n.id)&&visibleNodes.has(n.kind)).map(n=>{
    const child=assignment.get(n.id);
    return {...n,communities:{...n.communities,[lens]:{id:child?.id||parent.id,label:child?.label||parent.label,derived:false}}};
  });
  const ids=new Set(nodes.map(n=>n.id));
  const links=scopeData.links.filter(e=>ids.has(nodeId(e.source))&&ids.has(nodeId(e.target)))
    .map(e=>({...e,source:nodeId(e.source),target:nodeId(e.target)}));
  renderGraph(nodes,links,true);
  const crumb=drillStack.map(g=>safe(g.label)).join(' → ');
  details.innerHTML=`<div class="cluster-detail"><p class="eyebrow">${safe($('#cluster-lens').selectedOptions[0].text)} · level ${drillStack.length}</p><h1>${safe(parent.label)}</h1>
    <p>${parent.ids.size.toLocaleString()} members · ${drillChildren.length} internal communities</p>
    <p class="meta">${crumb}</p><p class="caution">Subclusters are computed from links within this group for the selected network. They are exploratory, not verified categories.</p>
    ${drillChildren.length?'<p>Select a subcluster at the bottom of the left panel to explore it.</p>':'<p>No further meaningful split was found at this level.</p>'}</div>`;
  updateLegend();setInspector(true);
}
function updateStyle() {
  if(!graph) return;
  graph.nodeVisibility(overviewMode ? () => true : nodeVisible)
    .linkVisibility(overviewMode ? () => true : edgeVisible)
    .nodeColor(nodeColour).linkColor(edgeColour);
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
  window.hideResearchView?.();
  $('#overview').classList.add('active');
  $('#overview').setAttribute('aria-pressed','true');
  $('#matchmaker-tab').classList.remove('active');
  $('#matchmaker-tab').setAttribute('aria-pressed','false');
  requestAnimationFrame(() => { if (graph) graph.width(host.clientWidth).height(host.clientHeight); });
}
function showMatchmakerView() {
  window.hideResearchView?.();
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
  currentNodes=nodes; currentLinks=links; currentNodeMap=new Map(nodes.map(n=>[n.id,n])); activeCluster=null; clusterDetailsBackup=null;
  const seeded = overview && nodes.length > 0 && nodes.every(n => Array.isArray(n.layouts?.[activeLens]));
  if (seeded) for (const n of nodes) [n.x, n.y] = n.layouts[activeLens];
  const degrees = new Map(nodes.map(n => [n.id, 0]));
  for (const l of links) { degrees.set(l.source, (degrees.get(l.source) || 0) + 1); degrees.set(l.target, (degrees.get(l.target) || 0) + 1); }
  prominent = new Set([...degrees].sort((a,b) => b[1] - a[1]).slice(0, 20).map(x => x[0]));
  graph = window.FoamGraph()(host).width(host.clientWidth).height(host.clientHeight)
    .cooldownTime(seeded ? 1200 : overview ? activeLens === 'none' ? 3000 : nodes.length > 12000 ? 8000 : 12000 : 15000)
    .graphData({nodes,links}).nodeId('id').backgroundColor('#f7f8f5').nodeRelSize(6)
    .onRenderFramePre(drawClusterAreas)
    .onRenderFramePost(drawClusterLabels)
    .nodeVisibility(overview ? () => true : nodeVisible)
    .linkVisibility(overview ? () => true : edgeVisible).nodeColor(nodeColour)
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
    .linkWidth(l => selectedEdge === l ? 5 : overviewMode ? Math.max(0.5, Math.min(activeLens !== 'none' && clusterOf(endNode(l.source)) !== clusterOf(endNode(l.target)) ? 2.0 : 1.4, Math.sqrt(l.weight || 1) * 0.6)) : Math.max(1, Math.min(2.5, Math.sqrt(l.weight || 1))))
    .onNodeClick(n => open(n.kind, n.id)).onLinkClick(l => {
      selectedEdge = l; graph.linkColor(graph.linkColor()); graph.linkWidth(graph.linkWidth()); showEdge(l);
    }).onEngineStop(() => graph.zoomToFit(350, 45));
  applyClusterLayout();
  updateLegend();
  const rendered = graph;
  fitTimer = setTimeout(() => { if (graph === rendered && overviewMode) graph.zoomToFit(seeded ? 250 : 650, 90); }, seeded ? 100 : 2500);
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
  drillStack=[];drillChildren=[];
  scopeData=scopedOverview();
  const lens = $('#cluster-lens').value;
  $('#cluster-count-control').hidden = lens === 'none';
  if (lens === 'none') {
    const nodes = scopeData.nodes.filter(n => visibleNodes.has(n.kind)).map(n => ({...n}));
    const selectedIds = new Set(nodes.map(n => n.id));
    const links = scopeData.links.filter(l => visibleEdges.has(l.type) && selectedIds.has(nodeId(l.source)) && selectedIds.has(nodeId(l.target)))
      .map(l => ({...l, source:nodeId(l.source), target:nodeId(l.target)}));
    renderGraph(nodes, links, true);
    details.innerHTML = `<h1>UK and Ireland economics research</h1><p>${safe($('#country-filter').selectedOptions[0].text)} · ${nodes.length.toLocaleString()} visible nodes · ${links.length.toLocaleString()} evidence-backed links.</p><p>Use the left panel to choose a country or institution, show institutions or topics, or select a clustering lens. Select a node or link to inspect its evidence.</p><p class="caution">Source: OpenAlex publication bylines, not a complete RePEc census.</p>`;
    return;
  }
  const sizes = new Map();
  for (const n of scopeData.nodes) {
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
  const nodes = scopeData.nodes.filter(n => visibleNodes.has(n.kind) && chosen.has(n.communities?.[lens]?.id)).map(n => ({...n}));
  const ids = new Set(nodes.map(n => n.id));
  const links = scopeData.links.filter(l => visibleEdges.has(l.type) && ids.has(nodeId(l.source)) && ids.has(nodeId(l.target)))
    .map(l => ({...l, source:nodeId(l.source), target:nodeId(l.target)}));
  renderGraph(nodes, links, true);
  details.innerHTML = `<h1>UK and Ireland economics research</h1><p>${safe($('#country-filter').selectedOptions[0].text)} · showing ${count} of ${ranked.length} ${safe(lens)} communities, with ${nodes.length.toLocaleString()} people, institutions and topics and ${links.length.toLocaleString()} evidence-backed links.</p><p>Use the left slider to change how many communities appear. Search and focused views still cover the full dataset. Select a node or link to inspect its evidence. Colours and circles show algorithmic communities, not asserted group membership.</p><p class="caution">Source: OpenAlex publication bylines, not a complete RePEc census.</p>`;
}
async function openOverview(mode = 'people') {
  const request = ++overviewRequest;
  showGraphView();
  results.hidden = true; $('#loading').hidden = false;
  try {
    const view = visibleNodes.has('topic') || $('#cluster-lens').value === 'topic' ? 'full' : 'people';
    const d = await get(mode === 'topics' ? '/api/topic-overview' : `/api/overview?country=${encodeURIComponent($('#country-filter').value)}&view=${view}`);
    if (request !== overviewRequest) return;
    current = null;
    if(mode==='people') {
      overviewData = d;
      overviewDataView = view;
      scopeData = null; scopeKey = null;
      overviewClusters = new Map(d.nodes.map(n=>[n.id,n]));
      refreshInstitutions();
      renderOverviewSlice();
    } else {
      renderGraph(d.nodes, d.links);
    }
    if (mode === 'topics') details.innerHTML = `<h1>Research topics</h1><p>${d.nodes.length.toLocaleString()} topics · ${d.links.length.toLocaleString()} co-occurrence links</p><p>Two topics are linked when they appear on the same included paper. Click a line for supporting paper IDs.</p>`;
  } catch(e) { if (request === overviewRequest) error(e); } finally { if (request === overviewRequest) $('#loading').hidden = true; }
}
async function open(type, id) {
  drillStack=[];drillChildren=[];
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
        ${paperList(d.papers)}<h2>Affiliations on papers</h2>${d.affiliations.map(x => `<button class="item" data-open="institution" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">${x.target ? 'In-scope institution · ' : ''}${safe(x.weight)} papers</span></button>`).join('') || '<p>No resolved institution in these authorships.</p>'}
        <h2>Topics</h2>${d.topics.map(x => `<button class="item" data-open="topic" data-id="${safe(x.id)}">${safe(x.name)}<span class="meta">${safe(x.weight)} papers</span></button>`).join('')}`;
    } else if (type === 'institution') {
      nodes = [{id:d.centre.id,label:d.centre.name,kind:'institution',...communityFields(d.centre.id)},...d.people.map(x => ({id:x.id,label:x.name,kind:'person',...communityFields(x.id)}))];
      links = d.people.map(x => ({source:d.centre.id,target:x.id,type:'affiliation',weight:x.weight,paper_ids:x.paper_ids,dates:x.dates,raw_affiliations:x.raw_affiliations}));
      details.innerHTML = `<h1>${safe(d.centre.name)}</h1>${d.centre.ror && approvedUrl(d.centre.ror) ? `<a class="link" href="${safe(d.centre.ror)}" target="_blank" rel="noopener">ROR ↗</a>` : ''}
        <p>${d.people.length} displayed publication-affiliated authors${d.centre.target ? ' · In-scope institution' : ''}</p>${paperList(d.papers)}
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
details.addEventListener('click', e => {
  const drill=e.target.closest('[data-drill-start]');
  if(drill && activeCluster && overviewData){
    const lens=$('#cluster-lens').value;
    const members=scopeData.nodes.filter(n=>n.communities?.[lens]?.id===activeCluster);
    drillStack=[{id:activeCluster,label:members[0]?.communities?.[lens]?.label||'Cluster',ids:new Set(members.map(n=>n.id))}];
    renderDrill();if(window.innerWidth<=850)setMenu(false);return;
  }
  const p=e.target.closest('[data-paper]'), b=e.target.closest('[data-open]');
  if(p)showPaper(p.dataset.paper);else if(b)open(b.dataset.open,b.dataset.id);
});
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
$('#research-tab').addEventListener('click', () => window.showResearchView());
$('#cluster-lens').addEventListener('change',()=>{
  activeLens=$('#cluster-lens').value;
  activeCluster=null;
  if(clusterDetailsBackup!==null){details.innerHTML=clusterDetailsBackup;clusterDetailsBackup=null}
  if(overviewMode) {
    if($('#cluster-lens').value==='topic' && overviewDataView!=='full') openOverview();
    else renderOverviewSlice();
  } else {updateStyle();applyClusterLayout()}
});
$('#cluster-count').addEventListener('input',e=>{$('#cluster-count-value').textContent=`${e.target.value} of ${scopeData ? new Set(scopeData.nodes.map(n=>n.communities?.[$('#cluster-lens').value]).filter(c=>c && !c.derived && c.id!=='unconnected').map(c=>c.id)).size : 0}`});
$('#cluster-count').addEventListener('change',()=>{if(overviewMode)renderOverviewSlice()});
$('#country-filter').addEventListener('change',()=>{
  $('#institution-search').value='';selectedInstitutions.clear();
  openOverview();
});
$('#institution-search').addEventListener('input',refreshInstitutions);
$('#institution-filter').addEventListener('change',e=>{
  if(!e.target.matches('input[type="checkbox"]'))return;
  if(e.target.checked)selectedInstitutions.add(e.target.value);else selectedInstitutions.delete(e.target.value);
  scopeData=null;scopeKey=null;refreshInstitutions();
  if(overviewMode)renderOverviewSlice();else openOverview();
});
$('#institution-clear').addEventListener('click',()=>{
  selectedInstitutions.clear();scopeData=null;scopeKey=null;refreshInstitutions();
  if(overviewMode)renderOverviewSlice();else openOverview();
});
$('#legend').addEventListener('click',e=>{
  if(drillStack.length){
    if(e.target.closest('[data-drill-back]')){
      drillStack.pop();if(drillStack.length)renderDrill();else renderOverviewSlice();
    }else{
      const child=e.target.closest('[data-drill-child]');
      if(child){const g=drillChildren[Number(child.dataset.drillChild)];if(g){drillStack.push({...g,ids:new Set(g.ids)});renderDrill();}}
    }
    if(window.innerWidth<=850)setMenu(false);return;
  }
  const b=e.target.closest('[data-cluster]');if(!b)return;
  if(activeCluster===b.dataset.cluster){
    activeCluster=null;
    details.innerHTML=clusterDetailsBackup ?? details.innerHTML;
    clusterDetailsBackup=null;
  }else{
    if(clusterDetailsBackup===null)clusterDetailsBackup=details.innerHTML;
    activeCluster=b.dataset.cluster;
    renderClusterDetails(activeCluster);
  }
  updateStyle();
  if(window.innerWidth<=850)setMenu(false);
});
document.querySelectorAll('[data-node-type]').forEach(input=>input.addEventListener('change',()=>{
  input.checked?visibleNodes.add(input.dataset.nodeType):visibleNodes.delete(input.dataset.nodeType);
  if(overviewMode) {
    if(input.dataset.nodeType==='topic' && input.checked && overviewDataView!=='full') openOverview();
    else renderOverviewSlice();
  } else {updateStyle();applyClusterLayout()}
}));
document.querySelectorAll('[data-label-type]').forEach(input=>input.addEventListener('change',()=>{input.checked?visibleLabels.add(input.dataset.labelType):visibleLabels.delete(input.dataset.labelType);updateStyle()}));
document.querySelectorAll('[data-edge-type]').forEach(input=>input.addEventListener('change',()=>{
  input.checked?visibleEdges.add(input.dataset.edgeType):visibleEdges.delete(input.dataset.edgeType);
  if(overviewMode)renderOverviewSlice();else{updateStyle();applyClusterLayout()}
}));
openOverview();
