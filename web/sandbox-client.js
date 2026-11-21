/** API client for the deployed demo sandbox. Tokens stay in browser storage. */
(function (root) {
  'use strict';
  const BASE_URL = 'https://34-118-11-71.nip.io/api/v1';
  const STORAGE_KEY = 'field-under-pressure.sandbox.v1';
  function create(options = {}) {
    const base = (options.baseUrl || BASE_URL).replace(/\/$/, '');
    const fetcher = options.fetch || root.fetch.bind(root);
    const storage = options.storage || root.localStorage;
    const storageKey = options.storageKey || STORAGE_KEY;
    let session = null;
    let renewal = null;
    try { session = JSON.parse(storage.getItem(storageKey) || 'null'); } catch (_) { session = null; }
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
      if (!response.ok) {
        const message = response.status === 401 ? 'Your farm session has expired.' :
          response.status === 422 ? 'The farm service rejected the inputs. Check the field and parcel limits.' : 'The farm service could not complete the request.';
        const error = new Error(message); error.status = response.status; error.detail = data?.detail; throw error;
      }
      return data;
    }
    async function start(mode) {
      if (!['mock', 'empty'].includes(mode)) throw new Error('Invalid sandbox mode.');
      const data = await request('/sandbox', { method: 'POST', body: { mode }, authenticated: false });
      if (typeof data?.token !== 'string' || !data.token) throw new Error('The farm session could not be created.');
      const next = { token: data.token, mode, expiresAt: Date.now() + Number(data.expires_in || 28800) * 1000 };
      try { storage.setItem(storageKey, JSON.stringify(next)); } catch (_) { throw new Error('Could not save your farm session in this browser.'); }
      session = next;
      return { mode, expiresAt: next.expiresAt };
    }
    return {
      hasSession: () => Boolean(session?.token),
      start,
      async places(query) {
        const path = `/places?${new URLSearchParams({ q: query })}`;
        try { return await request(path); }
        catch (error) {
          if (error.status !== 401 || !session?.mode) throw error;
          if (!renewal) renewal = start(session.mode).finally(() => { renewal = null; });
          await renewal;
          return request(path);
        }
      },
      fields: () => request('/fields'),
      clock: () => request('/clock'),
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
      addSpray: (id, body) => request(`/crop-areas/${encodeURIComponent(id)}/sprays`, { method: 'POST', body })
    };
  }
  root.SandboxClient = { create, BASE_URL, STORAGE_KEY };
  if (typeof module !== 'undefined' && module.exports) module.exports = { create, BASE_URL, STORAGE_KEY };
})(typeof globalThis !== 'undefined' ? globalThis : this);
