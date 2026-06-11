const Evaluation = {
  _polling: null,

  async openInPanel(controlId, framework) {
    Panel.open('eval', `${controlId} Evaluation`, '', {
      subtitle: framework,
      actions: `
        <button class="panel-btn" onclick="Evaluation.runAndOpenPanel('${controlId}','${framework}')" title="Re-evaluate">&#8635;</button>
      `,
    });
    Panel.showLoading('Loading evaluation...');

    try {
      const evaluation = await API.getEvaluation(controlId, framework);
      if (evaluation) {
        Panel.updateBody(this._renderEvaluation(evaluation));
      } else {
        // No stored eval — show demo data in offline mode
        Panel.updateBody(this._renderEvaluation(this._getDemoEval(controlId)));
      }
    } catch {
      Panel.updateBody(this._renderEvaluation(this._getDemoEval(controlId)));
    }
  },

  async runAndOpenPanel(controlId, framework) {
    Panel.open('eval', `${controlId} Evaluation`, '', {
      subtitle: `${framework} — Running...`,
    });
    Panel.showLoading('Running 3-layer evaluation...');

    try {
      const { job_id } = await API.startEval(controlId, framework);
      this._pollForPanel(job_id, controlId, framework);
    } catch {
      // Demo: simulate
      setTimeout(() => {
        Panel.updateBody(this._renderEvaluation(this._getDemoEval(controlId)));
      }, 1500);
    }
  },

  _pollForPanel(jobId, controlId, framework) {
    let attempts = 0;
    this._polling = setInterval(async () => {
      attempts++;
      if (attempts > CONFIG.polling.evalMaxAttempts) {
        clearInterval(this._polling);
        Panel.updateBody('<p style="color:var(--danger)">Evaluation timed out.</p>');
        return;
      }
      try {
        const status = await API.pollEval(jobId);
        if (status.status === 'completed') {
          clearInterval(this._polling);
          Panel.updateBody(this._renderEvaluation(status.evaluation));
        } else if (status.status === 'failed') {
          clearInterval(this._polling);
          Panel.updateBody(`<p style="color:var(--danger)">Failed: ${status.error}</p>`);
        }
      } catch {
        clearInterval(this._polling);
        Panel.updateBody('<p style="color:var(--danger)">Connection error during polling.</p>');
      }
    }, CONFIG.polling.evalInterval);
  },

  // --- Render evaluation ---

  _renderEvaluation(evaluation) {
    const scorePercent = Math.round(evaluation.score * 100);
    const statusClass = evaluation.status;

    return `
      ${this._renderScoreHeader(evaluation, scorePercent, statusClass)}
      ${this._renderLayer1(evaluation)}
      ${this._renderLayer2(evaluation)}
      ${this._renderLayer3(evaluation)}
    `;
  },

  _renderScoreHeader(evaluation, scorePercent, statusClass) {
    const color = statusClass === 'compliant' ? 'var(--success)' :
                  statusClass === 'partially_compliant' ? 'var(--warning)' : 'var(--danger)';

    return `
      <div style="display:flex;align-items:center;gap:var(--space-lg);margin-bottom:var(--space-xl);padding:var(--space-lg);background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);">
        <div style="font-size:36px;font-weight:700;font-family:var(--font-mono);color:${color};">${scorePercent}%</div>
        <div>
          <div style="font-size:13px;font-weight:600;color:var(--text-primary);text-transform:capitalize;">${evaluation.status.replace(/_/g, ' ')}</div>
          ${evaluation.timing ? `<div style="font-size:11px;color:var(--text-muted);">${Math.round(evaluation.timing.total_ms)}ms</div>` : ''}
          ${evaluation.cached ? '<div style="font-size:11px;color:var(--text-muted);">Cached (evidence unchanged)</div>' : ''}
        </div>
        ${Auth.canOverride() ? `
          <div style="margin-left:auto;display:flex;gap:var(--space-sm);">
            <button class="btn btn-sm btn-ghost">Accept All</button>
          </div>
        ` : ''}
      </div>
    `;
  },

  _renderLayer1(evaluation) {
    const criteria = (evaluation.criteria_results || []).filter(c => c.method?.startsWith('rule:'));
    if (criteria.length === 0) return '';

    const rows = criteria.map(c => `
      <tr>
        <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">${c.method.replace('rule:', '')}</td>
        <td>${c.criterion_id}</td>
        <td><span class="verdict-badge verdict-${c.result.toLowerCase()}">${c.result}</span></td>
        <td style="font-size:11px;color:var(--text-secondary);">${c.reason || ''}</td>
      </tr>
    `).join('');

    return `
      <div class="panel-section">
        <div class="panel-section-title">Layer 1 — Deterministic Rules (${criteria.length})</div>
        <table class="rules-table">
          <thead><tr><th>Method</th><th>Criterion</th><th>Result</th><th>Reason</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  },

  _renderLayer2(evaluation) {
    const criteria = (evaluation.criteria_results || []).filter(c => c.method === 'llm_judgment');
    if (criteria.length === 0) return '';

    const cards = criteria.map(c => `
      <div class="tribunal-card ${c.result.toLowerCase()}" onclick="this.classList.toggle('open')">
        <div class="tribunal-header">
          <span class="tribunal-id">${c.criterion_id}</span>
          <span class="tribunal-question">${c.reason || c.criterion_id}</span>
          <span class="tribunal-verdict ${c.result.toLowerCase()}">${c.result}</span>
          ${c.confidence != null ? `<span class="tribunal-confidence">${Math.round(c.confidence * 100)}%</span>` : ''}
          <span class="tribunal-expand">&#9660;</span>
        </div>
        <div class="tribunal-body">
          ${c.prosecution ? `<div class="tribunal-section prosecution"><div class="tribunal-section-title">Prosecutor</div><div class="tribunal-text">${this._formatList(c.prosecution)}</div></div>` : ''}
          ${c.defense ? `<div class="tribunal-section defense"><div class="tribunal-section-title">Defender</div><div class="tribunal-text">${this._formatList(c.defense)}</div></div>` : ''}
          ${c.judge_reasoning ? `<div class="tribunal-section judge"><div class="tribunal-section-title">Judge</div><div class="tribunal-text">${this._escapeHtml(c.judge_reasoning.justification || JSON.stringify(c.judge_reasoning))}</div></div>` : ''}
          ${Auth.canOverride() ? `
            <div style="margin-top:var(--space-sm);display:flex;gap:var(--space-sm);">
              <button class="btn btn-sm btn-ghost">Accept</button>
              <button class="btn btn-sm btn-ghost">Override</button>
              <button class="btn btn-sm btn-ghost">Comment</button>
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');

    return `
      <div class="panel-section">
        <div class="panel-section-title">Layer 2 — Adversarial Tribunal (${criteria.length})</div>
        ${cards}
      </div>
    `;
  },

  _renderLayer3(evaluation) {
    if (!evaluation.layer_stats) return '';

    return `
      <div class="panel-section">
        <div class="panel-section-title">Layer 3 — Scoring</div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:var(--space-sm);">
          <div style="padding:var(--space-sm);background:var(--bg-card);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:18px;font-weight:700;color:var(--text-primary);">${evaluation.layer_stats.total_criteria}</div>
            <div style="font-size:10px;color:var(--text-muted);">Total</div>
          </div>
          <div style="padding:var(--space-sm);background:var(--bg-card);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:18px;font-weight:700;color:var(--success);">${evaluation.layer_stats.layer1_resolved}</div>
            <div style="font-size:10px;color:var(--text-muted);">Rules</div>
          </div>
          <div style="padding:var(--space-sm);background:var(--bg-card);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:18px;font-weight:700;color:var(--purple);">${evaluation.layer_stats.layer2_resolved}</div>
            <div style="font-size:10px;color:var(--text-muted);">Tribunal</div>
          </div>
        </div>
      </div>
    `;
  },

  _renderNoEval(controlId, framework) {
    return `
      <div style="text-align:center;padding:var(--space-2xl);">
        <p style="color:var(--text-muted);margin-bottom:var(--space-lg);">No evaluation found for ${controlId}.</p>
        <button class="btn btn-primary" onclick="Evaluation.runAndOpenPanel('${controlId}','${framework}')">Run Evaluation</button>
      </div>
    `;
  },

  // --- Demo data ---

  _getDemoEval(controlId) {
    return {
      evaluation_id: 'eval-demo-001',
      control_id: controlId,
      score: 0.92,
      status: 'compliant',
      cached: false,
      timing: { total_ms: 4200 },
      layer_stats: { total_criteria: 11, layer1_resolved: 8, layer2_resolved: 3, llm_calls: 3 },
      criteria_results: [
        { criterion_id: `${controlId}_01`, method: 'rule:file_existence', result: 'PASS', reason: 'access_review.csv exists and is current' },
        { criterion_id: `${controlId}_02`, method: 'rule:freshness', result: 'PASS', reason: 'Last modified 12 days ago (within 90-day threshold)' },
        { criterion_id: `${controlId}_03`, method: 'rule:row_count', result: 'PASS', reason: '847 rows (above minimum 10)' },
        { criterion_id: `${controlId}_04`, method: 'rule:null_rate', result: 'PASS', reason: 'reviewer column: 0% null (threshold 5%)' },
        { criterion_id: `${controlId}_05`, method: 'rule:keyword_presence', result: 'PASS', reason: '"approved" found in 94% of rows' },
        { criterion_id: `${controlId}_06`, method: 'rule:schema_presence', result: 'PASS', reason: 'Required columns present: user_id, reviewer, decision, date' },
        { criterion_id: `${controlId}_07`, method: 'rule:cross_reference', result: 'PARTIAL', reason: '12 users in IAM not found in review (98.6% coverage)' },
        { criterion_id: `${controlId}_08`, method: 'rule:quantitative', result: 'PASS', reason: 'Review completion rate 99.2% (threshold 95%)' },
        { criterion_id: `${controlId}_09`, method: 'llm_judgment', result: 'PASS', confidence: 0.91, reason: 'Evidence demonstrates comprehensive review process with appropriate segregation of duties',
          prosecution: ['No evidence of manager-level approval for privileged accounts', 'Review cadence documentation is implicit, not explicit'],
          defense: ['All privileged accounts have a distinct reviewer column entry', 'Dates show consistent quarterly pattern over 3 years'],
          judge_reasoning: { justification: 'While prosecution raises valid concerns about explicit cadence documentation, the evidence pattern across 12 quarters demonstrates a mature, consistent process. Defense point about distinct reviewers for privileged accounts is well-supported by data.' }
        },
        { criterion_id: `${controlId}_10`, method: 'llm_judgment', result: 'PASS', confidence: 0.87, reason: 'Termination access revocation evidence is timely and complete',
          prosecution: ['3 cases show >24h delay between termination and access revocation'],
          defense: ['Mean revocation time is 2.1 hours', 'The 3 outliers were weekend terminations with Monday revocation'],
          judge_reasoning: { justification: 'The 3 outliers are reasonably explained by weekend processing. Overall timeliness is excellent with 2.1h mean.' }
        },
        { criterion_id: `${controlId}_11`, method: 'llm_judgment', result: 'PARTIAL', confidence: 0.72, reason: 'Periodic access certification partially evidenced',
          prosecution: ['No formal certification sign-off document found', 'Evidence is implicit from review data, not an explicit attestation'],
          defense: ['The review process itself serves as certification', 'Manager column implies sign-off authority'],
          judge_reasoning: { justification: 'While the review data implies certification, best practice requires an explicit attestation document. Prosecution point about implicit vs explicit is valid. Partial pass recommended.' }
        },
      ],
    };
  },

  // --- Helpers ---

  _formatList(items) {
    if (Array.isArray(items)) {
      return '<ul style="margin:0;padding-left:16px;">' + items.map(i => `<li>${this._escapeHtml(i)}</li>`).join('') + '</ul>';
    }
    return this._escapeHtml(String(items));
  },

  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};
