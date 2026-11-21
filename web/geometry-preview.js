/** Immediate, non-authoritative polygon feedback using Turf.js. */
(function (root) {
  'use strict';

  function inspect(parcels, areas, turf) {
    if (!turf) throw new Error('Geometry preview is unavailable.');
    const parcelFeatures = parcels.map(parcel => turf.feature(parcel.geometry));
    const areaFeatures = areas.map(area => turf.feature(area.geometry, { id: area.crop_area_id }));
    if (!parcelFeatures.length) throw new Error('No selected parcels.');
    const invalid = areaFeatures.filter(feature => {
      try { return !turf.booleanValid(feature) || turf.kinks(feature).features.length > 0; }
      catch (_) { return true; }
    });
    if (invalid.length) return { invalid: invalid.map(item => item.properties.id), overlaps: [], gaps: [], outside: [] };
    const combine = features => features.length === 1 ? features[0] : turf.union(turf.featureCollection(features));
    const difference = (a, b) => turf.difference(turf.featureCollection([a, b]));
    const parcelUnion = combine(parcelFeatures);
    if (!parcelUnion) throw new Error('Could not combine parcels.');
    const overlaps = [];
    for (let i = 0; i < areaFeatures.length; i++) {
      for (let j = i + 1; j < areaFeatures.length; j++) {
        const intersection = turf.intersect(turf.featureCollection([areaFeatures[i], areaFeatures[j]]));
        if (intersection) overlaps.push({ crop_area_ids: [areaFeatures[i].properties.id, areaFeatures[j].properties.id], geometry: intersection.geometry });
      }
    }
    const outside = areaFeatures.map(feature => ({ feature, outside: difference(feature, parcelUnion) }))
      .filter(item => item.outside).map(item => ({ crop_area_id: item.feature.properties.id, geometry: item.outside.geometry }));
    const covered = areaFeatures.length ? combine(areaFeatures) : null;
    const gap = covered ? difference(parcelUnion, covered) : parcelUnion;
    return { invalid: [], overlaps, outside, gaps: gap ? [{ geometry: gap.geometry }] : [] };
  }
  /** Remove only duplicate or numerically collinear vertices without changing a ring's shape. */
  function removeRedundantVertices(geometry) {
    if (!geometry || geometry.type !== 'Polygon' || !Array.isArray(geometry.coordinates)) return geometry;
    const rings = geometry.coordinates.map(ring => {
      if (!Array.isArray(ring) || ring.length < 5 || ring.some(point => !Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite))) return ring;
      if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) return ring;
      const points = ring.slice(0, -1).map(point => [...point]);
      let removed = true;
      while (removed && points.length > 3) {
        removed = false;
        for (let i = 0; i < points.length; i++) {
          const a = points[(i + points.length - 1) % points.length], b = points[i], c = points[(i + 1) % points.length];
          const dx = c[0] - a[0], dy = c[1] - a[1], length = dx * dx + dy * dy;
          const scale = Math.max(1, ...a.map(Math.abs), ...b.map(Math.abs), ...c.map(Math.abs));
          const tolerance = 64 * Number.EPSILON * scale;
          const t = length ? ((b[0] - a[0]) * dx + (b[1] - a[1]) * dy) / length : -1;
          const redundant = length ? t >= 0 && t <= 1 && Math.abs(dx * (b[1] - a[1]) - dy * (b[0] - a[0])) <= tolerance * Math.sqrt(length) :
            Math.hypot(b[0] - a[0], b[1] - a[1]) <= tolerance;
          if (redundant) { points.splice(i, 1); removed = true; break; }
        }
      }
      return [...points, [...points[0]]];
    });
    return { ...geometry, coordinates: rings };
  }

  /** Propose a draft change; never persist or decide which crop owns an area. */
  function propose(kind, areaGeometry, findingGeometry, parcels, turf) {
    if (!turf) throw new Error('Geometry tools are unavailable.');
    const area = turf.feature(areaGeometry);
    let result;
    if (kind === 'clip') {
      const boundaries = parcels.map(parcel => turf.feature(parcel.geometry));
      if (!boundaries.length) throw new Error('No parcels selected.');
      const union = boundaries.length === 1 ? boundaries[0] : turf.union(turf.featureCollection(boundaries));
      result = turf.intersect(turf.featureCollection([area, union]));
    } else if (kind === 'subtract') {
      result = turf.difference(turf.featureCollection([area, turf.feature(findingGeometry)]));
    } else if (kind === 'fill') {
      result = turf.union(turf.featureCollection([area, turf.feature(findingGeometry)]));
    } else throw new Error('Unknown geometry action.');
    if (!result?.geometry || !['Polygon', 'MultiPolygon'].includes(result.geometry.type)) throw new Error('This change would leave no crop area.');
    return result.geometry;
  }
  root.GeometryPreview = { inspect, propose, removeRedundantVertices };
  if (typeof module !== 'undefined' && module.exports) module.exports = { inspect, propose, removeRedundantVertices };
})(typeof globalThis !== 'undefined' ? globalThis : this);
