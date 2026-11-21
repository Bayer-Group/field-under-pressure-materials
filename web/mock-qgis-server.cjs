#!/usr/bin/env node
/** Serve a read-only GeoJSON snapshot of the frontend mock for QGIS. */
'use strict';

const http = require('node:http');
const { createMockProvider } = require('./farmer-data.js');

const portText = process.env.FARMER_MOCK_PORT || '8765';
const port = Number(portText);
if (!/^\d+$/.test(portText) || !Number.isInteger(port) || port < 1 || port > 65535) {
  console.error('FARMER_MOCK_PORT must be a port number between 1 and 65535.');
  process.exit(1);
}

/** Build QGIS-friendly features from the frontend provider's fictional plots. */
async function buildFeatures() {
  const provider = createMockProvider();
  const { fields } = await provider.listFields();
  const { parcels } = await Promise.all(
    Array.from({ length: 5 }, (_, index) => provider.findParcels({ number: `DEMO-${String(index + 1).padStart(3, '0')}` }))
  ).then(results => ({ parcels: results.flatMap(result => result.parcels) }));
  const byParcel = new Map(fields.map(field => [field.parcel.parcel_id, field]));
  return {
    type: 'FeatureCollection',
    features: parcels.flatMap(parcel => {
      const field = byParcel.get(parcel.parcel_id);
      if (!field) return [{
        type: 'Feature', geometry: parcel.geometry,
        properties: { parcel_id: parcel.parcel_id, parcel_number: parcel.parcel_number,
          field_id: null, crop_area_id: null, farmer_crop_id: null, map_crop_id: null,
          sowing_date: null, past_sprays: '[]', plot_status: 'empty', data_status: 'mock' }
      }];
      return field.crop_areas.map(area => ({
        type: 'Feature', geometry: area.geometry,
        properties: { parcel_id: parcel.parcel_id, parcel_number: parcel.parcel_number,
          field_id: field.field_id, crop_area_id: area.crop_area_id,
          farmer_crop_id: area.crop.farmer_crop_id, map_crop_id: area.crop.map_crop_id,
          sowing_date: area.sowing_date, past_sprays: JSON.stringify(area.past_sprays),
          plot_status: 'saved', data_status: 'mock' }
      }));
    })
  };
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  if (request.method !== 'GET' || url.pathname !== '/mock/plots.geojson') {
    response.writeHead(request.method === 'GET' ? 404 : 405, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    response.end(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'Use GET /mock/plots.geojson.' } }));
    return;
  }
  try {
    const geojson = await buildFeatures();
    response.writeHead(200, { 'Content-Type': 'application/geo+json; charset=utf-8', 'Cache-Control': 'no-store' });
    response.end(JSON.stringify(geojson));
  } catch (error) {
    console.error('Failed to build mock layer:', error.message);
    response.writeHead(500, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    response.end(JSON.stringify({ error: { code: 'MOCK_ERROR', message: 'Could not build the mock layer.' } }));
  }
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Read-only fictional mock layer: http://127.0.0.1:${port}/mock/plots.geojson`);
});
