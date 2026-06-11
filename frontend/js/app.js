(function init() {
  Auth.init();
  if (!Auth.isAuthenticated()) {
    Auth.initDemo('compliance_manager');
  }

  document.getElementById('user-badge').textContent =
    `${Auth.getUserName()} (${Auth.getRole()})`;

  Router.register('/dashboard', renderDashboard);
  Router.register('/controls', renderControls);
  Router.register('/policies', renderPolicies);
  Router.register('/evidence', renderEvidence);

  Router.init();
  Tasks.init();
  Chat.init();
})();

// --- Page renderers ---

function renderDashboard() {
  document.getElementById('page-content').innerHTML = `
    <div style="max-width:1000px;">
      <h1 style="font-size:24px;font-weight:700;margin-bottom:var(--space-xl);">Compliance Dashboard</h1>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--space-lg);margin-bottom:var(--space-2xl);">
        ${statCard('Overall Score', '87%', '+3% from last month', 'var(--success)')}
        ${statCard('Controls Evaluated', '42/58', '16 pending', 'var(--primary)')}
        ${statCard('Open Tasks', '5', '1 overdue', 'var(--warning)')}
        ${statCard('AI Evaluations Today', '7', '3 cached', 'var(--purple)')}
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-xl);">
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--space-xl);">
          <h3 style="font-size:14px;font-weight:600;margin-bottom:var(--space-lg);">Recent Evaluations</h3>
          ${recentEvals()}
        </div>
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--space-xl);">
          <h3 style="font-size:14px;font-weight:600;margin-bottom:var(--space-lg);">Active Workflows</h3>
          ${activeWorkflows()}
        </div>
      </div>
    </div>
  `;
}

function statCard(label, value, sub, color) {
  return `
    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--space-xl);">
      <div style="font-size:11px;font-weight:500;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">${label}</div>
      <div style="font-size:28px;font-weight:700;color:${color};margin-top:var(--space-xs);">${value}</div>
      <div style="font-size:12px;color:var(--text-secondary);margin-top:var(--space-xs);">${sub}</div>
    </div>
  `;
}

