const loadJson = async (path) => {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}`);
  return res.json();
};

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

function renderTable(el, rows, columns) {
  el.innerHTML = `
    <thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}</tr></thead>
    <tbody>
      ${rows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : esc(row[c.key])}</td>`).join('')}</tr>`).join('')}
    </tbody>
  `;
}

function summarize(rows, key) {
  const counts = new Map();
  rows.forEach(r => counts.set(r[key] || '未知', (counts.get(r[key] || '未知') || 0) + 1));
  return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
}

function reportColumns() {
  return [
    { label: '日期', key: 'publish_date' },
    { label: '公司', key: 'company' },
    { label: '类型', render: r => `<span class="badge">${esc(r.report_type || '未知')}</span>` },
    { label: '标题', render: r => `${r.detail_url ? `<a href="${esc(r.detail_url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}` },
    { label: '来源', key: 'source_type' },
    { label: '关键词', key: 'matched_keywords' },
  ];
}

function renderReports(rows) {
  const el = document.getElementById('reports-list');
  if (!rows.length) {
    el.innerHTML = '<div class="empty">没有匹配结果</div>';
    return;
  }
  renderTable(el, rows, reportColumns());
}

function applyFilters(allRows) {
  const company = document.getElementById('company-filter').value;
  const type = document.getElementById('type-filter').value;
  const source = document.getElementById('source-filter').value;
  const keyword = document.getElementById('keyword-filter').value.trim().toLowerCase();
  const rows = allRows.filter(r => {
    if (company !== 'ALL' && r.company !== company) return false;
    if (type !== 'ALL' && r.report_type !== type) return false;
    if (source !== 'ALL' && r.source_type !== source) return false;
    if (keyword) {
      const haystack = `${r.title || ''} ${r.matched_keywords || ''} ${r.company || ''}`.toLowerCase();
      if (!haystack.includes(keyword)) return false;
    }
    return true;
  }).sort((a, b) => String(b.publish_date || '').localeCompare(String(a.publish_date || '')));
  document.getElementById('filtered-count').textContent = rows.length;
  renderReports(rows.slice(0, 500));
}

function fillSelect(id, values, labelAll) {
  const el = document.getElementById(id);
  el.innerHTML = `<option value="ALL">${labelAll}</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
}

async function main() {
  const [meta, reports] = await Promise.all([
    loadJson('data/site_meta.json'),
    loadJson('data/raw_reports.json'),
  ]);

  document.getElementById('site-meta').textContent = `更新时间：${meta.generated_at} ｜ 研报线索：${meta.report_count}条 ｜ 机构：${meta.company_count}家 ｜ 日期：${meta.earliest_date} 至 ${meta.latest_date}`;
  document.getElementById('summary-cards').innerHTML = `
    <div class="card"><div class="label">覆盖机构</div><div class="value">${meta.company_count}</div></div>
    <div class="card"><div class="label">研报线索</div><div class="value">${meta.report_count}</div></div>
    <div class="card"><div class="label">起始日期</div><div class="value small">${meta.earliest_date}</div></div>
    <div class="card"><div class="label">最新日期</div><div class="value small">${meta.latest_date}</div></div>
  `;

  const companies = summarize(reports, 'company');
  const types = summarize(reports, 'report_type');
  const sources = summarize(reports, 'source_type');

  renderTable(document.getElementById('company-table'), companies, [
    { label: '机构', key: 'name' },
    { label: '线索数', key: 'count' },
  ]);
  renderTable(document.getElementById('type-table'), types, [
    { label: '类型', key: 'name' },
    { label: '数量', key: 'count' },
  ]);

  fillSelect('company-filter', companies.map(x => x.name), '全部公司');
  fillSelect('type-filter', types.map(x => x.name), '全部类型');
  fillSelect('source-filter', sources.map(x => x.name), '全部来源');

  ['company-filter', 'type-filter', 'source-filter', 'keyword-filter'].forEach(id => {
    document.getElementById(id).addEventListener('input', () => applyFilters(reports));
  });
  applyFilters(reports);
}

main().catch(err => {
  document.body.innerHTML = `<main class="container"><div class="panel"><h1>数据加载失败</h1><p>${esc(err.message)}</p></div></main>`;
});
