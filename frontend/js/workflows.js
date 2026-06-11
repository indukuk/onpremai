const Workflows = {
  _active: null,

  show(playbook) {
    this._active = playbook;
    const container = document.getElementById('chat-workflow');
    const stepsEl = document.getElementById('workflow-steps');

    if (!playbook || !playbook.steps) {
      container.hidden = true;
      return;
    }

    container.hidden = false;
    stepsEl.innerHTML = playbook.steps.map((step, i) => {
      let stateClass = 'pending';
      if (i < playbook.current_step) stateClass = 'completed';
      else if (i === playbook.current_step) stateClass = 'active';

      const indicator = stateClass === 'completed' ? '&#10003;' : (i + 1);

      return `
        <div class="workflow-step workflow-step--${stateClass}">
          <div class="workflow-step-indicator">${indicator}</div>
          <span class="workflow-step-label">${step.name}</span>
        </div>
        ${i < playbook.steps.length - 1 ? '<div class="workflow-step-connector"></div>' : ''}
      `;
    }).join('');
  },

  hide() {
    this._active = null;
    document.getElementById('chat-workflow').hidden = true;
  },

  renderInMessage(playbook) {
    if (!playbook || !playbook.steps) return '';

    const steps = playbook.steps.map((step, i) => {
      let iconClass = 'pending';
      let icon = i + 1;
      if (i < playbook.current_step) { iconClass = 'done'; icon = '&#10003;'; }
      else if (i === playbook.current_step) { iconClass = 'active'; icon = '&#9679;'; }

      const stepClass = i === playbook.current_step ? 'active' : (i < playbook.current_step ? 'done' : '');

      return `
        <div class="workflow-progress-step ${stepClass}">
          <div class="workflow-progress-icon ${iconClass}">${icon}</div>
          <span class="workflow-progress-label">${step.name}</span>
        </div>
      `;
    }).join('');

    return `
      <div class="workflow-card">
        <div class="workflow-card-title">${playbook.name || 'Workflow'}</div>
        <div class="workflow-progress">${steps}</div>
      </div>
    `;
  },

  renderTimeline(steps) {
    return `
      <div class="workflow-timeline">
        ${steps.map((step, i) => {
          const stateClass = step.completed ? 'done' : (step.active ? 'active' : '');
          return `
            <div class="workflow-timeline-item ${stateClass}">
              <div class="workflow-timeline-dot"></div>
              <div class="workflow-timeline-content">
                <div class="workflow-timeline-title">${step.title}</div>
                <div class="workflow-timeline-desc">${step.description || ''}</div>
                ${step.meta ? `<div class="workflow-timeline-meta">${step.meta}</div>` : ''}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  getPlaybooks() {
    return [
      {
        id: 'evidence-collection',
        name: 'Evidence Collection',
        description: 'Guided evidence gathering for a control',
        icon: '&#128194;',
        steps: [
          { name: 'Identify requirements' },
          { name: 'Check existing evidence' },
          { name: 'Generate upload list' },
          { name: 'Validate completeness' },
        ],
      },
      {
        id: 'gap-analysis',
        name: 'Gap Analysis',
        description: 'Find compliance gaps across a framework',
        icon: '&#128269;',
        steps: [
          { name: 'Select framework' },
          { name: 'Scan controls' },
          { name: 'Identify gaps' },
          { name: 'Prioritize remediation' },
        ],
      },
      {
        id: 'vendor-assessment',
        name: 'Vendor Risk Assessment',
        description: 'Evaluate third-party vendor compliance',
        icon: '&#127970;',
        steps: [
          { name: 'Collect questionnaire' },
          { name: 'Analyze responses' },
          { name: 'Score risk' },
          { name: 'Generate report' },
        ],
      },
      {
        id: 'incident-response',
        name: 'Incident Response',
        description: 'Handle a compliance incident',
        icon: '&#128680;',
        steps: [
          { name: 'Document incident' },
          { name: 'Assess impact' },
          { name: 'Notify stakeholders' },
          { name: 'Remediate & close' },
        ],
      },
    ];
  },

  renderPlaybookList() {
    const playbooks = this.getPlaybooks();
    return `
      <div class="playbook-list">
        ${playbooks.map(p => `
          <div class="playbook-item" onclick="Workflows.startPlaybook('${p.id}')">
            <div class="playbook-icon">${p.icon}</div>
            <div class="playbook-info">
              <div class="playbook-name">${p.name}</div>
              <div class="playbook-desc">${p.description}</div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  },

  startPlaybook(id) {
    const playbook = this.getPlaybooks().find(p => p.id === id);
    if (!playbook) return;

    const active = { ...playbook, current_step: 0 };
    this.show(active);

    Chat._showChatView();
    Chat._addAssistantMessage(
      `Starting **${playbook.name}**. I'll guide you through each step.\n\nStep 1: **${playbook.steps[0].name}** — let me gather what's needed.`
    );
  },
};
