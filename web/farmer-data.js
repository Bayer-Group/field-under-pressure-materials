/** Frontend-local farmer data provider for the contract in FARMER_INPUT_CONTRACT.md. */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.FarmerData = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const crops = [
    { id: 'wheat', label: 'Pszenica' },
    { id: 'soy', label: 'Soja' },
    { id: 'maize', label: 'Kukurydza' }
  ];
  const copy = value => JSON.parse(JSON.stringify(value));
  const polygon = (west, south, east, north) => ({
    type: 'Polygon', coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
  });
  const parcels = [
    { parcel_number: '123/4', cadastral_id: '141201_1.0001.123/4', locality: 'Krzewie', commune: 'Wolsztyn', area_ha: 2.35 },
    { parcel_number: '124/1', cadastral_id: '141201_1.0001.124/1', locality: 'Krzewie', commune: 'Wolsztyn', area_ha: 1.82 },
    { parcel_number: '123/4', cadastral_id: '080401_2.0002.123/4', locality: 'Krzewie', commune: 'Nowa Sól', area_ha: 0.98 },
    { parcel_number: '77/2', cadastral_id: '301204_5.0001.77/2', locality: 'Nowa Wieś', commune: 'Siedlec', area_ha: 3.17 },
    { parcel_number: '18/3', cadastral_id: '301204_5.0002.18/3', locality: 'Teresin', commune: 'Wolsztyn', area_ha: 1.42 }
  ].map((metadata, i) => ({
    parcel_id: `parcel-demo-${i + 1}`,
    ...metadata,
    geometry: polygon(20.75 + i * 0.01, 52.17, 20.76 + i * 0.01, 52.18)
  }));
  const initialFields = parcels.slice(0, 3).map((parcel, i) => ({
    field_id: `field-demo-${i + 1}`,
    parcel,
    crop_areas: [{
      crop_area_id: `area-demo-${i + 1}`,
      geometry: parcel.geometry,
      crop: { farmer_crop_id: i === 1 ? 'soy' : 'wheat', map_crop_id: i === 0 ? 'maize' : null },
      sowing_date: '2024-09-15',
      past_sprays: i === 0 ? [{ date: '2024-10-10', protection_duration_days: 14 }] : []
    }],
    data_status: 'mock'
  }));
  // The first plot has two crop areas to exercise the agreed example.
  initialFields[0].crop_areas[0].geometry = polygon(20.75, 52.17, 20.755, 52.18);
  initialFields[0].crop_areas.push({
    crop_area_id: 'area-demo-1b', geometry: polygon(20.755, 52.17, 20.76, 52.18),
    crop: { farmer_crop_id: 'soy', map_crop_id: null }, sowing_date: '2024-09-20', past_sprays: []
  });

  /** Create an error with the contract's response shape and HTTP-like status. */
  function providerError(status, code, message, fields) {
    const error = new Error(message);
    error.status = status;
    error.error = { code, message };
    if (fields && fields.length) error.error.fields = fields;
    return error;
  }

  /** Validate a calendar date without accepting JavaScript date rollover. */
  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
  }

  /** Check the basic GeoJSON polygon contract, including closed coordinate rings. */
  function validPolygon(geometry) {
    return !!geometry && geometry.type === 'Polygon' && Array.isArray(geometry.coordinates) &&
      geometry.coordinates.length > 0 && geometry.coordinates.every(ring =>
        Array.isArray(ring) && ring.length >= 4 && ring.every(point =>
          Array.isArray(point) && point.length >= 2 && Number.isFinite(point[0]) &&
          Number.isFinite(point[1]) && Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90
        ) && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
      ) && geometry.coordinates.every(ring => {
        let twiceArea = 0;
        for (let i = 0; i < ring.length - 1; i++) {
          twiceArea += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
        }
        return Math.abs(twiceArea) > 1e-12;
      });
  }

  /** Check if a point is inside a ring; boundary points count as matches. */
  function ringContains(ring, x, y) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      const cross = (x - xi) * (yj - yi) - (y - yi) * (xj - xi);
      if (Math.abs(cross) < 1e-12 && x >= Math.min(xi, xj) && x <= Math.max(xi, xj) &&
          y >= Math.min(yi, yj) && y <= Math.max(yi, yj)) return true;
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  /** Validate the agreed save contract and return errors with field paths. */
  function validateField(id, field) {
    const errors = [];
    const add = (path, message) => errors.push({ path, message });
    if (!field || typeof field !== 'object' || Array.isArray(field)) {
      add('field', 'Enter a field object.');
      return errors;
    }
    if (field.field_id !== id) add('field_id', 'The field ID must match the requested ID.');
    if (!field.parcel || !parcels.some(p => p.parcel_id === field.parcel.parcel_id)) {
      add('parcel', 'Select a mock parcel.');
    }
    if (!Array.isArray(field.crop_areas) || field.crop_areas.length === 0) {
      add('crop_areas', 'Add at least one crop area.');
      return errors;
    }
    const areaIds = new Set();
    field.crop_areas.forEach((area, index) => {
      const path = `crop_areas[${index}]`;
      if (!area || typeof area !== 'object') { add(path, 'Enter a crop area.'); return; }
      if (typeof area.crop_area_id !== 'string' || !area.crop_area_id.trim() || areaIds.has(area.crop_area_id)) {
        add(`${path}.crop_area_id`, 'Enter a unique crop area ID.');
      } else areaIds.add(area.crop_area_id);
      if (!validPolygon(area.geometry)) add(`${path}.geometry`, 'Enter a valid closed GeoJSON polygon.');
      if (!area.crop || !crops.some(c => c.id === area.crop.farmer_crop_id)) add(`${path}.crop.farmer_crop_id`, 'Select an available crop.');
      if (!validDate(area.sowing_date)) add(`${path}.sowing_date`, 'Enter a valid date in YYYY-MM-DD format.');
      if (!Array.isArray(area.past_sprays)) add(`${path}.past_sprays`, 'Enter a list of past sprays.');
      else area.past_sprays.forEach((spray, j) => {
        if (!spray || !validDate(spray.date)) add(`${path}.past_sprays[${j}].date`, 'Enter a valid date in YYYY-MM-DD format.');
        if (!spray || !Number.isFinite(spray.protection_duration_days) || spray.protection_duration_days <= 0) {
          add(`${path}.past_sprays[${j}].protection_duration_days`, 'Enter a positive duration in days.');
        }
      });
    });
    return errors;
  }

  /** Build a frontend-local provider; each instance keeps edits only until page reload. */
  function createMockProvider(options = {}) {
    const fields = new Map(initialFields.map(field => [field.field_id, copy(field)]));
    let available = options.available !== false;
    const requireService = () => {
      if (!available) throw providerError(503, 'SERVICE_UNAVAILABLE', 'The mock service is unavailable. Please retry.');
    };
    return {
      mode: 'mock',
      storageLifetime: 'memory: changes are lost when the provider is recreated or the page reloads',
      setAvailable(value) { available = Boolean(value); },
      async findParcels(query) {
        requireService();
        if (!query || typeof query !== 'object') throw providerError(400, 'INVALID_REQUEST', 'Provide a parcel number or map coordinates.');
        const byNumber = typeof query.number === 'string' && query.number.trim() !== '';
        const byCoordinates = Number.isFinite(query.lon) && Number.isFinite(query.lat) && Math.abs(query.lon) <= 180 && Math.abs(query.lat) <= 90;
        if (byNumber === byCoordinates) throw providerError(400, 'INVALID_REQUEST', 'Provide either a parcel number or valid map coordinates.');
        let results;
        if (!byNumber) results = parcels.filter(p => ringContains(p.geometry.coordinates[0], query.lon, query.lat));
        else {
          const term = query.number.trim();
          const fullId = /^\d{6}_\d\.\d{4}\.\d+(?:\/\d+)?$/.test(term);
          const combined = term.match(/^(.+?)\s+(\d+(?:\/\d*)?)$/);
          const number = query.locality ? term : (combined ? combined[2] : term);
          const locality = query.locality || (combined ? combined[1] : '');
          results = fullId ? parcels.filter(p => p.cadastral_id.toLowerCase() === term.toLowerCase()) :
            /^\d+(?:\/\d*)?$/.test(number) ? parcels.filter(p => p.parcel_number.toLowerCase().startsWith(number.toLowerCase()) &&
              (!locality || `${p.locality} ${p.commune}`.toLowerCase().startsWith(locality.toLowerCase()))) :
              parcels.filter(p => `${p.locality} ${p.commune}`.toLowerCase().startsWith(term.toLowerCase()));
        }
        return { parcels: copy(results), data_status: 'mock' };
      },
      async getCrops() { requireService(); return { crops: copy(crops), data_status: 'mock' }; },
      async listFields() { requireService(); return { fields: copy([...fields.values()]), data_status: 'mock' }; },
      async getField(id) {
        requireService();
        if (!fields.has(id)) throw providerError(404, 'NOT_FOUND', 'Field not found.');
        return copy(fields.get(id));
      },
      async saveField(id, field) {
        requireService();
        if (typeof id !== 'string' || !id.trim()) throw providerError(400, 'INVALID_REQUEST', 'Enter a field ID.');
        const errors = validateField(id, field);
        if (errors.length) throw providerError(422, 'VALIDATION_ERROR', 'Check the entered data.', errors);
        const saved = copy(field);
        saved.parcel = copy(parcels.find(p => p.parcel_id === field.parcel.parcel_id));
        saved.data_status = 'mock';
        fields.set(id, saved);
        return copy(saved);
      }
    };
  }

  /** Build a provider with the same methods using the real backend's agreed paths. */
  function createBackendProvider(options = {}) {
    const baseUrl = (options.baseUrl || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
    const fetcher = options.fetch || (typeof fetch === 'function' && fetch.bind(globalThis));
    if (!fetcher) throw new Error('A fetch implementation is required.');
    async function request(path, init) {
      let response;
      try { response = await fetcher(baseUrl + path, init); }
      catch (_) { throw providerError(503, 'SERVICE_UNAVAILABLE', 'The backend is unavailable. Please retry.'); }
      let data;
      try { data = await response.json(); }
      catch (_) { throw providerError(502, 'INVALID_RESPONSE', 'The backend returned an invalid response.'); }
      if (!response.ok) {
        const detail = data && data.error;
        throw providerError(response.status, detail && detail.code || 'BACKEND_ERROR',
          detail && detail.message || 'The backend request failed.', detail && detail.fields);
      }
      return data;
    }
    return {
      mode: 'backend', storageLifetime: 'determined by the backend',
      findParcels(query) {
        const params = new URLSearchParams();
        if (query && query.number !== undefined) params.set('number', query.number);
        if (query && query.locality !== undefined) params.set('locality', query.locality);
        if (query && query.lon !== undefined) params.set('lon', query.lon);
        if (query && query.lat !== undefined) params.set('lat', query.lat);
        return request(`/parcels?${params}`);
      },
      getCrops: () => request('/crops'),
      listFields: () => request('/fields'),
      getField: id => request(`/fields/${encodeURIComponent(id)}`),
      saveField: (id, field) => request(`/fields/${encodeURIComponent(id)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(field)
      })
    };
  }

  /** Select a mock or backend provider through configuration. */
  function createProvider(options = {}) {
    if (!options.mode || options.mode === 'mock') return createMockProvider(options);
    if (options.mode === 'backend') return createBackendProvider(options);
    throw new Error(`Unknown farmer data provider mode: ${options.mode}`);
  }

  return { createProvider, createMockProvider, createBackendProvider };
});
