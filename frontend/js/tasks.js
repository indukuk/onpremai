const Tasks = {
  _tasks: [],
  _filter: 'all',
  _open: false,

  init() {
    this._bindEvents();
    this.load();
  },

  _bindEvents() {
    document.getElementById('chat-menu-btn').addEventListener('click', () => this.toggle());

    document.querySelectorAll('.task-filter').forEach(btn => {
      btn.addEventListener('click', () => this.setFilter(btn.dataset.filter));
    });
  },

  async load() {
    try {
      const response = await API.getTasks({ status: 'open' });
      this._tasks = response.tasks || response || [];
    } catch {
      this._tasks = this._getDemoTasks();
    }
    this._render();
    this._updateBadge();
  },

  // --- Toggle tasks panel ---

  toggle() {
    this._open ? this.close() : this.open();
  },

  open() {
    this._open = true;
    const section = document.getElementById('chat-section');
    const tasks = document.getElementById('chat-tasks');
    const btn = document.getElementById('chat-menu-btn');

    section.classList.add('tasks-open');
    tasks.hidden = false;
    btn.classList.add('active');
    this._render();
  },

  close() {
    this._open = false;
    const section = document.getElementById('chat-section');
    const tasks = document.getElementById('chat-tasks');
    const btn = document.getElementById('chat-menu-btn');

    section.classList.remove('tasks-open');
    tasks.hidden = true;
    btn.classList.remove('active');
  },

  // --- Render ---

  _render() {
    const container = document.getElementById('chat-tasks-cards');
    const filtered = this._getFiltered();

    if (filtered.length === 0) {
      container.innerHTML = `<div style="padding:var(--space-sm);font-size:12px;color:var(--text-muted);">No tasks.</div>`;
      return;
    }

    container.innerHTML = filtered.map(task => this._renderCard(task)).join('');
  },

  _getFiltered() {
    if (this._filter === 'all') return this._tasks;
    if (this._filter === 'overdue') return this._tasks.filter(t => this._isOverdue(t));
    return this._tasks.filter(t => t.type === this._filter);
  },

  _renderCard(task) {
    const typeClass = this._isOverdue(task) ? 'overdue' : task.type;
    const dueText = this._formatDue(task.due_date);
    const dueClass = this._isOverdue(task) ? 'overdue' : '';

    return `
      <div class="task-card task-card--${typeClass}" onclick="Tasks.openTask('${task.id}')">
        <div class="task-card-title">${this._escapeHtml(task.title)}</div>
        <div class="task-card-meta">
          ${task.framework ? `<span class="task-card-framework">${task.framework}</span>` : ''}
          ${task.control_id ? `<span class="task-card-control">${task.control_id}</span>` : ''}
          ${dueText ? `<span class="task-card-due ${dueClass}">${dueText}</span>` : ''}
        </div>
      </div>
    `;
  },

  _updateBadge() {
    document.getElementById('chat-menu-badge').textContent = this._tasks.length;
  },

  // --- Actions ---

  openTask(taskId) {
    const task = this._tasks.find(t => t.id === taskId);
    if (!task) return;

    if (task.type === 'evaluation' && task.control_id) {
      Evaluation.openInPanel(task.control_id, task.framework || 'SOC2');
      Chat._addAssistantMessage(`Opening evaluation for **${task.control_id}**`);
      Chat.expand();
    } else {
      Panel.open('task', task.title, this._renderTaskDetail(task), {
        subtitle: `${task.framework || ''} ${task.control_id || ''}`.trim(),
      });
    }
  },

  _renderTaskDetail(task) {
    return `
      <div class="panel-section">
        <div class="panel-section-title">Description</div>
        <p style="font-size:13px;color:var(--text-secondary);line-height:1.5;">${this._escapeHtml(task.description || 'No description')}</p>
      </div>
      <div class="panel-section">
        <div class="panel-section-title">Details</div>
        <div style="display:grid;grid-template-columns:100px 1fr;gap:var(--space-sm);font-size:12px;">
          <span style="color:var(--text-muted);">Type</span><span style="color:var(--text-primary);">${task.type}</span>
          <span style="color:var(--text-muted);">Framework</span><span style="color:var(--text-primary);">${task.framework || '—'}</span>
          <span style="color:var(--text-muted);">Control</span><span style="color:var(--text-primary);">${task.control_id || '—'}</span>
          <span style="color:var(--text-muted);">Due</span><span style="color:${this._isOverdue(task) ? 'var(--danger)' : 'var(--text-primary)'};">${task.due_date ? new Date(task.due_date).toLocaleDateString() : '—'}</span>
        </div>
      </div>
      <div class="panel-section">
        <button class="btn btn-primary btn-sm" onclick="Chat.expand(); Chat._addAssistantMessage('How can I help with this task?');">Ask AI</button>
      </div>
    `;
  },

  setFilter(filter) {
    this._filter = filter;
    document.querySelectorAll('.task-filter').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.filter === filter);
    });
    this._render();
  },

  _isOverdue(task) {
    if (!task.due_date) return false;
    return new Date(task.due_date) < new Date();
  },

  _formatDue(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diffDays = Math.ceil((date - now) / (1000 * 60 * 60 * 24));
    if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Tomorrow';
    if (diffDays <= 7) return `${diffDays}d`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  },

  _getDemoTasks() {
    return [
      { id: 'task-001', title: 'Upload access review evidence', type: 'evidence', framework: 'SOC2', control_id: 'CC6.1', due_date: new Date(Date.now() + 2 * 86400000).toISOString(), status: 'open', description: 'Annual user access review documentation.' },
      { id: 'task-002', title: 'Evaluate Change Management', type: 'evaluation', framework: 'SOC2', control_id: 'CC7.2', due_date: new Date(Date.now() + 5 * 86400000).toISOString(), status: 'open', description: 'System changes need documented approval.' },
      { id: 'task-003', title: 'Review vendor questionnaire', type: 'review', framework: 'SOC2', control_id: null, due_date: new Date(Date.now() - 1 * 86400000).toISOString(), status: 'open', description: 'AWS shared responsibility assessment.' },
      { id: 'task-004', title: 'Evaluate Asset Management', type: 'evaluation', framework: 'ISO27001', control_id: 'A.8.1', due_date: new Date(Date.now() + 10 * 86400000).toISOString(), status: 'open', description: 'Hardware and software asset inventory.' },
      { id: 'task-005', title: 'Update incident response policy', type: 'policy', framework: 'SOC2', control_id: 'CC7.4', due_date: new Date(Date.now() + 3 * 86400000).toISOString(), status: 'open', description: 'Policy document needs annual review.' },
    ];
  },

  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};
