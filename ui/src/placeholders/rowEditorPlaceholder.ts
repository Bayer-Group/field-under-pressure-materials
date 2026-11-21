import type {
  CropPrefDoc,
  ObjectIdString,
  OrchardBoundaryDoc,
  SaveOrchardLayoutRequest,
  SaveOrchardLayoutResponse,
} from '../types/orchard';
import { findPlaceholderOrchard } from './orchardsCatalogPlaceholder';

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
 * Exact orchard parcel geometry from local MongoDB `Orchard` (`WGS 84 / EPSG:4326`).
 * Starts with empty `rows: []` for first-time row line drawing.
 */
export function getPlaceholderOrchardBoundary(orchardId: ObjectIdString): OrchardBoundaryDoc {
  const entry = findPlaceholderOrchard(orchardId);

  return {
    _id: entry._id,
    name: entry.name,
    locationLabel: entry.locationLabel,
    geometry: entry.geometry,
    center: {
      lat: entry.centroid.lat,
      lng: entry.centroid.long,
    },
    areaHectares: entry.areaHectares,
    shapeAreaM2: entry.shapeAreaM2,
    shapeLengthM: entry.shapeLengthM,
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
