const Panel = {
  _open: false,
  _type: null,
  _el: null,

  open(type, title, content, options = {}) {
    this._type = type;
    this._open = true;

    // Remove existing panel if any
    this._el?.remove();

    const workspace = document.getElementById('workspace');

    // Create panel element
    const panel = document.createElement('div');
    panel.className = 'right-panel';
    panel.id = 'right-panel';
    panel.innerHTML = `
      <div class="panel-header">
        <div class="panel-header-left">
          <div class="panel-header-icon ${type}">${this._getIcon(type)}</div>
          <div>
            <div class="panel-title">${title}</div>
            ${options.subtitle ? `<div class="panel-subtitle">${options.subtitle}</div>` : ''}
          </div>
        </div>
        <div class="panel-header-right">
          ${options.actions || ''}
          <button class="panel-btn" onclick="Panel.close()" title="Close (Esc)">&#10005;</button>
        </div>
      </div>
      ${options.tabs ? this._renderTabs(options.tabs) : ''}
      <div class="panel-body" id="panel-body">
        ${content}
      </div>
    `;

    workspace.appendChild(panel);
    this._el = panel;

    // Trigger open animation
    requestAnimationFrame(() => {
      workspace.classList.add('has-panel');
      if (options.wide) workspace.classList.add('panel-wide');
    });

    // Bind Escape key
    this._escHandler = (e) => {
      if (e.key === 'Escape') this.close();
    };
    document.addEventListener('keydown', this._escHandler);
  },

  close() {
    if (!this._open) return;
    this._open = false;
    this._type = null;

    const workspace = document.getElementById('workspace');
    workspace.classList.remove('has-panel', 'panel-wide');

    // Remove after transition
    setTimeout(() => {
      this._el?.remove();
      this._el = null;
    }, 250);

    document.removeEventListener('keydown', this._escHandler);
  },

  isOpen() {
    return this._open;
  },

  getType() {
    return this._type;
  },

  updateBody(content) {
    const body = document.getElementById('panel-body');
    if (body) body.innerHTML = content;
  },

  showLoading(message = 'Loading...') {
    this.updateBody(`
      <div class="panel-loading">
        <div class="panel-spinner"></div>
        <div class="panel-loading-text">${message}</div>
      </div>
    `);
  },

  _getIcon(type) {
    const icons = {
      eval: '&#9878;',
      evidence: '&#128196;',
      workflow: '&#9654;',
      comment: '&#128172;',
      task: '&#9744;',
    };
    return icons[type] || '&#8942;';
  },

  _renderTabs(tabs) {
    return `
      <div class="panel-tabs">
        ${tabs.map((tab, i) => `
          <button class="panel-tab ${i === 0 ? 'active' : ''}" data-tab="${tab.id}" onclick="Panel.switchTab('${tab.id}')">${tab.label}</button>
        `).join('')}
      </div>
    `;
  },

  switchTab(tabId) {
    document.querySelectorAll('.panel-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.tab === tabId);
    });
    document.querySelectorAll('.panel-tab-content').forEach(c => {
      c.hidden = c.dataset.tab !== tabId;
    });
  },
};
