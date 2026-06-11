const Router = {
  _routes: {},
  _current: null,

  register(path, handler) {
    this._routes[path] = handler;
  },

  init() {
    window.addEventListener('hashchange', () => this._resolve());
    this._resolve();
  },

  _resolve() {
    const hash = window.location.hash || '#/dashboard';
    const [path, ...params] = hash.slice(1).split('/').filter(Boolean);
    const route = '/' + path;

    // Update nav active state
    document.querySelectorAll('.nav-link').forEach(link => {
      link.classList.toggle('active', link.dataset.page === path);
    });

    const handler = this._routes[route];
    if (handler) {
      this._current = route;
      handler(params);
    } else {
      this._render404();
    }
  },

  navigate(path) {
    window.location.hash = '#' + path;
  },

  _render404() {
    document.getElementById('page-content').innerHTML = `
      <div style="text-align:center;padding:60px;">
        <h2 style="color:var(--text-primary)">Page not found</h2>
        <p style="color:var(--text-muted)">The page you're looking for doesn't exist.</p>
        <a href="#/dashboard" class="btn btn-primary" style="margin-top:16px">Go to Dashboard</a>
      </div>
    `;
  },
};
