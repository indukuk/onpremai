const API = {
  async _fetch(url, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...(Auth.getToken() && { 'Authorization': `Bearer ${Auth.getToken()}` }),
      ...options.headers,
    };

    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      Auth.logout();
      window.location.hash = '#/login';
      throw new Error('Unauthorized');
    }

    return response;
  },

  // --- Chat (compliance-assistant:8081) ---

  async chatInit(sessionId) {
    const res = await this._fetch(`${CONFIG.services.assistant}/init`, {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        user_context: {
          tenant_id: Auth.getTenantId(),
          user_id: Auth.getUserId(),
          role: Auth.getRole(),
          email: Auth.getClaims()?.email || '',
          name: Auth.getUserName(),
        },
      }),
    });
    return res.json();
  },

  async chat(message, sessionId) {
    const res = await this._fetch(`${CONFIG.services.assistant}/chat`, {
      method: 'POST',
      body: JSON.stringify({
        message,
        session_id: sessionId,
        user_context: {
          tenant_id: Auth.getTenantId(),
          user_id: Auth.getUserId(),
          role: Auth.getRole(),
          email: Auth.getClaims()?.email || '',
          name: Auth.getUserName(),
        },
      }),
    });
    return res.json();
  },

  async chatStream(message, sessionId, onChunk, onDone) {
    const res = await fetch(`${CONFIG.services.assistant}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${Auth.getToken()}`,
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        stream: true,
        user_context: {
          tenant_id: Auth.getTenantId(),
          user_id: Auth.getUserId(),
          role: Auth.getRole(),
          email: Auth.getClaims()?.email || '',
          name: Auth.getUserName(),
        },
      }),
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(error.error || `HTTP ${res.status}`);
    }

    if (res.headers.get('content-type')?.includes('text/event-stream')) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
              onDone?.();
              return;
            }
            try {
              const parsed = JSON.parse(data);
              onChunk(parsed);
            } catch {
              onChunk({ content: data });
            }
          }
        }
      }
      onDone?.();
    } else {
      const data = await res.json();
      onChunk(data);
      onDone?.();
    }
  },

  async chatConfirm(sessionId, confirmationId) {
    const res = await this._fetch(`${CONFIG.services.assistant}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, confirmation_id: confirmationId }),
    });
    return res.json();
  },

  async chatCancel(sessionId, confirmationId) {
    const res = await this._fetch(`${CONFIG.services.assistant}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, confirmation_id: confirmationId }),
    });
    return res.json();
  },

  // --- Evaluations (agent-eval:8080) ---

  async startEval(controlId, framework, bypassCache = false) {
    const res = await this._fetch(`${CONFIG.services.agentEval}/evaluate`, {
      method: 'POST',
      body: JSON.stringify({
        control_id: controlId,
        framework,
        tenant_id: Auth.getTenantId(),
        bypass_cache: bypassCache,
      }),
    });
    return res.json();
  },

  async pollEval(jobId) {
    const res = await this._fetch(`${CONFIG.services.agentEval}/status/${jobId}`);
    return res.json();
  },

  // --- Evaluation results (memory-service:5000) ---

  async getEvaluation(controlId, framework) {
    const res = await this._fetch(
      `${CONFIG.services.memory}/eval/${Auth.getTenantId()}/${framework}/${controlId}/last`
    );
    if (res.status === 404) return null;
    return res.json();
  },

  async getEvalHistory(controlId, framework, limit = 10) {
    const res = await this._fetch(
      `${CONFIG.services.memory}/eval/${Auth.getTenantId()}/${framework}/${controlId}/history?limit=${limit}`
    );
    return res.json();
  },

  // --- Decisions ---

  async acceptEval(evalId, criterionId = null) {
    const res = await this._fetch(`${CONFIG.services.memory}/eval/${evalId}/accept`, {
      method: 'POST',
      body: JSON.stringify({
        criterion_id: criterionId,
        user_id: Auth.getUserId(),
        user_name: Auth.getUserName(),
      }),
    });
    return res.json();
  },

  async overrideEval(evalId, criterionId, userVerdict, reason) {
    const res = await this._fetch(`${CONFIG.services.memory}/eval/${evalId}/override`, {
      method: 'POST',
      body: JSON.stringify({
        criterion_id: criterionId,
        user_verdict: userVerdict,
        reason,
        user_id: Auth.getUserId(),
        user_name: Auth.getUserName(),
      }),
    });
    return res.json();
  },

  // --- Comments ---

  async getComments(evalId) {
    const res = await this._fetch(`${CONFIG.services.memory}/eval/${evalId}/comments`);
    return res.json();
  },

  async addComment(evalId, content, criterionId = null, parentId = null) {
    const res = await this._fetch(`${CONFIG.services.memory}/eval/${evalId}/comments`, {
      method: 'POST',
      body: JSON.stringify({
        content,
        criterion_id: criterionId,
        parent_comment_id: parentId,
        user_id: Auth.getUserId(),
        user_name: Auth.getUserName(),
      }),
    });
    return res.json();
  },

  async deleteComment(evalId, commentId) {
    return this._fetch(`${CONFIG.services.memory}/eval/${evalId}/comments/${commentId}`, {
      method: 'DELETE',
    });
  },

  // --- Tasks ---

  async getTasks(filter = {}) {
    const params = new URLSearchParams({
      tenant_id: Auth.getTenantId(),
      assignee: Auth.getUserId(),
      ...filter,
    });
    const res = await this._fetch(`${CONFIG.services.memory}/tasks?${params}`);
    return res.json();
  },

  async updateTask(taskId, updates) {
    const res = await this._fetch(`${CONFIG.services.memory}/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
    return res.json();
  },
};
