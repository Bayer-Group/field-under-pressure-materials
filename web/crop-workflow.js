/** Farmer crop-area editor. Data and crop suggestions come from the configured provider. */
(function (root) {
  'use strict';

  const copy = value => JSON.parse(JSON.stringify(value));
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function requiredLabel(text) {
    const label = el('span', '', text);
    const star = el('span', 'required-star', ' *');
    star.setAttribute('aria-hidden', 'true');
    label.append(star);
    return label;
  }

  const monthNamesPl = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];
  const monthShortPl = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function formatDisplayDate(isoStr) {
    if (!isoStr || !/^\d{4}-\d{2}-\d{2}$/.test(isoStr)) return 'Select a date';
    const [y, m, d] = isoStr.split('-').map(Number);
    return `${d} ${monthShortPl[m - 1]} ${y}`;
  }

  function create({ map, provider, selected, panel, status, setDrawer, fitParcelPreview, animateDrawerResize, onParcelChange, onSaved }) {
    let draft = null;
    let crops = [];
    let editing = false;
    let drawing = false;
    let partition = null;
    let partitionFrame = null;
    let partitionUndo = null;
    let drawPoints = [];
    let geometryArea = null;
    let explicitGeometryEdit = false;
    let markers = [];
    let sequence = 0;
    let snappingEnabled = true;
    let snapIndicator = null;
    let snapIndicatorTimer = null;
    let areaLabels = new Map();
    let activeAreaId = null;
    let validation = null;
    let validationBusy = false;
    let localPreview = null;
    let previewFingerprint = null;
    let previewTimer = null;
    let findingPopup = null;
    let displayedFindings = [];
    let splitByParcel = false;

    const toolbar = document.getElementById('crop-draw-toolbar');
    const finish = document.getElementById('crop-draw-finish');
    const cancel = document.getElementById('crop-draw-cancel');
    const magnet = document.getElementById('crop-draw-magnet');
    const cropGuide = document.getElementById('crop-guide');
    const editGuide = document.getElementById('crop-edit-guide');
    const vertexNotice = document.getElementById('crop-vertex-notice');

    const palette = ['#36784c', '#c7892b', '#486e99', '#935887', '#d06941'];
    const mapSource = () => map.getSource('crop-areas');
    const newId = () => `area-local-${Date.now()}-${++sequence}`;

    function updateMagnetUI() {
      if (magnet) {
        magnet.classList.toggle('active', snappingEnabled);
        magnet.setAttribute('aria-pressed', String(snappingEnabled));
      }
    }
    if (magnet) {
      magnet.addEventListener('click', () => {
        snappingEnabled = !snappingEnabled;
        updateMagnetUI();
      });
    }

    const showError = message => {
      status.textContent = message;
      panel.closest('.sheet').scrollTo({ top: 0, behavior: 'smooth' });
    };

    function clearMarkers() {
      markers.forEach(marker => marker.remove());
      markers = [];
    }

    function showSnapFeedback(lngLat) {
      if (!snapIndicator) {
        const dot = el('div', 'crop-snap-indicator');
        snapIndicator = new maplibregl.Marker({ element: dot });
      }
      snapIndicator.setLngLat([lngLat.lng, lngLat.lat]).addTo(map);
      clearTimeout(snapIndicatorTimer);
      snapIndicatorTimer = setTimeout(() => {
        if (snapIndicator) snapIndicator.remove();
      }, 500);
    }

    function getSnapTargets(excludeAreaId = null, excludePointIndex = null) {
      const vertices = [];
      const segments = [];

      function addRing(ring) {
        if (!ring || ring.length < 3) return;
        for (let i = 0; i < ring.length - 1; i++) {
          vertices.push(ring[i]);
          segments.push([ring[i], ring[i + 1]]);
        }
      }

      if (draft && draft.parcels) {
        draft.parcels.forEach(p => {
          const geom = p.geometry;
          if (geom.type === 'Polygon') {
            addRing(geom.coordinates[0]);
          } else if (geom.type === 'MultiPolygon') {
            geom.coordinates.forEach(poly => addRing(poly[0]));
          }
        });
      }

      if (draft && draft.areas) {
        draft.areas.forEach(a => {
          if (a.crop_area_id === excludeAreaId) return;
          if (a.geometry && a.geometry.coordinates) {
            addRing(a.geometry.coordinates[0]);
          }
        });
      }

      if (drawPoints.length > 0) {
        drawPoints.forEach((pt, i) => { if (i !== excludePointIndex) vertices.push(pt); });
        for (let i = 0; i < drawPoints.length - 1; i++) {
          if (i !== excludePointIndex && i + 1 !== excludePointIndex) segments.push([drawPoints[i], drawPoints[i + 1]]);
        }
      }

      return { vertices, segments };
    }

    function snap(lngLat, excludeAreaId = null, excludePointIndex = null) {
      if (!snappingEnabled) return { lng: lngLat.lng, lat: lngLat.lat, snapped: false };
      const p = map.project(lngLat);
      const targets = getSnapTargets(excludeAreaId, excludePointIndex);

      let bestVertex = null;
      let bestVertexDist = 24;
      for (const v of targets.vertices) {
        const vp = map.project(v);
        const dist = Math.hypot(p.x - vp.x, p.y - vp.y);
        if (dist < bestVertexDist) {
          bestVertexDist = dist;
          bestVertex = v;
        }
      }
      if (bestVertex) {
        const res = { lng: bestVertex[0], lat: bestVertex[1], snapped: true };
        showSnapFeedback(res);
        return res;
      }

      let bestSegPoint = null;
      let bestSegDist = 18;
      for (const [a, b] of targets.segments) {
        const ap = map.project(a);
        const bp = map.project(b);
        const dx = bp.x - ap.x;
        const dy = bp.y - ap.y;
        const lenSq = dx * dx + dy * dy;
        if (lenSq < 1e-4) continue;
        const t = Math.max(0, Math.min(1, ((p.x - ap.x) * dx + (p.y - ap.y) * dy) / lenSq));
        const projX = ap.x + t * dx;
        const projY = ap.y + t * dy;
        const dist = Math.hypot(p.x - projX, p.y - projY);
        if (dist < bestSegDist) {
          bestSegDist = dist;
          const unp = map.unproject([projX, projY]);
          bestSegPoint = [unp.lng, unp.lat];
        }
      }
      if (bestSegPoint) {
        const res = { lng: bestSegPoint[0], lat: bestSegPoint[1], snapped: true };
        showSnapFeedback(res);
        return res;
      }
      return { lng: lngLat.lng, lat: lngLat.lat, snapped: false };
    }

    /** Find a point inside a polygon using horizontal scanlines, including holes. */
    function labelPoint(geometry) {
      const rings = geometry.coordinates;
      const ys = rings[0].map(point => point[1]);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      let best = null;
      for (let n = 1; n <= 15; n++) {
        const y = minY + (maxY - minY) * n / 16;
        const intersections = [];
        for (const ring of rings) {
          for (let i = 0; i < ring.length - 1; i++) {
            const a = ring[i], b = ring[i + 1];
            if ((a[1] > y) !== (b[1] > y)) intersections.push(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
          }
        }
        intersections.sort((a, b) => a - b);
        for (let i = 0; i + 1 < intersections.length; i += 2) {
          const width = intersections[i + 1] - intersections[i];
          if (!best || width > best.width + 1e-12 || (Math.abs(width - best.width) <= 1e-12 && Math.abs(y - (minY + maxY) / 2) < Math.abs(best.point[1] - (minY + maxY) / 2))) {
            best = { width, point: [(intersections[i] + intersections[i + 1]) / 2, y] };
          }
        }
      }
      return best ? best.point : rings[0][0];
    }

    function geometryRequest() {
      return {
        parcel_ids: draft.parcels.map(parcel => parcel.parcel_id),
        crop_areas: draft.areas.map(area => ({ crop_area_id: area.crop_area_id, geometry: copy(area.geometry) }))
      };
    }

    function geometryFingerprint() { return draft ? JSON.stringify(geometryRequest()) : ''; }

    function showFindings(response) {
      const source = map.getSource('geometry-findings');
      if (!source) return;
      const findings = findingsFrom(response);
      displayedFindings = findings;
      source.setData({ type: 'FeatureCollection', features: findings.map((item, index) => ({ type: 'Feature', geometry: item.geometry, properties: { index } })) });
      if (findings.length && map.getLayer('geometry-findings-fill') && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        map.setPaintProperty('geometry-findings-fill', 'fill-opacity-transition', { duration: 300 });
        map.setPaintProperty('geometry-findings-fill', 'fill-opacity', .7);
        setTimeout(() => { if (map.getLayer('geometry-findings-fill')) map.setPaintProperty('geometry-findings-fill', 'fill-opacity', .45); }, 320);
      }
    }

    /** Measure visible distance of returned outside vertices from selected parcel edges. */
    function outsideDistancePixels(findings) {
      const edges = [];
      draft.parcels.forEach(parcel => {
        const geom = parcel.geometry;
        const polygons = geom.type === 'MultiPolygon' ? geom.coordinates : [geom.coordinates];
        polygons.forEach(polygon => polygon.forEach(ring => {
          for (let i = 0; i < ring.length - 1; i++) edges.push([map.project(ring[i]), map.project(ring[i + 1])]);
        }));
      });
      if (!edges.length) return null;
      let max = 0;
      function distanceToBoundary(p) {
        let nearest = Infinity;
        edges.forEach(([a, b]) => {
          const dx = b.x - a.x, dy = b.y - a.y, length = dx * dx + dy * dy;
          const t = length ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length)) : 0;
          nearest = Math.min(nearest, Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy));
        });
        max = Math.max(max, nearest);
      }
      findings.forEach(item => {
        const geom = item.geometry;
        if (!geom || !['Polygon', 'MultiPolygon'].includes(geom.type)) return;
        const polygons = geom.type === 'MultiPolygon' ? geom.coordinates : [geom.coordinates];
        polygons.forEach(polygon => polygon.forEach(ring => {
          for (let i = 0; i < ring.length - 1; i++) {
            const a = map.project(ring[i]), b = map.project(ring[i + 1]);
            const steps = Math.min(512, Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / 4)));
            for (let n = 0; n <= steps; n++) distanceToBoundary({ x: a.x + (b.x - a.x) * n / steps, y: a.y + (b.y - a.y) * n / steps });
          }
        }));
      });
      return max;
    }

    /** Add a decorative icon while keeping the action's text accessible. */
    function addActionIcon(button, paths) {
      const ns = 'http://www.w3.org/2000/svg';
      const icon = document.createElementNS(ns, 'svg');
      icon.setAttribute('viewBox', '0 0 24 24');
      icon.setAttribute('aria-hidden', 'true');
      paths.forEach(d => { const path = document.createElementNS(ns, 'path'); path.setAttribute('d', d); icon.append(path); });
      button.prepend(icon);
      button.classList.add('geometry-icon-action');
    }

    /** Display one finding at its geometry, using the parcel-details map card. */
    function showFinding(finding, { review = false, preserveDrawer = false, serviceUnavailable = false } = {}) {
      if (!finding || !editing) return;
      const content = el('div', 'geometry-popup-content');
      const labels = {
        overlap: ['Crop areas overlap', 'Adjust the boundaries so each place has only one crop.'],
        gap: ['Area without a crop', 'This part of your land will not be included in the analysis.'],
        outside: ['Outside selected parcels', 'This area extends beyond the parcels you selected.'],
        repair: ['Review boundary change', 'The backend proposes this change to the crop boundary.'],
        invalid: ['Check this boundary', 'The boundary crosses itself or has no valid area. Adjust it before continuing.'],
        error: ['Boundary needs attention', 'The backend could not prepare this area. Please adjust its boundary.'],
        unavailable: ['Unable to save yet', 'The boundary checking service is unavailable. Your changes are still here.']
      };
      const [title, message] = labels[finding.kind];
      content.append(el('h2', '', title), el('p', 'geometry-popup-message', message));
      if (serviceUnavailable && finding.kind !== 'unavailable') content.append(el('p', 'geometry-popup-message', 'The boundary checking service is unavailable. You can still adjust this area.'));
      const actions = el('div', 'geometry-fix-actions');
      let offersMultipart = false;
      const cropName = area => {
        const index = draft.areas.indexOf(area) + 1;
        const crop = crops.find(item => item.id === area.crop?.farmer_crop_id);
        return `Area ${index}${crop ? ` · ${crop.label}` : ''}`;
      };
      const offerFix = (text, area, kind) => {
        let proposed;
        try { proposed = GeometryPreview.propose(kind, area.geometry, finding.geometry, draft.parcels, window.turf); }
        catch (_) { return; }
        if (proposed.type === 'MultiPolygon') offersMultipart = true;
        const button = el('button', 'crop-outline geometry-nearby-candidate', text + (proposed.type === 'MultiPolygon' ? ' (multiple parts)' : ''));
        button.type = 'button';
        if (kind === 'clip') addActionIcon(button, ['M4 4h7v7H4zM13 13h7v7h-7z', 'M8 11v5a3 3 0 0 0 3 3h2M13 5h4a2 2 0 0 1 2 2v4', 'm17 9 2 2 2-2']);
        const fingerprint = geometryFingerprint();
        button.addEventListener('click', () => {
          if (!draft || fingerprint !== geometryFingerprint() || !draft.areas.includes(area)) return;
          area.geometry = copy(proposed);
          activeAreaId = null;
          validation = null; closeFinding(); showFindings(null);
          stopDrawing(); render();
        });
        actions.append(button);
      };
      if (finding.kind === 'outside') {
        const area = draft.areas.find(item => item.crop_area_id === finding.cropAreaId);
        if (area) offerFix('Clip to selected parcels', area, 'clip');
      }
      if (finding.kind === 'gap') draft.areas.forEach(area => offerFix(`Add to ${cropName(area)}`, area, 'fill'));
      if (finding.kind === 'overlap') (finding.cropAreaIds || []).forEach(id => {
        const area = draft.areas.find(item => item.crop_area_id === id);
        if (area) offerFix(`Remove overlap from ${cropName(area)}`, area, 'subtract');
      });
      if (actions.childElementCount) content.append(actions);
      if (offersMultipart) content.append(el('p', 'geometry-popup-message', 'Multiple-part areas can be displayed, but their points cannot yet be edited.'));
      const token = finding.id ? `${finding.kind}:${finding.id}` : null;
      if (review && validation && token && ['gap', 'outside', 'repair'].includes(finding.kind)) {
        const label = el('label', 'geometry-confirm');
        const input = el('input'); input.type = 'checkbox'; input.checked = validation.accepted.has(token);
        input.addEventListener('change', () => input.checked ? validation.accepted.add(token) : validation.accepted.delete(token));
        const copyText = { gap: 'Exclude this area from analysis', outside: 'Clip to my selected parcels', repair: 'Accept this boundary change' };
        label.append(input, el('span', '', copyText[finding.kind])); content.append(label);
        const next = el('button', 'crop-link geometry-popup-action', 'Continue'); next.type = 'button';
        next.addEventListener('click', () => { if (input.checked) save(); else input.focus(); });
        content.append(next);
      }
      if (finding.kind === 'outside' && outsideDistancePixels([finding]) > 24) {
        const nearby = el('div', 'geometry-nearby');
        const button = el('button', 'crop-outline geometry-nearby-candidate geometry-popup-action', 'Find nearby parcels'); button.type = 'button';
        addActionIcon(button, ['M3 3h7v7H3zM3 13h7v7H3zM13 13h7v7h-7z', 'M17 2v8M13 6h8']);
        button.addEventListener('click', async () => {
          button.disabled = true;
          const fingerprint = geometryFingerprint();
          try {
            const point = findingPoint(finding.geometry);
            const { parcels } = await provider.findParcels({ lon: point[0], lat: point[1] });
            if (!draft || !editing || fingerprint !== geometryFingerprint()) return;
            const candidates = parcels.filter(parcel => !selected.has(parcel.parcel_id));
            if (!candidates.length) nearby.append(el('p', 'geometry-popup-message', 'No nearby parcels found here.'));
            candidates.forEach(parcel => {
              const add = el('button', 'crop-outline geometry-nearby-candidate', `Add parcel ${parcel.parcel_number} · ${parcel.locality}`);
              add.type = 'button';
              add.addEventListener('click', () => {
                selected.set(parcel.parcel_id, copy(parcel)); draft.parcels.push(copy(parcel)); onParcelChange?.();
                validation = null; closeFinding(); showFindings(null); render();
              });
              nearby.append(add);
            });
          } catch (_) { nearby.append(el('p', 'geometry-popup-message', 'Could not load nearby parcels. Please try again.')); button.disabled = false; }
        });
        nearby.append(button); content.append(nearby);
      }
      closeFinding();
      findingPopup = new maplibregl.Popup({ className: 'parcel-popup geometry-map-popup', closeButton: true, closeOnClick: false, offset: 8, maxWidth: '310px' })
        .setLngLat(findingPoint(finding.geometry)).setDOMContent(content).addTo(map);
      findingPopup.getElement().querySelector('.maplibregl-popup-close-button')?.setAttribute('aria-label', 'Close boundary message');
      if (review && !preserveDrawer) setDrawer(false);
      const popup = findingPopup;
      requestAnimationFrame(() => {
        if (findingPopup !== popup || !popup.isOpen()) return;
        const rect = popup.getElement().getBoundingClientRect();
        const drawer = panel.closest('.sheet').getBoundingClientRect();
        const mapRect = map.getContainer().getBoundingClientRect();
        const overlapsDrawer = rect.right > drawer.left && rect.left < drawer.right && rect.bottom > drawer.top && rect.top < drawer.bottom;
        let dx = rect.right > mapRect.right - 12 ? rect.right - (mapRect.right - 12) : rect.left < mapRect.left + 12 ? rect.left - (mapRect.left + 12) : 0;
        let dy = rect.top < mapRect.top + 80 ? rect.top - (mapRect.top + 80) : 0;
        if (overlapsDrawer) {
          if (window.matchMedia('(max-width: 719px)').matches) dy = Math.max(dy, rect.bottom - drawer.top + 12);
          else dx = Math.min(dx, rect.left - drawer.right - 12);
        }
        if (dx || dy) map.panBy([dx, dy], { duration: 250 });
      });
    }

    function closeFinding() { if (findingPopup) { findingPopup.remove(); findingPopup = null; } }

    /** Find a point inside the first component of a polygon or multipolygon. */
    function findingPoint(geometry) {
      return labelPoint(geometry.type === 'MultiPolygon' ? { type: 'Polygon', coordinates: geometry.coordinates[0] } : geometry);
    }

    function findingsFrom(response) {
      if (!response || response.error) return [];
      const findings = [];
      (response.overlaps || []).forEach(item => findings.push({ kind: 'overlap', cropAreaIds: item.crop_area_ids, geometry: item.geometry }));
      (response.gaps || []).forEach(item => findings.push({ kind: 'gap', id: item.gap_id, geometry: item.geometry }));
      (response.outside || []).forEach(item => findings.push({ kind: 'outside', id: item.outside_id, cropAreaId: item.crop_area_id, geometry: item.geometry }));
      (response.crop_areas || []).filter(item => item.repair?.requires_review && item.geometry).forEach(item => findings.push({ kind: 'repair', id: item.repair.repair_id, geometry: item.geometry }));
      (response.invalid || []).forEach(id => { const area = draft?.areas.find(item => item.crop_area_id === id); if (area?.geometry) findings.push({ kind: 'invalid', cropAreaId: id, geometry: area.geometry }); });
      (response.errors || []).forEach(item => { const area = draft?.areas.find(value => value.crop_area_id === item.crop_area_id); if (area?.geometry) findings.push({ kind: 'error', cropAreaId: area.crop_area_id, geometry: area.geometry }); });
      return findings.filter(item => item.geometry && ['Polygon', 'MultiPolygon'].includes(item.geometry.type));
    }

    /** Only backend results authorize saving; local results are visual feedback. */
    async function validateForSave() {
      if (validationBusy) return false;
      const request = geometryRequest(), fingerprint = geometryFingerprint();
      validationBusy = true;
      try {
        const response = await provider.validateGeometry(request);
        if (!response || typeof response.validation_id !== 'string' || !response.validation_id ||
            !['crop_areas', 'overlaps', 'gaps', 'outside', 'errors'].every(key => Array.isArray(response[key])) ||
            response.gaps.some(item => !item.gap_id || !item.geometry) ||
            response.outside.some(item => !item.outside_id || !item.geometry) ||
            response.crop_areas.some(item => item.repair?.requires_review && !item.repair.repair_id) ||
            response.crop_areas.length !== request.crop_areas.length ||
            request.crop_areas.some(area => !response.crop_areas.some(item => item.crop_area_id === area.crop_area_id))) throw new Error('Incomplete validation response');
        if (!draft || !editing || fingerprint !== geometryFingerprint()) return false;
        validation = { response, fingerprint, accepted: new Set() };
        showFindings(response);
        return true;
      } catch (error) {
        if (draft && editing && fingerprint === geometryFingerprint()) {
          if (error?.status === 422) {
            const detail = error.detail;
            const invalidParcelId = typeof detail === 'string' && detail.includes('id must be') && request.parcel_ids.some(id => id.includes('/'));
            const message = invalidParcelId ? 'The service cannot currently validate parcel numbers containing a slash. Your selection is still here.' :
              typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message :
              Array.isArray(detail) ? detail.map(item => item.msg).filter(Boolean).join('; ') : '';
            showError(message || 'The service rejected the boundary validation request. Your selection is still here.');
            return false;
          }
          if (!localPreview || previewFingerprint !== fingerprint) {
            try { localPreview = GeometryPreview.inspect(draft.parcels, draft.areas, window.turf); }
            catch (_) { localPreview = { error: true }; }
          }
          showFindings(localPreview.error ? null : localPreview);
          const finding = displayedFindings[0] || (draft.areas[0]?.geometry && { kind: 'unavailable', geometry: draft.areas[0].geometry });
          if (finding) showFinding(finding, { review: true, serviceUnavailable: true });
          else showError('The boundary checking service is unavailable. Your changes are still here.');
        }
        return false;
      } finally { validationBusy = false; }
    }

    /** Inspect current draft locally; backend approval remains required for saving. */
    function runPreview(fingerprint) {
      if (!draft || !editing || fingerprint !== geometryFingerprint()) return;
      try { localPreview = GeometryPreview.inspect(draft.parcels, draft.areas, window.turf); }
      catch (_) { localPreview = { error: true }; status.textContent = 'Live boundary preview is unavailable. Backend validation is still required.'; }
      showFindings(validation ? validation.response : localPreview.error ? null : localPreview);
      if (displayedFindings.length && !drawing && !explicitGeometryEdit) showFinding(displayedFindings[0], { review: Boolean(validation), preserveDrawer: true });
    }

    /** Recalculate only after geometry changes; never use this preview as backend approval. */
    function schedulePreview() {
      if (!draft || !editing) return;
      const fingerprint = geometryFingerprint();
      if (fingerprint === previewFingerprint) return;
      previewFingerprint = fingerprint;
      closeFinding();
      if (!validation) showFindings(null);
      localPreview = null;
      clearTimeout(previewTimer);
      previewTimer = setTimeout(() => runPreview(fingerprint), 220);
    }

    function mapData() {
      if (validation && validation.fingerprint !== geometryFingerprint()) {
        validation = null; showFindings(null);
        closeFinding();
      }
      schedulePreview();
      const features = draft
        ? draft.areas.map((area, index) => ({
            type: 'Feature',
            geometry: area.geometry,
            properties: { id: area.crop_area_id, color: palette[index % palette.length], selected: area.crop_area_id === activeAreaId }
          }))
        : [];
      if (drawPoints.length >= 2) {
        const geometry = drawPoints.length >= 3
          ? { type: 'Polygon', coordinates: [[...drawPoints, drawPoints[0]]] }
          : { type: 'LineString', coordinates: drawPoints };
        features.push({ type: 'Feature', geometry, properties: { id: 'drawing', color: '#176544' } });
      }
      if (mapSource()) mapSource().setData({ type: 'FeatureCollection', features });
      const liveIds = new Set();
      if (editing && draft) draft.areas.forEach((area, index) => {
        const ring = area.geometry?.type === 'Polygon' ? area.geometry.coordinates[0] : area.geometry?.type === 'MultiPolygon' ? area.geometry.coordinates[0]?.[0] : null;
        if (!ring || ring.length < 4) return;
        liveIds.add(area.crop_area_id);
        let label = areaLabels.get(area.crop_area_id);
        if (!label) {
          const button = el('button', 'crop-map-label');
          button.type = 'button';
          button.addEventListener('click', event => {
            event.stopPropagation();
            if (!drawing) focusArea(area.crop_area_id, { openPanel: true });
          });
          label = { button, marker: new maplibregl.Marker({ element: button, anchor: 'center' }), added: false };
          areaLabels.set(area.crop_area_id, label);
        }
        const center = findingPoint(area.geometry);
        label.marker.setLngLat(center);
        if (!label.added) { label.marker.addTo(map); label.added = true; }
        const crop = crops.find(item => item.id === area.crop.farmer_crop_id);
        label.button.replaceChildren(document.createTextNode(String(index + 1)));
        if (crop) label.button.append(el('span', 'crop-map-label-name', crop.label));
        label.button.style.setProperty('--area-color', palette[index % palette.length]);
        label.button.setAttribute('aria-label', `Show area ${index + 1}${crop ? `, ${crop.label}` : ''}`);
        label.button.classList.toggle('active', area.crop_area_id === activeAreaId);
      });
      for (const [id, label] of areaLabels) if (!liveIds.has(id)) { label.marker.remove(); areaLabels.delete(id); }
    }

    function focusArea(id, { openPanel = false, preview = false } = {}) {
      if (!draft) return;
      const area = draft.areas.find(item => item.crop_area_id === id);
      if (!area) return;
      activeAreaId = id;
      if (splitByParcel && area.parcel_id && draft.currentParcel !== area.parcel_id) {
        draft.currentParcel = area.parcel_id;
        render();
      } else {
        panel.querySelectorAll('.crop-card').forEach(card => card.classList.toggle('active', card.dataset.areaId === id));
        mapData();
      }
      if (openPanel) {
        setDrawer(true);
        requestAnimationFrame(() => {
          const card = [...panel.querySelectorAll('.crop-card')].find(item => item.dataset.areaId === id);
          card?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      if (preview) fitParcelPreview({ geometry: area.geometry });
    }

    function drawToolbar() {
      toolbar.hidden = !drawing;
      finish.disabled = drawPoints.length < 3;
      updateMagnetUI();
    }

    function hideGuides() {
      [cropGuide, editGuide].forEach(guide => { guide.classList.remove('visible'); guide.setAttribute('aria-hidden', 'true'); });
    }

    function stopDrawing() {
      if (partitionFrame !== null) { cancelAnimationFrame(partitionFrame); partitionFrame = null; }
      if (partition?.undoButton) partition.undoButton.remove();
      partition = null; partitionPointer = null; map.dragPan.enable();
      map.getSource('partition-preview')?.setData({ type: 'FeatureCollection', features: [] });
      hideGuides();
      geometryArea = null;
      explicitGeometryEdit = false;
      vertexNotice.textContent = '';
      cropGuide.classList.remove('visible');
      cropGuide.setAttribute('aria-hidden', 'true');
      drawing = false;
      drawPoints = [];
      clearMarkers();
      drawToolbar();
      mapData();
    }

    function closeEditor() {
      editing = false;
      clearTimeout(previewTimer); previewFingerprint = null; localPreview = null;
      validation = null; closeFinding(); showFindings(null);
      activeAreaId = null;
      stopDrawing();
      clearMarkers();
      if (mapSource()) mapSource().setData({ type: 'FeatureCollection', features: [] });
    }

    function startDrawing() {
      closeFinding();
      clearMarkers();
      geometryArea = null;
      explicitGeometryEdit = false;
      finish.hidden = false;
      cancel.textContent = 'Cancel';
      drawing = true;
      drawPoints = [];
      status.textContent = '';
      drawToolbar();
      mapData();
      setDrawer(false);
      cropGuide.classList.add('visible');
      cropGuide.setAttribute('aria-hidden', 'false');
    }

    /** Locate the closest polygon edge in screen pixels. */
    function closestEdge(points, lngLat, closed = true) {
      if (points.length < 2) return null;
      const p = map.project(lngLat);
      let best = null;
      const count = closed ? points.length : points.length - 1;
      for (let i = 0; i < count; i++) {
        const a = map.project(points[i]);
        const b = map.project(points[(i + 1) % points.length]);
        const dx = b.x - a.x, dy = b.y - a.y;
        const length = dx * dx + dy * dy;
        const t = length ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length)) : 0;
        const projected = { x: a.x + t * dx, y: a.y + t * dy };
        const distance = Math.hypot(p.x - projected.x, p.y - projected.y);
        if (!best || distance < best.distance) best = { index: i + 1, distance, position: [points[i][0] + t * (points[(i + 1) % points.length][0] - points[i][0]), points[i][1] + t * (points[(i + 1) % points.length][1] - points[i][1])] };
      }
      return best;
    }

    /** Replace a closed exterior ring without changing any interior rings. */
    function updateRing(area, points) {
      area.geometry.coordinates[0] = [...points.map(point => [...point]), [...points[0]]];
    }

    /** Rebuild handles after inserting or removing a vertex. */
    function showVertexHandles(points, area = null) {
      clearMarkers();
      points.forEach((point, index) => {
        const handle = el('button', 'crop-vertex');
        handle.type = 'button';
        handle.setAttribute('aria-label', `Move point ${index + 1}`);
        handle.addEventListener('click', event => event.stopPropagation());
        const marker = new maplibregl.Marker({ element: handle, draggable: true }).setLngLat(point).addTo(map);
        let rawPosition = null;
        let original = [...point];
        marker.on('dragstart', () => { original = [...points[index]]; hideGuides(); vertexNotice.textContent = ''; });
        marker.on('drag', () => {
          rawPosition = marker.getLngLat();
          const position = snap(rawPosition, area ? area.crop_area_id : null, area ? null : index);
          marker.setLngLat([position.lng, position.lat]);
          points[index] = [position.lng, position.lat];
          if (area) updateRing(area, points);
          mapData();
        });
        marker.on('dragend', () => {
          if (!rawPosition) return;
          const raw = map.project(rawPosition);
          const target = points.findIndex((other, i) => i !== index && Math.hypot(map.project(other).x - raw.x, map.project(other).y - raw.y) <= 22);
          if (target !== -1) {
            if (points.length > 3) {
              points.splice(index, 1);
              vertexNotice.textContent = 'Point removed.';
            } else {
              points[index] = original;
              vertexNotice.textContent = 'An area needs at least three points.';
            }
            if (area) updateRing(area, points);
            showVertexHandles(points, area);
            drawToolbar();
            if (area && explicitGeometryEdit) { toolbar.hidden = false; finish.hidden = true; }
            mapData();
          }
        });
        markers.push(marker);
      });
    }

    function addPoint(lngLat) {
      if (partition) return true;
      if (!drawing) return false;
      hideGuides();
      vertexNotice.textContent = '';
      const pt = snap(lngLat);
      const edge = drawPoints.length >= 3 ? closestEdge(drawPoints, lngLat) : null;
      drawPoints.splice(edge ? edge.index : drawPoints.length, 0, [pt.lng, pt.lat]);
      showVertexHandles(drawPoints);
      drawToolbar();
      mapData();
      return true;
    }

    function addEditPoint(lngLat) {
      if (partition || !geometryArea) return false;
      hideGuides();
      const points = geometryArea.geometry.coordinates[0].slice(0, -1).map(point => [...point]);
      const edge = closestEdge(points, lngLat);
      if (!edge || edge.distance > 24) return false;
      points.splice(edge.index, 0, edge.position);
      updateRing(geometryArea, points);
      showVertexHandles(points, geometryArea);
      vertexNotice.textContent = 'Point added. Drag it to adjust the boundary.';
      mapData();
      return true;
    }

    /** Check the drawn exterior ring for obvious zero-area or crossing edges. */
    function hasInvalidDrawnRing(points) {
      let twiceArea = 0;
      const orientation = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
      const onSegment = (a, b, p) => p[0] >= Math.min(a[0], b[0]) && p[0] <= Math.max(a[0], b[0]) && p[1] >= Math.min(a[1], b[1]) && p[1] <= Math.max(a[1], b[1]);
      for (let i = 0; i < points.length; i++) {
        const a = points[i], b = points[(i + 1) % points.length];
        if (a[0] === b[0] && a[1] === b[1]) return true;
        twiceArea += a[0] * b[1] - b[0] * a[1];
        for (let j = i + 1; j < points.length; j++) {
          if (j === i + 1 || (i === 0 && j === points.length - 1)) continue;
          const c = points[j], d = points[(j + 1) % points.length];
          const abC = orientation(a, b, c), abD = orientation(a, b, d);
          const cdA = orientation(c, d, a), cdB = orientation(c, d, b);
          if ((abC * abD < 0 && cdA * cdB < 0) ||
              (abC === 0 && onSegment(a, b, c)) || (abD === 0 && onSegment(a, b, d)) ||
              (cdA === 0 && onSegment(c, d, a)) || (cdB === 0 && onSegment(c, d, b))) return true;
        }
      }
      return Math.abs(twiceArea) < 1e-12;
    }

    finish.addEventListener('click', () => {
      if (partition) { applyPartition(); return; }
      if (!draft || drawPoints.length < 3) return;
      const ring = [...drawPoints.map(point => [...point]), [...drawPoints[0]]];
      const geometry = GeometryPreview.removeRedundantVertices({ type: 'Polygon', coordinates: [ring] });
      if (hasInvalidDrawnRing(geometry.coordinates[0].slice(0, -1))) {
        vertexNotice.textContent = 'The boundary crosses itself or has no area. Move the points to continue.';
        return;
      }
      const id = newId();
      draft.areas.push({
        crop_area_id: id,
        parcel_id: null,
        geometry,
        crop: { farmer_crop_id: 'wheat', map_crop_id: null },
        sowing_date: null,
        past_sprays: [],
        spray_choice: null
      });
      activeAreaId = id;
      stopDrawing();
      status.textContent = '';
      setDrawer(true);
      render();
    });

    cancel.addEventListener('click', () => {
      const wasEditingBoundary = explicitGeometryEdit;
      if (wasEditingBoundary && geometryArea?.geometry) geometryArea.geometry = GeometryPreview.removeRedundantVertices(geometryArea.geometry);
      stopDrawing();
      finish.hidden = false;
      cancel.textContent = 'Cancel';
      status.textContent = '';
      setDrawer(true);
      render();
      if (wasEditingBoundary && draft) {
        clearTimeout(previewTimer);
        previewFingerprint = geometryFingerprint();
        runPreview(previewFingerprint);
      }
      const area = draft?.areas.find(item => item.crop_area_id === activeAreaId);
      if (area) fitParcelPreview({ geometry: area.geometry });
    });

    function editGeometry(area) {
      closeFinding();
      if (area.geometry?.type !== 'Polygon') {
        showError('Editing multipart areas is not available yet.');
        return;
      }
      activeAreaId = area.crop_area_id;
      stopDrawing();
      geometryArea = area;
      explicitGeometryEdit = true;
      const points = area.geometry.coordinates[0].slice(0, -1).map(point => [...point]);
      showVertexHandles(points, area);
      status.textContent = '';
      setDrawer(false);
      toolbar.hidden = false;
      finish.hidden = true;
      cancel.textContent = 'Done';
      updateMagnetUI();
      editGuide.classList.add('visible');
      editGuide.setAttribute('aria-hidden', 'false');
    }

    function createDatePicker({ value, labelText, onChange, initiallyOpen = true }) {
      const wrap = el('div', 'crop-label apple-date-control');
      const titleSpan = requiredLabel(labelText);
      let currentDate = value || '';
      let viewDate = currentDate ? new Date(currentDate) : new Date();
      if (isNaN(viewDate.getTime())) viewDate = new Date();

      const trigger = el('button', 'apple-date-pill');
      trigger.type = 'button';
      trigger.setAttribute('aria-expanded', String(initiallyOpen));

      const left = el('div', 'apple-date-pill-left');
      left.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M16 2v4M8 2v4M3 10h18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
      const dateText = el('span', 'apple-date-value', formatDisplayDate(currentDate));
      left.appendChild(dateText);

      const chevron = el('span', 'apple-date-pill-chevron');
      chevron.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      trigger.append(left, chevron);

      const popover = el('div', 'apple-calendar-popover');
      popover.hidden = !initiallyOpen;
      popover.style.display = initiallyOpen ? 'block' : 'none';

      function renderCalendar() {
        popover.replaceChildren();

        const nav = el('div', 'cal-nav');
        const title = el('span', 'cal-nav-title', `${monthNamesPl[viewDate.getMonth()]} ${viewDate.getFullYear()}`);

        const actions = el('div', 'cal-nav-actions');
        const prevBtn = el('button', 'cal-nav-btn', '‹');
        prevBtn.type = 'button';
        prevBtn.setAttribute('aria-label', 'Previous month');
        prevBtn.addEventListener('click', e => {
          e.stopPropagation();
          viewDate.setMonth(viewDate.getMonth() - 1);
          renderCalendar();
        });

        const nextBtn = el('button', 'cal-nav-btn', '›');
        nextBtn.type = 'button';
        nextBtn.setAttribute('aria-label', 'Next month');
        nextBtn.addEventListener('click', e => {
          e.stopPropagation();
          viewDate.setMonth(viewDate.getMonth() + 1);
          renderCalendar();
        });

        const todayBtn = el('button', 'cal-today-btn', 'Today');
        todayBtn.type = 'button';
        todayBtn.addEventListener('click', e => {
          e.stopPropagation();
          const now = new Date();
          viewDate = new Date(now.getFullYear(), now.getMonth(), 1);
          const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
          setDate(iso);
          setCalendarVisibility(false, false);
          trigger.focus({ preventScroll: true });
        });

        actions.append(prevBtn, nextBtn, todayBtn);
        nav.append(title, actions);
        popover.appendChild(nav);

        const weekdays = el('div', 'cal-weekdays');
        ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(w => weekdays.appendChild(el('span', '', w)));
        popover.appendChild(weekdays);

        const grid = el('div', 'cal-days-grid');
        grid.setAttribute('role', 'grid');

        const year = viewDate.getFullYear();
        const month = viewDate.getMonth();
        const firstDayIndex = (new Date(year, month, 1).getDay() + 6) % 7;
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const daysInPrevMonth = new Date(year, month, 0).getDate();

        for (let i = firstDayIndex - 1; i >= 0; i--) {
          const dayNum = daysInPrevMonth - i;
          const cell = el('button', 'cal-day-cell out-of-month', String(dayNum));
          cell.type = 'button';
          const prevM = month === 0 ? 11 : month - 1;
          const prevY = month === 0 ? year - 1 : year;
          const iso = `${prevY}-${String(prevM + 1).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`;
          cell.addEventListener('click', e => {
            e.stopPropagation();
            viewDate = new Date(prevY, prevM, 1);
            setDate(iso);
            setCalendarVisibility(false, false);
            trigger.focus({ preventScroll: true });
          });
          grid.appendChild(cell);
        }

        const todayStr = new Date().toISOString().slice(0, 10);
        for (let d = 1; d <= daysInMonth; d++) {
          const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
          const cell = el('button', 'cal-day-cell', String(d));
          cell.type = 'button';
          if (iso === currentDate) cell.classList.add('is-selected');
          if (iso === todayStr) cell.classList.add('is-today');
          cell.addEventListener('click', e => {
            e.stopPropagation();
            setDate(iso);
            setCalendarVisibility(false, false);
            trigger.focus({ preventScroll: true });
          });
          grid.appendChild(cell);
        }

        const totalCells = firstDayIndex + daysInMonth;
        const remaining = (7 - (totalCells % 7)) % 7;
        for (let n = 1; n <= remaining; n++) {
          const cell = el('button', 'cal-day-cell out-of-month', String(n));
          cell.type = 'button';
          const nextM = month === 11 ? 0 : month + 1;
          const nextY = month === 11 ? year + 1 : year;
          const iso = `${nextY}-${String(nextM + 1).padStart(2, '0')}-${String(n).padStart(2, '0')}`;
          cell.addEventListener('click', e => {
            e.stopPropagation();
            viewDate = new Date(nextY, nextM, 1);
            setDate(iso);
            setCalendarVisibility(false, false);
            trigger.focus({ preventScroll: true });
          });
          grid.appendChild(cell);
        }
        popover.appendChild(grid);

        const manualRow = el('div', 'cal-manual-box');
        manualRow.append(el('span', '', 'Enter date:'));
        const manualInput = el('input', 'cal-manual-input');
        manualInput.type = 'text';
        manualInput.placeholder = 'YYYY-MM-DD';
        manualInput.value = currentDate;
        manualInput.autocomplete = 'off';
        manualInput.addEventListener('input', () => {
          const val = manualInput.value.trim();
          if (/^\d{4}-\d{2}-\d{2}$/.test(val)) {
            const parsed = new Date(val);
            if (!isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === val) {
              currentDate = val;
              viewDate = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
              dateText.textContent = formatDisplayDate(val);
              onChange(val);
              renderCalendar();
            }
          }
        });
        manualRow.appendChild(manualInput);
        popover.appendChild(manualRow);
      }

      function setDate(iso) {
        currentDate = iso;
        dateText.textContent = formatDisplayDate(iso);
        onChange(iso);
      }

      function centerInDrawer(element) {
        requestAnimationFrame(() => {
          const sheet = panel.closest('.sheet');
          if (!sheet) return;
          const sheetRect = sheet.getBoundingClientRect();
          const elemRect = element.getBoundingClientRect();
          const currentScroll = sheet.scrollTop;
          const offset = (elemRect.top - sheetRect.top) - (sheetRect.height - elemRect.height) / 2;
          sheet.scrollTo({
            top: Math.max(0, currentScroll + offset),
            behavior: 'smooth'
          });
        });
      }

      let calendarAnimation = null;
      let calendarOpen = initiallyOpen;
      function setCalendarVisibility(show, shouldCenter = true) {
        if (calendarAnimation) { calendarAnimation.cancel(); calendarAnimation = null; }
        calendarOpen = show;
        trigger.setAttribute('aria-expanded', String(show));
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (show) {
          popover.hidden = false;
          popover.style.display = 'block';
          popover.style.pointerEvents = '';
          if (currentDate) {
            const parsed = new Date(currentDate);
            if (!isNaN(parsed.getTime())) viewDate = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
          }
          renderCalendar();
          if (!reduceMotion) {
            const height = popover.getBoundingClientRect().height;
            calendarAnimation = popover.animate([
              { height: '0px', opacity: 0, overflow: 'hidden' },
              { height: `${height}px`, opacity: 1, overflow: 'hidden' }
            ], { duration: 200, easing: 'cubic-bezier(.22,1,.36,1)' });
            calendarAnimation.onfinish = () => { calendarAnimation = null; };
          }
          if (shouldCenter) centerInDrawer(popover);
        } else {
          popover.style.pointerEvents = 'none';
          const hide = () => { popover.hidden = true; popover.style.display = 'none'; calendarAnimation = null; };
          if (reduceMotion || popover.hidden) hide();
          else {
            const height = popover.getBoundingClientRect().height;
            calendarAnimation = popover.animate([
              { height: `${height}px`, opacity: 1, overflow: 'hidden' },
              { height: '0px', opacity: 0, overflow: 'hidden' }
            ], { duration: 170, easing: 'cubic-bezier(.4,0,1,1)' });
            calendarAnimation.onfinish = hide;
          }
        }
      }

      trigger.addEventListener('click', e => {
        e.stopPropagation();
        setCalendarVisibility(!calendarOpen, true);
      });

      document.addEventListener('click', e => {
        if (!wrap.contains(e.target) && calendarOpen) {
          setCalendarVisibility(false, false);
        }
      });

      if (initiallyOpen) {
        renderCalendar();
      }

      wrap.append(titleSpan, trigger, popover);
      return wrap;
    }

    /** Recompute all cuts from the original geometry so endpoint edits stay reversible. */
    function updatePartition() {
      if (!partition) return false;
      try {
        let parts = [partition.area.geometry];
        for (const cut of partition.cuts) {
          let split = false;
          const next = [];
          for (const geometry of parts) {
            try { next.push(...GeometryPreview.splitByLine(geometry, cut.points, window.turf)); split = true; }
            catch (_) { next.push(geometry); }
          }
          if (!split) throw new Error('Each cut must cross an area. Move the endpoints or undo the cut.');
          if (draft.areas.length - 1 + next.length > 20) throw new Error('You can have at most 20 areas. Move or undo the last cut.');
          parts = next;
        }
        partition.parts = parts;
        vertexNotice.textContent = partition.cuts.length ? `${parts.length} areas · draw another cut or drag an endpoint.` : 'Drag across the area to draw a cut.';
        finish.disabled = !partition.cuts.length;
        partition.valid = true;
      } catch (error) {
        partition.valid = false;
        vertexNotice.textContent = error.message;
        finish.disabled = true;
      }
      const features = partition.parts.map((geometry, index) => ({ type: 'Feature', geometry, properties: { color: palette[index % palette.length] } }));
      partition.cuts.forEach(cut => features.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: cut.points }, properties: {} }));
      map.getSource('partition-preview')?.setData({ type: 'FeatureCollection', features });
      partition.undoButton.disabled = !partition.cuts.length;
      return partition.valid;
    }

    function queuePartitionUpdate() {
      if (partitionFrame !== null) return;
      partitionFrame = requestAnimationFrame(() => { partitionFrame = null; updatePartition(); });
    }

    function showCutHandles() {
      clearMarkers();
      partition.cuts.forEach((cut, cutIndex) => cut.points.forEach((point, index) => {
        const handle = el('button', 'crop-vertex'); handle.type = 'button';
        handle.setAttribute('aria-label', `Move endpoint ${index + 1} of cut ${cutIndex + 1}`);
        handle.addEventListener('click', event => event.stopPropagation());
        const marker = new maplibregl.Marker({ element: handle, draggable: true }).setLngLat(point).addTo(map);
        marker.on('drag', () => { if (!partition) return; const p = marker.getLngLat(); cut.points[index] = [p.lng, p.lat]; queuePartitionUpdate(); });
        marker.on('dragend', () => updatePartition());
        markers.push(marker);
      }));
    }

    function startPartition(area) {
      if (!window.turf) { showError('Geometry tools are unavailable. Please reload and try again.'); return; }
      if (draft.areas.length >= 20) { showError('You can have at most 20 areas.'); return; }
      closeFinding(); stopDrawing();
      activeAreaId = area.crop_area_id;
      const undoButton = el('button', 'crop-link partition-undo', 'Undo last cut'); undoButton.type = 'button'; undoButton.disabled = true;
      partition = { area, cuts: [], parts: [area.geometry], valid: true, undoButton };
      undoButton.addEventListener('click', () => { partition.cuts.pop(); updatePartition(); showCutHandles(); });
      toolbar.insertBefore(undoButton, toolbar.querySelector('.crop-draw-actions'));
      drawing = true; toolbar.hidden = false; finish.hidden = false; finish.disabled = true;
      finish.textContent = 'Apply cuts'; cancel.textContent = 'Cancel';
      vertexNotice.textContent = 'Drag across the area to draw a cut.';
      mapData(); setDrawer(false); fitParcelPreview({ geometry: area.geometry });
    }

    const partitionCanvas = map.getCanvas();
    let partitionPointer = null;
    partitionCanvas.addEventListener('pointerdown', event => {
      if (!partition || event.button !== 0 || partitionPointer !== null) return;
      event.preventDefault(); event.stopImmediatePropagation();
      partitionPointer = event.pointerId; partitionCanvas.setPointerCapture(event.pointerId); map.dragPan.disable();
      clearMarkers();
      const rect = partitionCanvas.getBoundingClientRect(), p = map.unproject([event.clientX - rect.left, event.clientY - rect.top]);
      partition.cuts.push({ points: [[p.lng, p.lat], [p.lng, p.lat]] }); updatePartition();
    }, true);
    partitionCanvas.addEventListener('pointermove', event => {
      if (partitionPointer !== event.pointerId || !partition) return;
      event.preventDefault(); event.stopImmediatePropagation();
      const rect = partitionCanvas.getBoundingClientRect(), p = map.unproject([event.clientX - rect.left, event.clientY - rect.top]);
      partition.cuts[partition.cuts.length - 1].points[1] = [p.lng, p.lat]; queuePartitionUpdate();
    }, true);
    function endPartitionPointer(event) {
      if (partitionPointer !== event.pointerId) return;
      event.preventDefault(); event.stopImmediatePropagation(); partitionPointer = null; map.dragPan.enable();
      if (!partition) return;
      if (event.type === 'pointercancel') partition.cuts.pop();
      updatePartition(); showCutHandles();
    }
    partitionCanvas.addEventListener('pointerup', endPartitionPointer, true);
    partitionCanvas.addEventListener('pointercancel', endPartitionPointer, true);

    function applyPartition() {
      if (!partition?.valid || !partition.cuts.length || !draft.areas.includes(partition.area)) return;
      const before = copy(draft.areas);
      const original = partition.area, index = draft.areas.indexOf(original);
      const parts = partition.parts.map((geometry, i) => ({ ...copy(original), crop_area_id: i ? newId() : original.crop_area_id, geometry: copy(geometry) }));
      draft.areas.splice(index, 1, ...parts); activeAreaId = parts[0].crop_area_id;
      partitionUndo = { before, after: JSON.stringify(draft.areas) };
      validation = null; stopDrawing(); status.textContent = ''; setDrawer(true); render();
    }

    function revealSection(element) {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      requestAnimationFrame(() => {
        if (!element.isConnected) return;
        const height = element.getBoundingClientRect().height;
        element.animate([
          { height: '0px', opacity: 0, overflow: 'hidden' },
          { height: `${height}px`, opacity: 1, overflow: 'hidden' }
        ], { duration: 220, easing: 'cubic-bezier(.22,1,.36,1)' });
      });
    }

    function renderArea(area, index) {
      const card = el('article', 'crop-card');
      card.dataset.areaId = area.crop_area_id;
      card.classList.toggle('active', area.crop_area_id === activeAreaId);
      const header = el('div', 'crop-card-heading');
      const globalIndex = draft.areas.indexOf(area);
      const identify = el('button', 'crop-area-identify');
      identify.type = 'button';
      identify.setAttribute('aria-label', `Show area ${globalIndex + 1} on the map`);
      const marker = el('span', 'crop-area-number', String(globalIndex + 1));
      marker.style.setProperty('--area-color', palette[globalIndex % palette.length]);
      const title = el('span', 'crop-area-heading');
      const crop = crops.find(item => item.id === area.crop.farmer_crop_id);
      title.append(el('span', 'crop-area-kicker', `AREA ${globalIndex + 1}`), el('strong', '', crop ? crop.label : 'Select a crop'));
      identify.append(marker, title);
      identify.addEventListener('click', () => focusArea(area.crop_area_id, { preview: true }));
      header.append(identify);
      const currentAreas = draft.areas;
      header.append(el('span', 'crop-area-spacer'));
      card.append(header);

      const cut = el('button', 'crop-outline crop-action', 'Cut area'); cut.type = 'button';
      cut.addEventListener('click', () => startPartition(area)); card.append(cut);
      card.append(createDatePicker({
        value: area.sowing_date,
        labelText: 'When was it sown?',
        initiallyOpen: false,
        onChange: value => { area.sowing_date = value; }
      }));
      const sprays = el('section', 'crop-sprays crop-sprays-compact');
      const sprayQuestion = requiredLabel('Was the crop sprayed?');
      sprayQuestion.className = 'spray-question-label';
      sprays.append(sprayQuestion);
      const choices = el('div', 'spray-binary');
      choices.setAttribute('role', 'radiogroup');
      choices.setAttribute('aria-required', 'true');
      choices.setAttribute('aria-label', 'Was the crop sprayed?');
      const switchChoice = (choice, focusAfter = false) => {
        const update = () => {
          area.spray_choice = choice;
          area.past_sprays = choice === 'recorded' ? [{ date: null, protection_duration_days: null }] : [];
          render();
          if (focusAfter) {
            const newCard = [...panel.querySelectorAll('.crop-card')].find(item => item.dataset.areaId === area.crop_area_id);
            newCard?.querySelector('[role=radio][aria-checked=true]')?.focus();
          }
        };
        const details = sprays.querySelector('.spray-details');
        if (!details || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { update(); return; }
        const height = details.getBoundingClientRect().height;
        const animation = details.animate([
          { height: `${height}px`, opacity: 1, overflow: 'hidden' },
          { height: '0px', opacity: 0, overflow: 'hidden' }
        ], { duration: 160, easing: 'cubic-bezier(.4,0,1,1)' });
        animation.onfinish = update;
      };
      [['recorded', 'Yes'], ['none', 'No']].forEach(([choice, label]) => {
        const button = el('button', 'spray-binary-option', label);
        button.type = 'button';
        button.setAttribute('role', 'radio');
        button.setAttribute('aria-checked', String(area.spray_choice === choice));
        button.tabIndex = area.spray_choice ? (area.spray_choice === choice ? 0 : -1) : (choice === 'recorded' ? 0 : -1);
        button.addEventListener('keydown', event => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
          event.preventDefault();
          const other = choice === 'recorded' ? 'none' : 'recorded';
          if (area.spray_choice !== other) switchChoice(other, true);
        });
        button.addEventListener('click', () => { if (area.spray_choice !== choice) switchChoice(choice); });
        choices.append(button);
      });
      sprays.append(choices);
      if (area.spray_choice === 'recorded') {
        const details = el('div', 'spray-details');
        area.past_sprays.forEach((spray, sprayIndex) => {
          const group = el('div', 'spray-compact-row');
          if (area.past_sprays.length > 1) group.append(el('strong', 'spray-number', `Spray ${sprayIndex + 1}`));
          const durationWrap = el('label', 'crop-label spray-duration');
          durationWrap.hidden = !spray.date;
          const duration = el('input', 'crop-input');
          duration.type = 'number'; duration.required = true; duration.min = '1'; duration.step = '1'; duration.inputMode = 'numeric';
          if (provider.mode === 'backend') duration.max = '60';
          duration.placeholder = 'Number of days';
          duration.value = spray.protection_duration_days ?? '';
          duration.addEventListener('input', () => { spray.protection_duration_days = duration.value === '' ? null : Number(duration.value); });
          durationWrap.append(requiredLabel('How long does the treatment protect the crop? (days)'), duration);
          const date = createDatePicker({ value: spray.date, labelText: 'When was it sprayed?', initiallyOpen: false, onChange: value => {
            spray.date = value;
            if (durationWrap.hidden) {
              const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180;
              setTimeout(() => { if (durationWrap.isConnected && durationWrap.hidden) { durationWrap.hidden = false; revealSection(durationWrap); } }, delay);
            }
          }});
          group.append(date, durationWrap);
          if (area.past_sprays.length > 1) {
            const remove = el('button', 'crop-link spray-remove', 'Remove spray');
            remove.type = 'button';
            remove.addEventListener('click', () => { area.past_sprays.splice(sprayIndex, 1); render(); });
            group.append(remove);
          }
          details.append(group);
        });
        const add = el('button', 'crop-link spray-add', '+ Add another spray');
        add.type = 'button';
        add.addEventListener('click', () => { area.past_sprays.push({ date: null, protection_duration_days: null }); render(); });
        details.append(add);
        sprays.append(details);
        revealSection(details);
      }
      card.append(sprays);
      if (currentAreas.length > 1) {
        const footer = el('div', 'crop-card-footer');
        const remove = el('button', 'crop-remove-icon');
        remove.type = 'button';
        remove.setAttribute('aria-label', `Remove area ${globalIndex + 1}`);
        remove.title = 'Remove area';
        remove.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v5m4-5v5"/></svg>';
        remove.addEventListener('click', () => {
          clearMarkers();
          if (activeAreaId === area.crop_area_id) { activeAreaId = null; geometryArea = null; }
          draft.areas.splice(draft.areas.indexOf(area), 1);
          render();
        });
        footer.append(remove);
        card.append(footer);
      }
      return card;
    }

    function renderCombinedSummary() {
      const summary = el('div', 'crop-selection-summary');
      const count = draft.parcels.length;
      const parcelWord = count === 1 ? 'parcel' : 'parcels';
      const line = `${count} ${parcelWord}`;
      summary.append(el('strong', '', line));
      const list = el('div', 'crop-selection-parcels');
      draft.parcels.forEach(parcel => list.append(el('span', '', [parcel.parcel_number, parcel.locality].filter(Boolean).join(' · '))));
      summary.append(list);
      return summary;
    }

    function render() {
      const previousHeight = panel.closest('.sheet').getBoundingClientRect().height;
      status.textContent = '';
      panel.replaceChildren();

      const header = el('div', 'crop-workflow-head');
      const backBtn = el('button', 'crop-back crop-back-icon');
      backBtn.type = 'button';
      backBtn.setAttribute('aria-label', 'Back to parcel selection');
      backBtn.title = 'Back to parcel selection';
      backBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5m6-6-6 6 6 6"/></svg>';
      backBtn.addEventListener('click', () => {
        const height = panel.closest('.sheet').getBoundingClientRect().height;
        closeEditor();
        panel.hidden = true;
        document.getElementById('drawer-content').hidden = false;
        document.querySelector('.app').classList.remove('cropping');
        document.querySelector('.sheet').setAttribute('aria-labelledby', 'heading');
        status.textContent = '';
        animateDrawerResize(height);
      });

      const heading = el('h1', '', 'What grows on your land?');
      heading.id = 'crop-heading';
      header.append(backBtn, heading);
      panel.append(header);

      if (!draft) return;
      const selectionBox = el('section', 'crop-selection-box');
      selectionBox.setAttribute('aria-label', 'Selected parcels');
      selectionBox.append(renderCombinedSummary());

      if (draft.parcels.length > 1) {
        const picker = el('div', 'crop-parcel-picker');
        const toggle = el('button', 'crop-split-toggle');
        toggle.type = 'button';
        toggle.setAttribute('aria-pressed', String(splitByParcel));
        toggle.append(el('span', '', 'Show parcels separately'), el('span', 'crop-switch'));
        toggle.addEventListener('click', () => { splitByParcel = !splitByParcel; render(); });
        picker.append(toggle);
        if (splitByParcel) {
          const tabs = el('div', 'crop-parcel-tabs');
          draft.parcels.forEach(parcel => {
            const button = el('button', 'crop-parcel-tab', `Parcel ${parcel.parcel_number} · ${parcel.locality}`);
            button.type = 'button';
            button.setAttribute('aria-pressed', String(parcel.parcel_id === draft.currentParcel));
            button.addEventListener('click', () => { draft.currentParcel = parcel.parcel_id; render(); fitParcelPreview(parcel); });
            tabs.append(button);
          });
          picker.append(tabs);
        }
        selectionBox.append(picker);
      }
      panel.append(selectionBox);
      const visibleAreas = splitByParcel ? draft.areas.filter(area => !area.parcel_id || area.parcel_id === draft.currentParcel) : draft.areas;
      visibleAreas.forEach((area, index) => panel.append(renderArea(area, index)));

      if (partitionUndo) {
        const undo = el('button', 'crop-link', 'Undo last split'); undo.type = 'button';
        undo.addEventListener('click', () => {
          if (JSON.stringify(draft.areas) !== partitionUndo.after) { showError('The area details changed after the split. Undo is no longer available.'); return; }
          draft.areas = partitionUndo.before; partitionUndo = null; activeAreaId = null;
          validation = null; closeFinding(); render();
        });
        panel.append(undo);
      }
      if (draft.saved && provider.mode === 'backend') {
        const resultsButton = el('button', 'crop-outline', 'View saved analysis'); resultsButton.type = 'button';
        resultsButton.addEventListener('click', async () => {
          resultsButton.disabled = true;
          try { if (!await onSaved()) showError('Your details were saved, but the analysis could not be loaded. Try again.'); }
          finally { resultsButton.disabled = false; }
        });
        panel.append(resultsButton);
      }
      const saveBtn = el('button', 'primary', provider.mode === 'backend' ? 'Save and view analysis' : 'Save crop details');
      saveBtn.type = 'button';
      saveBtn.addEventListener('click', async () => {
        if (saveBtn.disabled) return;
        saveBtn.disabled = true;
        try { await save(); } finally { saveBtn.disabled = false; }
      });
      panel.append(saveBtn);

      mapData();
      animateDrawerResize(previousHeight);
    }

    async function open() {
      try {
        status.textContent = 'Loading crop details…';
        const parcels = [...selected.values()];
        if (!parcels.length) {
          showError('Select at least one parcel first.');
          return;
        }

        const [cropResponse, fieldResponse, groupResponse] = await Promise.all([
          provider.getCrops(),
          provider.listFields(),
          provider.listCropGroups ? provider.listCropGroups() : Promise.resolve({ groups: [] })
        ]);
        crops = cropResponse.crops.filter(crop => crop.id === 'wheat');
        if (!crops.length) throw new Error('WHEAT_UNAVAILABLE');

        const suggestions = parcels.map(() => ({ areas: [] }));

        const areas = [];
        const fieldIds = {};
        let isSuggested = false;
        parcels.forEach((parcel, index) => {
          const saved = fieldResponse.fields.find(field => field.parcel?.parcel_id === parcel.parcel_id);
          if (saved && Array.isArray(saved.crop_areas) && saved.crop_areas.length) {
            fieldIds[parcel.parcel_id] = saved.field_id;
            copy(saved.crop_areas).forEach(area => {
              area.parcel_id = parcel.parcel_id;
              area.spray_choice = Array.isArray(area.past_sprays) ? (area.past_sprays.length ? 'recorded' : 'none') : null;
              if (!Array.isArray(area.past_sprays)) area.past_sprays = [];
              areas.push(area);
            });
          } else {
            const suggestedAreas = suggestions[index]?.areas || [];
            if (suggestedAreas.length) {
              isSuggested = true;
              suggestedAreas.forEach(suggestion => areas.push({
                crop_area_id: suggestion.crop_area_id,
                parcel_id: parcel.parcel_id,
                geometry: copy(suggestion.geometry),
                crop: { farmer_crop_id: 'wheat', map_crop_id: suggestion.map_crop_id || null },
                sowing_date: null, past_sprays: [], spray_choice: null
              }));
            } else {
              areas.push({
                crop_area_id: newId(), parcel_id: parcel.parcel_id,
                geometry: copy(parcel.geometry),
                crop: { farmer_crop_id: 'wheat', map_crop_id: null },
                sowing_date: null, past_sprays: [], spray_choice: null
              });
            }
          }
        });
        const chosenIds = parcels.map(parcel => parcel.parcel_id).sort().join('|');
        const savedGroup = (groupResponse.groups || []).find(group => Array.isArray(group.parcel_ids) && [...group.parcel_ids].sort().join('|') === chosenIds);
        const conflictingGroup = !savedGroup && (groupResponse.groups || []).some(group => Array.isArray(group.parcel_ids) && group.parcel_ids.some(id => parcels.some(parcel => parcel.parcel_id === id)));
        if (conflictingGroup) throw new Error('GROUP_SELECTION_MISMATCH');
        if (savedGroup && Array.isArray(savedGroup.crop_areas)) {
          areas.length = 0;
          copy(savedGroup.crop_areas).forEach(area => {
            area.parcel_id = null;
            area.spray_choice = Array.isArray(area.past_sprays) ? (area.past_sprays.length ? 'recorded' : 'none') : null;
            if (!Array.isArray(area.past_sprays)) area.past_sprays = [];
            areas.push(area);
          });
        }
        if (!savedGroup && !isSuggested && !Object.keys(fieldIds).length && areas.length > 1 && window.turf) {
          const union = window.turf.union(window.turf.featureCollection(areas.map(area => window.turf.feature(area.geometry))));
          if (!union?.geometry) throw new Error('Could not combine the selected parcels.');
          areas.splice(0, areas.length, { ...areas[0], parcel_id: null, geometry: union.geometry });
        }
        if (areas.some(area => area.crop?.farmer_crop_id && area.crop.farmer_crop_id !== 'wheat')) throw new Error('NON_WHEAT_AREA');
        areas.forEach(area => { area.crop = { ...area.crop, farmer_crop_id: 'wheat' }; });
        partitionUndo = null;
        draft = { parcels: copy(parcels), areas, fieldIds, fieldId: savedGroup?.field_id || null, currentParcel: parcels[0].parcel_id, saved: Boolean(savedGroup), suggested: isSuggested };
        splitByParcel = false;
        activeAreaId = null;

        editing = true;
        document.getElementById('drawer-content').hidden = true;
        panel.hidden = false;
        document.querySelector('.app').classList.add('cropping');
        document.querySelector('.sheet').setAttribute('aria-labelledby', 'crop-heading');
        status.textContent = '';
        setDrawer(true);
        render();

        const compositeBounds = {
          geometry: {
            type: 'MultiPolygon',
            coordinates: parcels.map(p =>
              p.geometry.type === 'MultiPolygon' ? p.geometry.coordinates[0] : p.geometry.coordinates
            )
          }
        };
        fitParcelPreview(compositeBounds);
      } catch (error) {
        showError(error?.message === 'GROUP_SELECTION_MISMATCH' ? 'Some parcels belong to a saved group. Select the entire group to preserve its crop data.' : error?.message === 'NON_WHEAT_AREA' ? 'This saved selection contains a crop other than wheat and cannot be edited here.' : error?.message === 'WHEAT_UNAVAILABLE' ? 'Wheat is unavailable in the crop catalog. Please try again later.' : 'Could not load crop details. Please try again.');
      }
    }

    async function save() {
      if (!draft || !draft.areas.length) {
        showError('Add at least one crop area.');
        return;
      }
      for (let i = 0; i < draft.areas.length; i++) {
        const area = draft.areas[i];
        const parcel = draft.parcels.find(item => item.parcel_id === area.parcel_id);
        const parcelAreas = draft.areas.filter(item => item.parcel_id === area.parcel_id);
        const areaLabel = parcel ? `Parcel ${parcel.parcel_number}, area ${parcelAreas.indexOf(area) + 1}: ` : `Area ${i + 1}: `;
        const invalid = message => {
          if (area.parcel_id) draft.currentParcel = area.parcel_id;
          activeAreaId = area.crop_area_id;
          render();
          showError(areaLabel + message);
          const card = [...panel.querySelectorAll('.crop-card')].find(item => item.dataset.areaId === area.crop_area_id);
          if (card) {
            const error = el('p', 'crop-inline-error', message);
            error.setAttribute('role', 'alert');
            card.prepend(error);
            card.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        };
        if (area.crop.farmer_crop_id !== 'wheat') {
          invalid('Only wheat areas are supported.');
          return;
        }
        if (!area.sowing_date) {
          invalid('Enter the sowing date.');
          return;
        }
        if (!area.spray_choice) {
          invalid('Choose whether the crop was sprayed.');
          return;
        }
        if (area.spray_choice === 'recorded') {
          if (!area.past_sprays.length) {
            invalid('Add a spray or confirm there were none.');
            return;
          }
          for (let s = 0; s < area.past_sprays.length; s++) {
            const spray = area.past_sprays[s];
            if (!spray.date) {
              invalid(`Spray ${s + 1}: select a date.`);
              return;
            }
            if (!Number.isInteger(spray.protection_duration_days) || spray.protection_duration_days < 1) {
              invalid(`Spray ${s + 1}: enter the number of days of protection (at least 1).`);
              return;
            }
            if (provider.mode === 'backend' && spray.protection_duration_days > 60) {
              invalid(`Spray ${s + 1}: the current service supports at most 60 days of protection.`);
              return;
            }
          }
        }
      }

      if (!validation || validation.fingerprint !== geometryFingerprint()) {
        if (!await validateForSave()) return;
      }
      const result = validation.response;
      if ((result.errors || []).length || (result.overlaps || []).length) {
        const issue = displayedFindings.find(item => item.kind === 'overlap' || item.kind === 'error');
        if (issue) showFinding(issue, { review: true }); else showError('Fix the geometry problems before saving.');
        return;
      }
      const required = [
        ...(result.gaps || []).map(item => `gap:${item.gap_id}`),
        ...(result.outside || []).map(item => `outside:${item.outside_id}`),
        ...(result.crop_areas || []).filter(item => item.repair?.requires_review).map(item => `repair:${item.repair.repair_id}`)
      ];
      if (required.some(id => !validation.accepted.has(id))) {
        const issue = displayedFindings.find(item => item.id && !validation.accepted.has(`${item.kind}:${item.id}`));
        if (issue) showFinding(issue, { review: true }); else showError('Confirm the boundary changes before saving.');
        return;
      }
      try {
        if (typeof provider.saveCropGroup !== 'function') throw new Error('Group save is not available');
        if (!draft.fieldId) draft.fieldId = `field-${crypto.randomUUID()}`;
        await provider.saveCropGroup({
          ...geometryRequest(), field_id: draft.fieldId, validation_id: result.validation_id,
          confirmations: [...validation.accepted],
          crop_areas: draft.areas.map(({ parcel_id, spray_choice, ...area }) => copy(area))
        });
        draft.saved = true; partitionUndo = null; closeFinding();
      } catch (error) {
        const detail = error?.detail;
        const message = typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : '';
        showError(message || 'Could not save the data. Your drawing is still here.'); return;
      }
      if (provider.mode === 'backend' && onSaved) {
        try { if (await onSaved()) return; } catch (_) { /* The save has already succeeded. */ }
        render(); showError('Your details were saved, but the analysis could not be loaded. Try again.');
      } else { render(); showError('Crop details saved.'); }

    }

    return {
      open,
      close: closeEditor,
      isEditing: () => editing,
      isDrawing: () => drawing,
      addPoint,
      addImportedAreas(areas) {
        if (!draft || !Array.isArray(areas)) return;
        areas.forEach(item => {
          if (!item.geometry || !['Polygon', 'MultiPolygon'].includes(item.geometry.type)) return;
          draft.areas.push({
            crop_area_id: newId(), parcel_id: null, geometry: copy(item.geometry),
            crop: { farmer_crop_id: 'wheat', map_crop_id: item.map_crop_id || null },
            sowing_date: null, past_sprays: [], spray_choice: null
          });
        });
        render(); setDrawer(true);
      },
      addEditPoint,
      dismissGuide() {
        if (!cropGuide.classList.contains('visible') && !editGuide.classList.contains('visible')) return false;
        hideGuides();
        return true;
      },
      deselectArea() {
        if (!editing || drawing || !activeAreaId) return false;
        activeAreaId = null;
        stopDrawing();
        closeFinding();
        panel.querySelectorAll('.crop-card').forEach(card => card.classList.remove('active'));
        mapData();
        return true;
      },
      showFindingAt(point) {
        if (!editing || drawing || !map.getLayer('geometry-findings-fill')) return false;
        const feature = map.queryRenderedFeatures(point, { layers: ['geometry-findings-fill'] })[0];
        const finding = feature && displayedFindings[Number(feature.properties.index)];
        if (!finding) return false;
        showFinding(finding, { review: Boolean(validation), preserveDrawer: true });
        return true;
      },
      selectAt(point) {
        if (!editing || drawing || !map.getLayer('crop-fill')) return;
        const feature = map.queryRenderedFeatures(point, { layers: ['crop-fill'] })[0];
        if (!feature?.properties?.id || feature.properties.id === 'drawing') return false;
        focusArea(feature.properties.id, { openPanel: true });
        return true;
      }
    };
  }

  root.CropWorkflow = { create };
})(globalThis);
