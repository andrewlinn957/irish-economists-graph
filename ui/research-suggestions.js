// Precomputed, source-backed research suggestions.
(() => {
  const $ = selector => document.querySelector(selector);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let data, loading, kind = 'weak', shown = 20;

  async function load() {
    if (data) return data;
    if (loading) return loading;
    loading = (async () => {
      data = window.staticGraphGet
        ? await window.staticGraphGet('/api/research-suggestions')
        : await fetch('/api/research-suggestions').then(response => {
            if (!response.ok) throw Error('Unable to load research suggestions');
            return response.json();
          });
      return data;
    })();
    try { return await loading; } catch (error) { loading = null; throw error; }
  }

  function evidence(ids) {
    return ids?.length ? `<p class="research-evidence">Example papers: ${ids.map(id =>
      `<a href="https://openalex.org/${encodeURIComponent(id)}" target="_blank" rel="noopener">${safe(id)}</a>`).join(' · ')}</p>` : '';
  }
  function weakCard(item) {
    return `<article class="research-card"><span class="research-tag">Weak bridge suggestion</span>
      <h2>${safe(item.a.name)} ↔ ${safe(item.b.name)}</h2>
      <p><strong>${item.bridge_papers.toLocaleString()} distinct papers</strong> connect these two topic communities in the corpus.</p>
      <p>${safe(item.a.name)}: ${item.a.topics} topics, ${item.a.papers.toLocaleString()} papers.<br>
      ${safe(item.b.name)}: ${item.b.topics} topics, ${item.b.papers.toLocaleString()} papers.</p>
      <p class="research-detail">An example connection is ${safe(item.representative.a)} ↔ ${safe(item.representative.b)} (${item.representative.papers.toLocaleString()} shared papers).</p>
      ${evidence(item.examples)}</article>`;
  }
  function emergingCard(item) {
    return `<article class="research-card"><span class="research-tag">Emerging combination suggestion</span>
      <h2>${safe(item.a.name)} + ${safe(item.b.name)}</h2>
      <p><strong>${item.joint_recent.toLocaleString()} joint papers</strong> in 2022–2025; ${item.joint_all.toLocaleString()} in the full corpus.</p>
      <p>${safe(item.a.name)}: ${item.a.earlier.toLocaleString()} papers in 2018–2021 → ${item.a.recent.toLocaleString()} in 2022–2025.<br>
      ${safe(item.b.name)}: ${item.b.earlier.toLocaleString()} → ${item.b.recent.toLocaleString()}.</p>
      <p class="research-detail">Related through ${item.shared_neighbours.map(safe).join(', ')}.</p>
      ${evidence(item.examples)}</article>`;
  }
  function render() {
    if (!data) return;
    const term = $('#research-search').value.trim().toLocaleLowerCase();
    const source = kind === 'weak' ? data.weak_bridges : data.emerging_combinations;
    const rows = term ? source.filter(item => [item.a.name, item.b.name,
      item.representative?.a, item.representative?.b, ...(item.shared_neighbours || [])]
      .some(name => name?.toLocaleLowerCase().includes(term))) : source;
    const visible = rows.slice(0, shown);
    $('#research-results').innerHTML = visible.map(kind === 'weak' ? weakCard : emergingCard).join('')
      || '<p>No suggestions match this search in the published shortlist.</p>';
    $('#research-more').hidden = shown >= rows.length;
    $('#research-count').textContent = `Showing ${visible.length.toLocaleString()} of ${rows.length.toLocaleString()} suggestions`;
    $('#research-method').textContent = kind === 'weak'
      ? 'Weak bridges compare algorithmically detected topic communities with substantial paper coverage but few papers crossing between them. Communities are inferred, not institutional or disciplinary labels.'
      : 'Emerging combinations pair topics whose paper counts each rose from 2018–2021 to 2022–2025, with shared specific neighbours but at most three joint papers in the recent window. Partial-year 2026 is excluded from the trend comparison.';
  }
  window.hideResearchView = () => {
    document.body.classList.remove('research-mode');
    $('main').classList.remove('research-mode');
    $('#research-view').hidden = true;
    $('#research-tab').classList.remove('active');
    $('#research-tab').setAttribute('aria-pressed','false');
  };
  window.showResearchView = async () => {
    document.body.classList.remove('matchmaker-mode');
    $('main').classList.remove('matchmaker-mode');
    $('#matchmaker-view').hidden = true;
    $('#matchmaker-tab').classList.remove('active');
    $('#matchmaker-tab').setAttribute('aria-pressed','false');
    $('#overview').classList.remove('active');
    $('#overview').setAttribute('aria-pressed','false');
    document.body.classList.add('research-mode');
    $('main').classList.add('research-mode');
    $('#research-view').hidden = false;
    $('#research-tab').classList.add('active');
    $('#research-tab').setAttribute('aria-pressed','true');
    $('#research-results').innerHTML = data ? $('#research-results').innerHTML : '<p>Loading suggestions…</p>';
    try { await load(); render(); }
    catch (error) { $('#research-results').innerHTML = `<p class="error">${safe(error.message)}</p>`; }
  };
  $('#research-search').addEventListener('input', () => { shown = 20; render(); });
  $('#research-more').addEventListener('click', () => { shown += 20; render(); });
  document.querySelectorAll('[data-research-kind]').forEach(button => button.addEventListener('click', () => {
    kind = button.dataset.researchKind;
    shown = 20;
    document.querySelectorAll('[data-research-kind]').forEach(other => {
      other.classList.toggle('active', other === button);
      other.setAttribute('aria-pressed', String(other === button));
    });
    render();
  }));
})();
