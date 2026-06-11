const CONFIG = {
  services: {
    assistant: window.DATA?.settings?.assistantUrl || '/api/chat',
    agentEval: window.DATA?.settings?.agentEvalUrl || '/api/evaluate',
    memory: window.DATA?.settings?.memoryUrl || '/api/memory',
    preprocessor: window.DATA?.settings?.preprocessorUrl || '/api/upload',
  },

  polling: {
    evalInterval: 3000,
    evalMaxAttempts: 20,
    heartbeatInterval: 30000,
  },

  session: {
    ttlHours: 4,
    maxHistory: 50,
  },

  roles: {
    canOverride: ['admin', 'compliance_manager', 'auditor'],
    canEvaluate: ['admin', 'compliance_manager', 'auditor'],
    canComment: ['admin', 'compliance_manager', 'auditor', 'contributor'],
  },
};
