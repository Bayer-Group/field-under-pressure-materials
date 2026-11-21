import type {
  CropPrefDoc,
  ObjectIdString,
  OrchardBoundaryDoc,
  SaveOrchardLayoutRequest,
  SaveOrchardLayoutResponse,
} from '../types/orchard';

/**
 * [PLACEHOLDER] Static snapshot copied from the local MongoDB `field_under_pressure` database:
 * - `CropPref`: all 5 real species documents & ObjectIds
 * - `Orchard`: real parcel `_id: 6b01933c1dc02a368703a020` (WGS 84 / EPSG:4326 MultiPolygon ring)
 *
 * Remove `src/placeholders/` once the backend API is serving live data.
 */

export function getPlaceholderCropPrefs(): CropPrefDoc[] {
  return [
    {
      _id: '6b00ce879a422805ed102006',
      code: 'malus-domestica',
      scientificName: 'Malus domestica',
      namePl: 'Jabłoń domowa',
      nameEn: 'Apple',
      variety: 'Malus domestica',
      category: 'pome',
      recommendedSpacingMeters: 3.5,
      colorHex: '#ef4444',
    },
    {
      _id: '6b00ceb29a422805ed102009',
      code: 'pyrus-communis',
      scientificName: 'Pyrus communis',
      namePl: 'Grusza pospolita',
      nameEn: 'Pear',
      variety: 'Pyrus communis',
      category: 'pome',
      recommendedSpacingMeters: 3.8,
      colorHex: '#84cc16',
    },
    {
      _id: '6b00cea79a422805ed102008',
      code: 'prunus-avium',
      scientificName: 'Prunus avium',
      namePl: 'Czereśnia ptasia',
      nameEn: 'Sweet Cherry',
      variety: 'Prunus avium',
      category: 'stone',
      recommendedSpacingMeters: 4.5,
      colorHex: '#e11d48',
    },
    {
      _id: '6b00ce999a422805ed102007',
      code: 'prunus-armeniaca',
      scientificName: 'Prunus armeniaca',
      namePl: 'Morela pospolita',
      nameEn: 'Apricot',
      variety: 'Prunus armeniaca',
      category: 'stone',
      recommendedSpacingMeters: 4.2,
      colorHex: '#f97316',
    },
    {
      _id: '6b00ce729a422805ed102005',
      code: 'juglans-regia',
      scientificName: 'Juglans regia',
      namePl: 'Orzech włoski',
      nameEn: 'Walnut',
      variety: 'Juglans regia',
      category: 'nut',
      recommendedSpacingMeters: 7.0,
      colorHex: '#8b5cf6',
    },
  ];
}

/**
 * Exact orchard parcel geometry from local MongoDB `Orchard` (`_id: 6b01933c1dc02a368703a020`).
 * Coordinates are in WGS 84 (EPSG:4326), converted from GeoJSON MultiPolygon `[lng, lat, 0]`.
 * Starts with empty `rows: []` for first-time row line drawing.
 */
export function getPlaceholderOrchardBoundary(orchardId: ObjectIdString): OrchardBoundaryDoc {
  // Real outer ring vertices from db.Orchard.findOne({ _id: ObjectId('6b01933c1dc02a368703a020') })
  const geometry = [
    { lat: 51.84447031436461, lng: 20.85185092156493 },
    { lat: 51.845577735233036, lng: 20.85194842604751 },
    { lat: 51.845542724553376, lng: 20.853352285976772 },
    { lat: 51.845774353581064, lng: 20.853382621744633 },
    { lat: 51.845798670667115, lng: 20.855111625449258 },
    { lat: 51.84446227417943, lng: 20.853588952884014 },
  ];

  return {
    _id: orchardId || '6b01933c1dc02a368703a020',
    name: 'Grojec A',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    geometry,
    center: {
      lat: 51.8450065,
      lng: 20.8530536,
    },
    areaHectares: 2.22,
    shapeAreaM2: 22195.94,
    shapeLengthM: 666.7,
    rows: [],
  };
}

export function getPlaceholderSaveOrchardLayoutResponse(
  payload: SaveOrchardLayoutRequest,
): SaveOrchardLayoutResponse {
  return {
    orchardId: payload.orchardId,
    savedRowsCount: payload.orchardRows.length,
    savedTreesCount: payload.trees.length,
    updatedAt: new Date().toISOString(),
    orchard: {
      _id: payload.orchardId,
      rows: payload.orchardRows,
    },
    trees: payload.trees,
  };
}
