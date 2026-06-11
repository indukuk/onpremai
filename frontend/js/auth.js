const Auth = {
  _token: null,
  _claims: null,

  init() {
    this._token = sessionStorage.getItem('auth_token');
    if (this._token) {
      this._claims = this._decodeJWT(this._token);
    }
  },

  getToken() {
    return this._token;
  },

  getClaims() {
    return this._claims;
  },

  getTenantId() {
    return this._claims?.['custom:tenant_id'] || 'demo-tenant';
  },

  getUserId() {
    return this._claims?.sub || 'demo-user';
  },

  getUserName() {
    return this._claims?.name || this._claims?.email || 'User';
  },

  getRole() {
    return this._claims?.['custom:role'] || 'viewer';
  },

  canOverride() {
    return CONFIG.roles.canOverride.includes(this.getRole());
  },

  canEvaluate() {
    return CONFIG.roles.canEvaluate.includes(this.getRole());
  },

  canComment() {
    return CONFIG.roles.canComment.includes(this.getRole());
  },

  setToken(token) {
    this._token = token;
    this._claims = this._decodeJWT(token);
    sessionStorage.setItem('auth_token', token);
  },

  logout() {
    this._token = null;
    this._claims = null;
    sessionStorage.removeItem('auth_token');
  },

  isAuthenticated() {
    if (!this._token || !this._claims) return false;
    const exp = this._claims.exp;
    if (exp && Date.now() / 1000 > exp) {
      this.logout();
      return false;
    }
    return true;
  },

  _decodeJWT(token) {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return null;
      const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(atob(payload));
    } catch {
      return null;
    }
  },

  // Demo mode: set a fake token for development without Cognito
  initDemo(role = 'compliance_manager') {
    const now = Math.floor(Date.now() / 1000);
    const payload = {
      sub: 'demo-user-001',
      name: 'Demo User',
      email: 'demo@acme-corp.com',
      'custom:tenant_id': 'acme-corp',
      'custom:role': role,
      iat: now,
      exp: now + 14400,
    };
    const header = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }));
    const body = btoa(JSON.stringify(payload));
    this.setToken(`${header}.${body}.demo`);
  },
};
