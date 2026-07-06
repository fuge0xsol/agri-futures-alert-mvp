const loadJson = async (path) => {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}`);
  return res.json();
};

const fmt = (value, suffix = '') => `${value}${suffix}`;
const returnClass = (value) => value >= 0 ? 'return-pos' : 'return-neg';

function renderTable(el, rows, columns) {
  el.innerHTML = `
    <thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}</tr></thead>
    <tbody>
      ${rows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : row[c.key]}</td>`).join('')}</tr>`).join('')}
    </tbody>
  `;
}

function rankingColumns() {
  return [
    { label: '排名', render: r => `<span class="rank">${r.rank}</span>` },
    { label: '机构', key: 'company_name' },
    { label: '准确率', render: r => fmt(r.accuracy, '%') },
    { label: '样本数', key: 'sample_count' },
    { label: '平均收益', render: r => `<span class="${returnClass(r.avg_return_pct)}">${fmt(r.avg_return_pct, '%')}</span>` },
    { label: '综合分', key: 'score' },
  ];
}

function renderReports(rows) {
  const el = document.getElementById('reports-list');
  el.innerHTML = rows
    .sort((a, b) => b.publish_date.localeCompare(a.publish_date))
    .map(r => `
      <article class="report-card">
        <div class="report-title">
          <span>${r.title}</span>
          <span class="${r.hit ? 'hit' : 'miss'}">${r.hit ? '命中' : '未命中'}</span>
        </div>
        <div class="report-meta">
          ${r.publish_date} · ${r.company_name} · ${r.commodity_name} · ${r.direction_label} · ${r.horizon === 'weekly' ? '周度' : '月度'} · 收益率 <span class="${returnClass(r.return_pct)}">${r.return_pct}%</span>
        </div>
        <div class="evidence">证据句：${r.evidence}</div>
      </article>
    `).join('');
}

function renderCommodityFilters(rows) {
  const filters = document.getElementById('commodity-filters');
  const table = document.getElementById('commodity-table');
  const commodities = [...new Map(rows.map(r => [r.commodity, r.commodity_name])).entries()];
  const render = (commodity) => {
    [...filters.querySelectorAll('button')].forEach(btn => btn.classList.toggle('active', btn.dataset.commodity === commodity));
    const filtered = commodity === 'ALL' ? rows : rows.filter(r => r.commodity === commodity);
    renderTable(table, filtered, [
      { label: '品种', key: 'commodity_name' },
      ...rankingColumns(),
    ]);
  };
  filters.innerHTML = `<button class="active" data-commodity="ALL">全部</button>` +
    commodities.map(([symbol, name]) => `<button data-commodity="${symbol}">${name}</button>`).join('');
  filters.addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') render(e.target.dataset.commodity);
  });
  render('ALL');
}

async function main() {
  const [meta, overall, weekly, monthly, commodity, reports] = await Promise.all([
    loadJson('data/site_meta.json'),
    loadJson('data/rankings_overall.json'),
    loadJson('data/rankings_weekly.json'),
    loadJson('data/rankings_monthly.json'),
    loadJson('data/rankings_by_commodity.json'),
    loadJson('data/reports.json'),
  ]);

  document.getElementById('site-meta').textContent = `更新时间：${meta.generated_at} ｜ 样例研报：${meta.report_count}篇 ｜ 机构：${meta.company_count}家 ｜ 品种：${meta.commodity_count}个`;

  const best = overall[0];
  document.getElementById('summary-cards').innerHTML = `
    <div class="card"><div class="label">覆盖机构</div><div class="value">${meta.company_count}</div></div>
    <div class="card"><div class="label">覆盖品种</div><div class="value">${meta.commodity_count}</div></div>
    <div class="card"><div class="label">研报样本</div><div class="value">${meta.report_count}</div></div>
    <div class="card"><div class="label">当前第一</div><div class="value">${best ? best.company_name : '-'}</div></div>
  `;

  renderTable(document.getElementById('overall-table'), overall, rankingColumns());
  renderTable(document.getElementById('weekly-table'), weekly, rankingColumns());
  renderTable(document.getElementById('monthly-table'), monthly, rankingColumns());
  renderCommodityFilters(commodity);
  renderReports(reports);
}

main().catch(err => {
  document.body.innerHTML = `<main class="container"><div class="panel"><h1>数据加载失败</h1><p>${err.message}</p></div></main>`;
});
