/** API client for the farm service. Each instance owns one type of session. */
(function (root) {
  'use strict';
  const BASE_URL = 'https://34-118-11-71.nip.io/api/v1';
  const STORAGE_KEY = 'field-under-pressure.sandbox.v1';
  const ACCOUNT_STORAGE_KEY = 'field-under-pressure.account.v1';

  /** Create an independent client for a sandbox or an account session. */
  function create(options = {}) {
    const base = (options.baseUrl || BASE_URL).replace(/\/$/, '');
    const fetcher = options.fetch || root.fetch.bind(root);
    const storage = options.storage || root.localStorage;
    const kind = options.kind || 'sandbox';
    const storageKey = options.storageKey || (kind === 'account' ? ACCOUNT_STORAGE_KEY : STORAGE_KEY);

    /** Read only this client's persisted session. */
    function readSession() {
      try { return JSON.parse(storage.getItem(storageKey) || 'null'); }
      catch (_) { return null; }
    }
    let session = readSession();

    /** Report a recorded expiry even after the expired token has been discarded. */
    function sessionState() {
      if (!session) return 'none';
      if (session.expired || (session.token && (!Number.isFinite(session.expiresAt) || session.expiresAt <= Date.now()))) return 'expired';
      return session.token ? 'active' : 'none';
    }

    /** Discard the expired token without touching a replacement saved in another tab. */
    function expire(expected = session) {
      if (!expected?.token || expected !== session) return;
      session = { expired: true };
      try {
        if (readSession()?.token === expected.token) storage.setItem(storageKey, JSON.stringify(session));
      } catch (_) { /* This instance has already stopped using the token. */ }
      options.onExpired?.();
    }

    /** Use the token captured at dispatch and invalidate it on an authenticated 401. */
    async function request(path, { method = 'GET', body, authenticated = true } = {}) {
      const requestedSession = authenticated ? session : null;
      const headers = {};
      if (authenticated) {
        if (sessionState() !== 'active') {
          expire(requestedSession);
          throw Object.assign(new Error('Your farm session has expired.'), { status: 401 });
        }
        headers.Authorization = `Bearer ${requestedSession.token}`;
      }
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      let response;
      try { response = await fetcher(base + path, { method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) }); }
      catch (_) { throw new Error('Unable to reach the farm service. Please try again.'); }
      let data = null;
      if (response.status === 401 && requestedSession) expire(requestedSession);
      if (response.status !== 204) {
        try { data = await response.json(); }
        catch (_) { if (response.ok) throw new Error('The farm service returned an invalid response.'); }
      }
      if (!response.ok) {
        const message = response.status === 401 && authenticated ? 'Your farm session has expired.' :
          response.status === 422 ? 'The farm service rejected the inputs. Check the field and parcel limits.' :
          response.status === 429 ? 'Too many requests. Wait a minute and try again.' :
          'The farm service could not complete the request. Please try again.';
        const error = new Error(message); error.status = response.status; error.detail = data?.detail; throw error;
      }
      return data;
    }
    /** Keep only the token, expiry and public session information. */
    function saveSession(data, mode) {
      const ttl = data?.expires_in;
      if (typeof data?.token !== 'string' || !data.token || !Number.isFinite(ttl) || ttl <= 0) {
        throw new Error('The farm service returned an incomplete session.');
      }
      const next = { token: data.token, mode, expiresAt: Date.now() + ttl * 1000 };
      try { storage.setItem(storageKey, JSON.stringify(next)); } catch (_) { throw new Error('Could not save your farm session in this browser.'); }
      session = next;
      return { mode, expiresAt: next.expiresAt };
    }

    /** Open a sandbox only when explicitly requested. */
    async function start(mode) {
      if (kind !== 'sandbox' || !['mock', 'empty'].includes(mode)) throw new Error('Invalid sandbox mode.');
      const data = await request('/sandbox', { method: 'POST', body: { mode }, authenticated: false });
      return saveSession(data, mode);
    }

    /** Login and registration both return an account token. */
    async function authenticate(path, body) {
      if (kind !== 'account') throw new Error('An account client is required.');
      const data = await request(path, { method: 'POST', body, authenticated: false });
      return saveSession(data);
    }

    /** Sign out locally because the API has no token revocation endpoint. */
    function logout() {
      if (kind !== 'account') return;
      if (readSession()?.token === session?.token) storage.removeItem(storageKey);
      session = null;
    }

    return {
      hasSession: () => sessionState() === 'active',
      sessionState,
      restore: () => { session = readSession(); },
      expiresAt: () => session?.expiresAt,
      expire,
      start,
      login: body => authenticate('/login', body),
      register: body => authenticate('/register', body),
      logout,
      me: () => request('/me'),
      places: query => request(`/places?${new URLSearchParams({ q: query })}`),
      fields: () => request('/fields'),
      clock: () => request('/clock', { authenticated: false }),
      async crops() {
        const result = await request('/crops', { authenticated: false });
        const items = Array.isArray(result) ? result : result?.crops;
        if (!Array.isArray(items)) throw new Error('The crop catalog is unavailable.');
        return items.map(item => ({ farmer_crop_id: item.farmer_crop_id || item.id, label: item.label }));
      },
      farmerProvider() {
        return {
          mode: 'backend',
          async findParcels(query) {
            const params = new URLSearchParams();
            if (query.number !== undefined) params.set('number', query.locality ? `${query.locality} ${query.number}` : query.number);
            if (query.lon !== undefined) params.set('lon', query.lon);
            if (query.lat !== undefined) params.set('lat', query.lat);
            const result = await request(`/parcels?${params}`);
            if (!Array.isArray(result?.parcels)) throw new Error('Invalid parcel response.');
            return { ...result, parcels: result.parcels.map(parcel => ({ ...parcel, cadastral_id: parcel.cadastral_id || parcel.parcel_id, locality: parcel.locality || (typeof parcel.location === 'string' ? parcel.location : parcel.location?.locality || parcel.location?.name) || null })) };
          },
          async getCrops() {
            const result = await request('/crops', { authenticated: false });
            const items = Array.isArray(result) ? result : result?.crops;
            if (!Array.isArray(items)) throw new Error('The crop catalog is unavailable.');
            return { crops: items.map(item => ({ id: item.id || item.farmer_crop_id, label: item.label })) };
          },
          async getCropSuggestions() { return { areas: [] }; },
          async listFields() {
            const result = await request('/fields');
            if (!Array.isArray(result?.fields)) throw new Error('Invalid field response.');
            return { fields: result.fields.filter(field => field.parcel?.parcel_id) };
          },
          async listCropGroups() {
            const result = await request('/fields');
            if (!Array.isArray(result?.fields)) throw new Error('Invalid field response.');
            return { groups: result.fields.filter(field => Array.isArray(field.parcel_ids) && field.parcel_ids.length).map(field => ({ field_id: field.field_id, parcel_ids: field.parcel_ids, crop_areas: field.crop_areas })) };
          },
          validateGeometry: payload => request('/fields/validate', { method: 'POST', body: payload }),
          async saveCropGroup(payload) {
            if (!payload.field_id) throw new Error('A field ID is required.');
            return request(`/fields/${encodeURIComponent(payload.field_id)}`, { method: 'PUT', body: payload });
          },
          async importGeometry() { throw new Error('Geometry import is not available in the backend yet.'); }
        };
      },
      areas: () => request('/me/crop-areas'),
      area: id => request(`/crop-areas/${encodeURIComponent(id)}`),
      risk: (id, from, to) => request(`/crop-areas/${encodeURIComponent(id)}/risk?${new URLSearchParams({ from, to })}`),
      changes: id => request(`/crop-areas/${encodeURIComponent(id)}/changes`),
      createArea: body => request('/crop-areas', { method: 'POST', body }),
      addSpray: (id, body) => request(`/crop-areas/${encodeURIComponent(id)}/sprays`, { method: 'POST', body }),
      field: id => request(`/fields/${encodeURIComponent(id)}`),
      validateField: body => request('/fields/validate', { method: 'POST', body }),
      putField: (id, body) => request(`/fields/${encodeURIComponent(id)}`, { method: 'PUT', body }),
      gridRisk: day => request(`/grid/risk?${new URLSearchParams({ date: day })}`),
      sprayWindows: params => request(`/me/spray-window${params ? '?' + new URLSearchParams(params) : ''}`),
      sprayWindow: (id, params) => request(`/crop-areas/${encodeURIComponent(id)}/spray-window${params ? '?' + new URLSearchParams(params) : ''}`),
      sprays: id => request(`/crop-areas/${encodeURIComponent(id)}/sprays`),
      patchArea: (id, body) => request(`/crop-areas/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
      patchSpray: (id, sprayId, body) => request(`/crop-areas/${encodeURIComponent(id)}/sprays/${encodeURIComponent(sprayId)}`, { method: 'PATCH', body }),
      deleteSpray: (id, sprayId) => request(`/crop-areas/${encodeURIComponent(id)}/sprays/${encodeURIComponent(sprayId)}`, { method: 'DELETE' })
    };
  }
  root.SandboxClient = { create, BASE_URL, STORAGE_KEY, ACCOUNT_STORAGE_KEY };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.SandboxClient;
})(typeof globalThis !== 'undefined' ? globalThis : this);
