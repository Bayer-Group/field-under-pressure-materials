/** API client for the deployed demo sandbox. Tokens stay in browser storage. */
(function (root) {
  'use strict';
  const BASE_URL = 'https://34-118-11-71.nip.io/api/v1';
  const STORAGE_KEY = 'field-under-pressure.sandbox.v1';
  function create(options = {}) {
    const base = (options.baseUrl || BASE_URL).replace(/\/$/, '');
    const fetcher = options.fetch || root.fetch.bind(root);
    const storage = options.storage || root.localStorage;
    let session = null;
    try { session = JSON.parse(storage.getItem(STORAGE_KEY) || 'null'); } catch (_) { session = null; }
    async function request(path, { method = 'GET', body, authenticated = true } = {}) {
      const headers = {};
      if (authenticated) {
        if (!session?.token) { const error = new Error('Sandbox session is unavailable.'); error.status = 401; throw error; }
        headers.Authorization = `Bearer ${session.token}`;
      }
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      let response;
      try { response = await fetcher(base + path, { method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) }); }
      catch (_) { throw new Error('Unable to reach the farm service. Please try again.'); }
      let data = null;
      if (response.status !== 204) { try { data = await response.json(); } catch (_) { throw new Error('The farm service returned an invalid response.'); } }
      if (!response.ok) { const error = new Error(response.status === 401 ? 'Your farm session has expired.' : 'The farm service could not complete the request.'); error.status = response.status; throw error; }
      return data;
    }
    return {
      hasSession: () => Boolean(session?.token),
      async start(mode) {
        if (!['mock', 'empty'].includes(mode)) throw new Error('Invalid sandbox mode.');
        const data = await request('/sandbox', { method: 'POST', body: { mode }, authenticated: false });
        if (typeof data?.token !== 'string' || !data.token) throw new Error('The farm session could not be created.');
        const next = { token: data.token, mode, expiresAt: Date.now() + Number(data.expires_in || 28800) * 1000 };
        try { storage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (_) { throw new Error('Could not save your farm session in this browser.'); }
        session = next;
        return { mode, expiresAt: next.expiresAt };
      },
      clock: () => request('/clock'),
      crops: () => request('/crops', { authenticated: false }),
      areas: () => request('/me/crop-areas'),
      area: id => request(`/crop-areas/${encodeURIComponent(id)}`),
      risk: (id, from, to) => request(`/crop-areas/${encodeURIComponent(id)}/risk?${new URLSearchParams({ from, to })}`),
      changes: id => request(`/crop-areas/${encodeURIComponent(id)}/changes`),
      createArea: body => request('/crop-areas', { method: 'POST', body }),
      addSpray: (id, body) => request(`/crop-areas/${encodeURIComponent(id)}/sprays`, { method: 'POST', body })
    };
  }
  root.SandboxClient = { create, BASE_URL, STORAGE_KEY };
  if (typeof module !== 'undefined' && module.exports) module.exports = { create, BASE_URL, STORAGE_KEY };
})(typeof globalThis !== 'undefined' ? globalThis : this);