function recentEvals() {
  const evals = [
    { id: 'CC6.1', fw: 'SOC2', score: 92, status: 'compliant' },
    { id: 'CC7.2', fw: 'SOC2', score: 71, status: 'partially_compliant' },
    { id: 'A.8.1', fw: 'ISO27001', score: 45, status: 'non_compliant' },
    { id: 'CC8.1', fw: 'SOC2', score: 88, status: 'compliant' },
  ];
  return evals.map(e => {
    const color = e.status === 'compliant' ? 'var(--success)' : e.status === 'partially_compliant' ? 'var(--warning)' : 'var(--danger)';
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-sm) var(--space-md);background:var(--bg-elevated);border-radius:var(--radius-sm);margin-bottom:var(--space-xs);cursor:pointer;" onclick="Evaluation.openInPanel('${e.id}','${e.fw}')">
        <div>
          <span style="font-size:13px;font-weight:500;">${e.id}</span>
          <span style="font-size:11px;color:var(--text-muted);margin-left:8px;">${e.fw}</span>
        </div>
        <span style="font-size:13px;font-weight:600;color:${color};">${e.score}%</span>
      </div>
    `;
  }).join('');
}

function activeWorkflows() {
  const wfs = [
    { name: 'SOC 2 Annual Audit Prep', progress: 65, status: 'In Progress' },
    { name: 'Vendor Risk Assessment — AWS', progress: 30, status: 'Step 2/4' },
  ];
  return wfs.map(w => `
    <div style="padding:var(--space-md);background:var(--bg-elevated);border-radius:var(--radius-sm);margin-bottom:var(--space-xs);">
      <div style="display:flex;justify-content:space-between;margin-bottom:var(--space-xs);">
        <span style="font-size:13px;font-weight:500;">${w.name}</span>
        <span style="font-size:11px;color:var(--text-muted);">${w.status}</span>
      </div>
      <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
        <div style="height:100%;width:${w.progress}%;background:var(--primary);border-radius:2px;"></div>
      </div>
    </div>
  `).join('');
}

function renderControls(params) {
  if (params?.[0]) {
    renderControlDetail(params[0]);
    return;
  }

  const controls = [
    { id: 'CC6.1', name: 'Logical and Physical Access', fw: 'SOC2', score: 92, status: 'compliant' },
    { id: 'CC6.2', name: 'System Access Provisioning', fw: 'SOC2', score: null },
    { id: 'CC7.2', name: 'Change Management', fw: 'SOC2', score: 71, status: 'partially_compliant' },
    { id: 'CC7.4', name: 'Incident Management', fw: 'SOC2', score: 88, status: 'compliant' },
    { id: 'CC8.1', name: 'Monitoring Activities', fw: 'SOC2', score: 45, status: 'non_compliant' },
    { id: 'A.8.1', name: 'Asset Management', fw: 'ISO27001', score: null },
  ];

  document.getElementById('page-content').innerHTML = `
    <div style="max-width:900px;">
      <h1 style="font-size:24px;font-weight:700;margin-bottom:var(--space-xl);">Controls</h1>
      <div style="display:flex;flex-direction:column;gap:var(--space-xs);">
        ${controls.map(c => {
          const color = c.status === 'compliant' ? 'var(--success)' : c.status === 'partially_compliant' ? 'var(--warning)' : c.status === 'non_compliant' ? 'var(--danger)' : 'var(--text-muted)';
          const scoreDisplay = c.score != null ? `<span style="font-weight:600;color:${color};">${c.score}%</span>` : '<span style="color:var(--text-muted);">—</span>';
          return `
            <a href="#/controls/${c.id}" style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-md) var(--space-lg);background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-md);text-decoration:none;transition:border-color 150ms ease;" onmouseover="this.style.borderColor='var(--primary)'" onmouseout="this.style.borderColor='var(--border)'">
              <div style="display:flex;align-items:center;gap:var(--space-md);">
                <span style="font-size:13px;font-family:var(--font-mono);color:var(--text-muted);min-width:50px;">${c.id}</span>
                <span style="font-size:13px;font-weight:500;color:var(--text-primary);">${c.name}</span>
                <span style="font-size:11px;color:var(--text-muted);padding:2px 6px;background:var(--bg-elevated);border-radius:var(--radius-sm);">${c.fw}</span>
              </div>
              ${scoreDisplay}
            </a>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function renderControlDetail(controlId) {
  document.getElementById('page-content').innerHTML = `
    <div style="max-width:700px;">
      <div style="display:flex;align-items:center;gap:var(--space-md);margin-bottom:var(--space-xl);">
        <a href="#/controls" style="color:var(--text-muted);text-decoration:none;font-size:13px;">&larr; Controls</a>
        <span style="color:var(--border);">/</span>
        <h1 style="font-size:20px;font-weight:700;">${controlId}</h1>
      </div>

      <div style="display:flex;gap:var(--space-sm);margin-bottom:var(--space-xl);">
        <button class="btn btn-primary" onclick="Evaluation.openInPanel('${controlId}','SOC2')">Show Evaluation</button>
        <button class="btn btn-ghost" onclick="Evaluation.runAndOpenPanel('${controlId}','SOC2')">Run New Evaluation</button>
      </div>

      <div style="padding:var(--space-xl);background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);">
        <p style="color:var(--text-secondary);font-size:13px;">
          Click "Show Evaluation" to open the AI evaluation panel on the right, or "Run New Evaluation" to trigger a fresh 3-layer assessment.
        </p>
        <p style="color:var(--text-muted);font-size:12px;margin-top:var(--space-md);">
          You can also type <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:3px;">show ${controlId} evaluation</code> in the chat bar below.
        </p>
      </div>
    </div>
  `;
}

function renderPolicies() {
  document.getElementById('page-content').innerHTML = `
    <div style="max-width:700px;">
      <h1 style="font-size:24px;font-weight:700;margin-bottom:var(--space-xl);">Policies</h1>
      <p style="color:var(--text-secondary);">Policy management with AI analysis — upload policies, auto-map to controls, detect conflicts.</p>
    </div>
  `;
}

function renderEvidence() {
  document.getElementById('page-content').innerHTML = `
    <div style="max-width:700px;">
      <h1 style="font-size:24px;font-weight:700;margin-bottom:var(--space-xl);">Evidence</h1>
      <p style="color:var(--text-secondary);">Evidence repository — upload, track, and validate compliance evidence across all controls.</p>
    </div>
  `;
}
