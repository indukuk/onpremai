const Chat = {
  _sessionId: null,
  _expanded: false,
  _messages: [],

  init() {
    this._sessionId = sessionStorage.getItem('chat_session_id') || this._generateId();
    sessionStorage.setItem('chat_session_id', this._sessionId);
    this._bindEvents();
    this._initSession();
  },

  _generateId() {
    return 'sess_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  },

  _bindEvents() {
    const input = document.getElementById('chat-bar-input');
    const send = document.getElementById('chat-bar-send');

    input.addEventListener('input', () => { send.disabled = !input.value.trim(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._sendMessage(); }
    });
    input.addEventListener('focus', () => { if (!this._expanded) this.expand(); });

    send.addEventListener('click', () => this._sendMessage());
    document.getElementById('chat-minimize-btn').addEventListener('click', () => this.collapse());
    document.getElementById('confirm-yes')?.addEventListener('click', () => this._handleConfirm(true));
    document.getElementById('confirm-no')?.addEventListener('click', () => this._handleConfirm(false));

    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'j') { e.preventDefault(); this.toggleExpand(); }
      if (e.key === 'Escape' && this._expanded && !Panel.isOpen()) this.collapse();
    });
  },

  async _initSession() {
    try {
      const response = await API.chatInit(this._sessionId);
      if (response?.message) this._addAssistantMessage(response.message, response.actions);
    } catch {
      this._addAssistantMessage(`Hi ${Auth.getUserName()}! Try "show CC6.1 evaluation" or click the ⊞ icon for tasks.`);
    }
  },

  expand() {
    this._expanded = true;
    document.getElementById('chat-section').classList.add('expanded');
    document.getElementById('chat-messages-area').hidden = false;
    this._scrollToBottom();
  },

  collapse() {
    this._expanded = false;
    document.getElementById('chat-section').classList.remove('expanded');
    document.getElementById('chat-messages-area').hidden = true;
  },

  toggleExpand() { this._expanded ? this.collapse() : this.expand(); },

  async _sendMessage() {
    const input = document.getElementById('chat-bar-input');
    const text = input.value.trim();
    if (!text) return;
    if (!this._expanded) this.expand();

    this._addUserMessage(text);
    input.value = '';
    document.getElementById('chat-bar-send').disabled = true;

    if (this._handleCommand(text)) return;

    this._showTyping();
    try {
      let fullResponse = '', actions = [], pendingConfirmation = null;
      await API.chatStream(text, this._sessionId,
        (chunk) => {
          if (chunk.content) { fullResponse += chunk.content; this._updateStreamingMessage(fullResponse); }
          if (chunk.actions) actions = chunk.actions;
          if (chunk.pending_confirmation) pendingConfirmation = chunk.pending_confirmation;
        },
        () => {
          this._hideTyping();
          if (fullResponse) this._finalizeAssistantMessage(fullResponse, actions);
          if (pendingConfirmation) this._showConfirmation(pendingConfirmation);
        }
      );
    } catch {
      this._hideTyping();
      try {
        const response = await API.chat(text, this._sessionId);
        if (response?.message) this._addAssistantMessage(response.message, response.actions || []);
        if (response?.pending_confirmation) this._showConfirmation(response.pending_confirmation);
      } catch { this._addAssistantMessage(this._handleLocalFallback(text)); }
    }
  },

  _handleCommand(text) {
    const lower = text.toLowerCase().trim();
    const evalMatch = lower.match(/^show\s+([\w.]+)\s+eval(?:uation)?$/);
    if (evalMatch) { const id = evalMatch[1].toUpperCase(); this._addAssistantMessage(`Opening evaluation for **${id}**...`); Evaluation.openInPanel(id, 'SOC2'); return true; }

    const runMatch = lower.match(/^evaluate\s+([\w.]+)$/);
    if (runMatch) { const id = runMatch[1].toUpperCase(); this._addAssistantMessage(`Running evaluation for **${id}**...`); Evaluation.runAndOpenPanel(id, 'SOC2'); return true; }

    if (lower === 'tasks' || lower === 'show tasks') { Tasks.open(); return true; }
    if (lower === 'hide tasks') { Tasks.close(); return true; }
    if (lower === 'workflows' || lower === 'playbooks') { this._addAssistantMessage(Workflows.renderPlaybookList()); return true; }
    return false;
  },

  _handleLocalFallback(text) {
    const lower = text.toLowerCase();
    if (lower.includes('eval') && /[a-z]{2}\d/i.test(lower)) {
      const match = lower.match(/([a-z]+[\d.]+[\d]*)/i);
      if (match) { const id = match[1].toUpperCase(); Evaluation.openInPanel(id, 'SOC2'); return `Opening **${id}** evaluation.`; }
    }
    return `Offline mode. Try "show CC6.1 evaluation", "tasks", or "workflows".`;
  },

  _addUserMessage(text) {
    this._messages.push({ role: 'user', content: text });
    document.getElementById('chat-bar-messages').insertAdjacentHTML('beforeend', `
      <div class="chat-msg chat-msg--user"><div class="chat-msg-avatar">${Auth.getUserName().charAt(0)}</div><div class="chat-msg-bubble">${this._escapeHtml(text)}</div></div>
    `);
    this._scrollToBottom();
  },

  _addAssistantMessage(text, actions = []) {
    this._messages.push({ role: 'assistant', content: text, actions });
    document.getElementById('chat-bar-messages').insertAdjacentHTML('beforeend', `
      <div class="chat-msg chat-msg--assistant"><div class="chat-msg-avatar">AI</div><div><div class="chat-msg-bubble">${this._formatMarkdown(text)}</div>${this._renderActions(actions)}</div></div>
    `);
    this._scrollToBottom();
  },

  _addSystemMessage(text) {
    document.getElementById('chat-bar-messages').insertAdjacentHTML('beforeend', `
      <div class="chat-msg chat-msg--system"><div class="chat-msg-bubble">${this._escapeHtml(text)}</div></div>
    `);
    this._scrollToBottom();
  },

  _updateStreamingMessage(text) {
    let el = document.getElementById('chat-streaming');
    if (!el) { document.getElementById('chat-bar-messages').insertAdjacentHTML('beforeend', `<div class="chat-msg chat-msg--assistant" id="chat-streaming"><div class="chat-msg-avatar">AI</div><div class="chat-msg-bubble"></div></div>`); el = document.getElementById('chat-streaming'); }
    el.querySelector('.chat-msg-bubble').innerHTML = this._formatMarkdown(text);
    this._scrollToBottom();
  },

  _finalizeAssistantMessage(text, actions) {
    const el = document.getElementById('chat-streaming');
    if (el) { el.removeAttribute('id'); if (actions.length) el.querySelector('.chat-msg-bubble').insertAdjacentHTML('afterend', this._renderActions(actions)); }
    this._messages.push({ role: 'assistant', content: text, actions });
  },

  _renderActions(actions) {
    if (!actions || !actions.length) return '';
    const btns = actions.map(a => {
      if (a.navigation) return `<button class="chat-msg-action" onclick="Chat.handleAction('navigate','${a.navigation}')">${a.label || 'Go'}</button>`;
      if (a.panel) return `<button class="chat-msg-action" onclick="Chat.handleAction('panel','${a.panel}')">${a.label || 'View'}</button>`;
      return '';
    }).filter(Boolean).join('');
    return btns ? `<div class="chat-msg-actions">${btns}</div>` : '';
  },

  handleAction(type, value) {
    if (type === 'navigate') window.location.hash = value;
    else if (type === 'panel') { const [t, id] = value.split(':'); if (t === 'eval') Evaluation.openInPanel(id, 'SOC2'); }
  },

  _showTyping() { if (!document.getElementById('chat-typing-el')) { document.getElementById('chat-bar-messages').insertAdjacentHTML('beforeend', `<div class="chat-typing" id="chat-typing-el"><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div></div>`); } this._scrollToBottom(); },
  _hideTyping() { document.getElementById('chat-typing-el')?.remove(); },

  _showConfirmation(c) { this._pendingConfirmation = c; document.getElementById('confirmation-text').textContent = c.summary; document.getElementById('chat-bar-confirmation').hidden = false; },
  async _handleConfirm(approved) { document.getElementById('chat-bar-confirmation').hidden = true; if (!this._pendingConfirmation) return; try { const fn = approved ? API.chatConfirm : API.chatCancel; const r = await fn(this._sessionId, this._pendingConfirmation.confirmation_id); if (r?.message) this._addAssistantMessage(r.message); } catch { this._addSystemMessage('Confirmation failed.'); } this._pendingConfirmation = null; },

  _scrollToBottom() { const c = document.getElementById('chat-bar-messages'); requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; }); },
  _escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; },
  _formatMarkdown(t) { let h = this._escapeHtml(t); h = h.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>'); h = h.replace(/`([^`]+)`/g, '<code style="background:var(--bg-elevated);padding:1px 4px;border-radius:3px;font-size:12px;">$1</code>'); h = h.replace(/\n/g, '<br>'); return h; },
};
