// Run explicitly with: docker compose run --rm seed
const seedId = (number) => ObjectId(`fa57a1${number.toString(16).padStart(18, '0')}`);
const now = new Date();
const sampledAt = new Date(now.getTime() - 24 * 60 * 60 * 1000);
const validAt = new Date(now.getTime() + 48 * 60 * 60 * 1000);
const sampleDate = sampledAt.toISOString().slice(0, 10);
const source = 'synthetic_demo';
const counts = {};

function insertDemo(collection, id, fields) {
  const result = db.getCollection(collection).updateOne(
    { _id: id },
    { $setOnInsert: { ...fields, source } },
    { upsert: true }
  );
  counts[collection] ??= { added: 0, existing: 0 };
  counts[collection].added += result.upsertedCount;
  counts[collection].existing += result.matchedCount;
}

const cropId = seedId(1);
insertDemo('CropPref', cropId, {
  species: 'Malus domestica (DEMO)',
  Ecology: {
    'Soil pH': { Optimal: { Min: 6, Max: 7 } },
    'Soil texture': 'medium',
    'Light intensity': { Optimal: { Min: 'very bright', Max: 'clear skies' } },
    'Temperat. requir.': { Optimal: { Min: 14, Max: 27 } },
  },
});

const examples = [
  {
    id: 10, name: 'DEMO A · pole zagrożone', lng: 20.82, lat: 51.85,
    moisture: 0.06, ndvi: 0.11, ph: 4.6, texture: 12, solar: 'poor',
    sunFraction: 0.24, temperature: 35, rain: 0, et0: 5.8, forecast: 0.04,
  },
  {
    id: 20, name: 'DEMO B · niskie ryzyko', lng: 20.85, lat: 51.85,
    moisture: 0.27, ndvi: 0.72, ph: 6.4, texture: 7, solar: 'good',
    sunFraction: 0.73, temperature: 22, rain: 4.5, et0: 2.1, forecast: 0.26,
  },
];

for (const example of examples) {
  const orchardId = seedId(example.id);
  const { lng, lat } = example;
  const sceneId = `DEMO_${example.id}`;
  const solar = {
    status: 'available', source, date_local: sampleDate, timezone: 'Europe/Warsaw',
    level: example.solar, clear_sky_fraction: example.sunFraction,
    clear_sky_kwh_m2: 6, energy_kwh_m2: 6 * example.sunFraction,
  };
  const weather = {
    status: 'available', source, date_local: sampleDate,
    mean_temperature_c: example.temperature, precipitation_mm: example.rain,
    reference_et0_mm: example.et0,
  };
  insertDemo('Orchard', orchardId, {
    name: example.name,
    geometry: {
      type: 'MultiPolygon',
      coordinates: [[[
        [lng, lat], [lng + 0.002, lat], [lng + 0.002, lat + 0.002],
        [lng, lat + 0.002], [lng, lat],
      ]]],
    },
    analysis: {
      soil_moisture: {
        scene_id: sceneId, acquired_at_utc: sampledAt, mean_m3_m3: example.moisture,
        valid_pixels: 24, source,
      },
      ndvi: { mean: example.ndvi, valid_pixels: 24, source },
      soil_parameters: {
        ph: { mean: example.ph, depth_cm: 0, valid_pixels: 2, source },
        texture: { dominant_class: example.texture, depth_cm: 0, valid_pixels: 2, source },
      },
      solar_intensity: solar,
      weather,
    },
  });

  for (let i = 1; i <= 3; i++) {
    const treeId = seedId(example.id + i);
    const coordinates = { lng: lng + i * 0.00045, lat: lat + 0.001 };
    const pixelId = `${sceneId}_${i}`;
    insertDemo('Tree', treeId, { orchardId, species: cropId, coordinates, healthIndex: null });
    insertDemo('TreePixelAnalysis', seedId(100 + example.id + i), {
      orchard_id: orchardId.toHexString(),
      tree_id: treeId.toHexString(),
      species: cropId,
      scene_id: sceneId,
      acquired_at_utc: sampledAt,
      tree_coordinates_lon_lat: [coordinates.lng, coordinates.lat],
      pixel_id: pixelId,
      sample_status: 'sampled',
      pixel: { id: pixelId, soil_moisture_estimate_m3_m3: example.moisture },
      layers: {
        ndvi: { value: example.ndvi },
        soil_parameters: { ph: { value: example.ph }, texture: { value: example.texture } },
      },
      context: { date_local: sampleDate, weather, solar },
      soil_moisture_forecast: {
        status: 'available', source, anchor_pixel_id: pixelId, issued_at_utc: now,
        values: [{ valid_at_utc: validAt, soil_moisture_m3_m3: example.forecast }],
      },
    });
  }
}

printjson({ database: db.getName(), ...counts });
