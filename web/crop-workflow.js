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

  function create({ map, provider, selected, panel, status, setDrawer, fitParcelPreview, animateDrawerResize }) {
    let drafts = new Map(), crops = [], currentId = null, editing = false, drawing = false;
    let drawPoints = [], markers = [], sequence = 0, drawParcelId = null;
    const toolbar = document.getElementById('crop-draw-toolbar');
    const toolbarText = document.getElementById('crop-draw-text');
    const finish = document.getElementById('crop-draw-finish');
    const cancel = document.getElementById('crop-draw-cancel');
    const palette = ['#4e8c5c', '#c4933a', '#6781ad', '#a9759c'];
    const mapSource = () => map.getSource('crop-areas');
    const selectedDraft = () => drafts.get(currentId);
    const newId = () => `area-local-${Date.now()}-${++sequence}`;
    const label = (text, control) => { const node = el('label', 'crop-label'); node.append(el('span', '', text), control); return node; };
    const button = (text, action, cls = 'crop-action') => { const node = el('button', cls, text); node.type = 'button'; node.addEventListener('click', action); return node; };
    const dateInput = (value, onChange) => { const input = el('input', 'crop-input'); input.type = 'date'; input.value = value || ''; input.addEventListener('input', () => onChange(input.value)); return input; };
    const showError = message => { status.textContent = message; panel.closest('.sheet').scrollTo({ top: 0, behavior: 'smooth' }); };
    function clearMarkers() { markers.forEach(marker => marker.remove()); markers = []; }
    function mapData() {
      const draft = selectedDraft();
      const features = draft ? draft.areas.map((area, index) => ({ type: 'Feature', geometry: area.geometry, properties: { id: area.crop_area_id, color: palette[index % palette.length] } })) : [];
      if (drawPoints.length >= 2) features.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: drawPoints }, properties: { id: 'drawing' } });
      if (mapSource()) mapSource().setData({ type: 'FeatureCollection', features });
    }
    function drawToolbar() {
      toolbar.hidden = !drawing;
      toolbarText.textContent = `Dotknij mapy, aby dodać punkty granicy (${drawPoints.length}). Potrzebne są co najmniej 3.`;
      finish.disabled = drawPoints.length < 3;
    }
    function stopDrawing() { drawing = false; drawPoints = []; drawParcelId = null; clearMarkers(); drawToolbar(); mapData(); }
    function closeEditor() { editing = false; stopDrawing(); clearMarkers(); if (mapSource()) mapSource().setData({ type: 'FeatureCollection', features: [] }); }
    function startDrawing() {
      clearMarkers(); finish.hidden = false; cancel.textContent = 'Anuluj'; drawing = true; drawPoints = []; drawParcelId = currentId; status.textContent = ''; drawToolbar(); mapData(); setDrawer(false);
    }
    function addPoint(lngLat) {
      if (!drawing) return false;
      drawPoints.push([lngLat.lng, lngLat.lat]);
      const dot = el('span', 'crop-draw-dot');
      markers.push(new maplibregl.Marker({ element: dot }).setLngLat([lngLat.lng, lngLat.lat]).addTo(map));
      drawToolbar(); mapData(); return true;
    }
    finish.addEventListener('click', () => {
      const draft = drafts.get(drawParcelId);
      if (!draft || drawPoints.length < 3) return;
      const ring = [...drawPoints.map(point => [...point]), [...drawPoints[0]]];
      draft.areas.push({ crop_area_id: newId(), geometry: { type: 'Polygon', coordinates: [ring] }, crop: { farmer_crop_id: null, map_crop_id: null }, sowing_date: null, past_sprays: [] });
      stopDrawing(); status.textContent = ''; setDrawer(true); render();
    });
    cancel.addEventListener('click', () => { stopDrawing(); finish.hidden = false; cancel.textContent = 'Anuluj'; status.textContent = ''; setDrawer(true); render(); });
    function editGeometry(area) {
      stopDrawing(); clearMarkers();
      const ring = area.geometry.coordinates[0];
      ring.slice(0, -1).forEach((point, index) => {
        const handle = el('button', 'crop-vertex'); handle.type = 'button'; handle.setAttribute('aria-label', `Punkt granicy ${index + 1}`);
        const marker = new maplibregl.Marker({ element: handle, draggable: true }).setLngLat(point).addTo(map);
        marker.on('drag', () => {
          const position = marker.getLngLat(); ring[index] = [position.lng, position.lat];
          if (index === 0) ring[ring.length - 1] = [...ring[0]];
          mapData();
        });
        markers.push(marker);
      });
      status.textContent = '';
      setDrawer(false);
      toolbar.hidden = false; toolbarText.textContent = 'Przeciągnij punkty granicy obszaru uprawy.';
      finish.hidden = true; cancel.textContent = 'Gotowe';
    }
    function renderArea(draft, area, index) {
      const card = el('article', 'crop-card');
      const header = el('div', 'crop-card-heading');
      const areaTitle = el('strong', 'crop-area-title', `Obszar ${index + 1}`);
      const color = el('span', 'crop-area-color'); color.style.backgroundColor = palette[index % palette.length]; color.setAttribute('aria-hidden', 'true'); areaTitle.prepend(color); header.append(areaTitle);
      if (draft.areas.length > 1) header.append(button('Usuń', () => { clearMarkers(); draft.areas.splice(index, 1); render(); }, 'crop-link'));
      card.append(header);
      const select = el('select', 'crop-input');
      const empty = el('option', '', 'Wybierz uprawę'); empty.value = ''; select.appendChild(empty);
      crops.forEach(crop => { const option = el('option', '', crop.label); option.value = crop.id; select.appendChild(option); });
      select.value = area.crop.farmer_crop_id || '';
      select.addEventListener('change', () => { area.crop.farmer_crop_id = select.value || null; });
      if (area.crop.map_crop_id) {
        const suggested = crops.find(crop => crop.id === area.crop.map_crop_id);
        const suggestion = el('div', 'crop-suggestion');
        suggestion.append(el('span', '', `Z mapy: ${suggested ? suggested.label : area.crop.map_crop_id}`));
        suggestion.append(button('Przyjmij', () => { area.crop.farmer_crop_id = area.crop.map_crop_id; select.value = area.crop.map_crop_id; }, 'crop-link'));
        card.append(suggestion);
      }
      card.append(label('Uprawa', select));
      card.append(label('Data siewu', dateInput(area.sowing_date, value => { area.sowing_date = value || null; })));
      card.append(button('Popraw granicę na mapie', () => editGeometry(area), 'crop-outline'));
      const sprays = el('div', 'crop-sprays'); sprays.append(el('strong', '', 'Wykonane opryski'));
      if (!area.past_sprays.length) sprays.append(el('p', 'crop-muted', 'Brak wykonanych oprysków.'));
      area.past_sprays.forEach((spray, sprayIndex) => {
        const group = el('div', 'spray-row');
        const duration = el('input', 'crop-input'); duration.type = 'number'; duration.min = '1'; duration.step = '1'; duration.inputMode = 'numeric'; duration.placeholder = 'np. 14'; duration.value = spray.protection_duration_days || '';
        duration.addEventListener('input', () => { spray.protection_duration_days = duration.value === '' ? null : Number(duration.value); });
        group.append(label('Data oprysku', dateInput(spray.date, value => { spray.date = value || null; })), label('Ochrona (dni)', duration));
        group.append(button('Usuń oprysk', () => { area.past_sprays.splice(sprayIndex, 1); render(); }, 'crop-link'));
        sprays.append(group);
      });
      sprays.append(button('+ Dodaj wykonany oprysk', () => { area.past_sprays.push({ date: null, protection_duration_days: null }); render(); }, 'crop-link'));
      card.append(sprays); return card;
    }
    function render() {
      const previousHeight = panel.closest('.sheet').getBoundingClientRect().height;
      panel.replaceChildren();
      const header = el('div', 'crop-workflow-head');
      header.append(button('‹  Działki', () => { const height = panel.closest('.sheet').getBoundingClientRect().height; closeEditor(); panel.hidden = true; document.getElementById('drawer-content').hidden = false; document.querySelector('.app').classList.remove('cropping'); document.querySelector('.sheet').setAttribute('aria-labelledby', 'heading'); status.textContent = ''; animateDrawerResize(height); }, 'crop-back'));
      const heading = el('h1', '', 'Co rośnie na działkach?'); heading.id = 'crop-heading';
      header.append(el('p', 'eyebrow', 'Twoje uprawy'), heading, el('p', 'crop-intro', 'Sprawdź obszary i uzupełnij dane dla każdej uprawy.'));
      panel.append(header);
      const parcelSelector = el('select', 'crop-input');
      drafts.forEach(draft => { const option = el('option', '', `Działka ${draft.parcel.parcel_number} · ${draft.parcel.locality || 'obręb'}`); option.value = draft.parcel.parcel_id; parcelSelector.appendChild(option); });
      parcelSelector.value = currentId;
      parcelSelector.addEventListener('change', () => { clearMarkers(); stopDrawing(); currentId = parcelSelector.value; render(); fitParcelPreview(selectedDraft().parcel); });
      panel.append(label('Wybrana działka', parcelSelector));
      const draft = selectedDraft();
      if (!draft) return;
      if (draft.suggested && !draft.saved) panel.append(el('p', 'crop-notice', 'Proponowany podział z mapy. Sprawdź granice i potwierdź uprawy.'));
      if (!draft.suggested && !draft.saved) panel.append(el('p', 'crop-notice', 'Brak propozycji z mapy. Wskaż uprawę i dostosuj jej obszar.'));
      draft.areas.forEach((area, index) => panel.append(renderArea(draft, area, index)));
      panel.append(button('+ Narysuj kolejny obszar', startDrawing, 'crop-outline'));
      panel.append(button('Zapisz dane działek', save, 'primary'));
      mapData();
      animateDrawerResize(previousHeight);
    }
    async function open() {
      try {
        status.textContent = 'Pobieramy dane upraw…';
        const [cropResponse, fieldResponse] = await Promise.all([provider.getCrops(), provider.listFields()]);
        const parcels = [...selected.values()];
        const suggestions = await Promise.all(parcels.map(parcel => provider.getCropSuggestions(parcel.parcel_id)));
        crops = cropResponse.crops;
        const nextDrafts = new Map();
        parcels.forEach((parcel, index) => {
          if (drafts.has(parcel.parcel_id)) { nextDrafts.set(parcel.parcel_id, drafts.get(parcel.parcel_id)); return; }
          const saved = fieldResponse.fields.find(field => field.parcel.parcel_id === parcel.parcel_id);
          const suggestedAreas = suggestions[index].areas;
          const areas = saved ? copy(saved.crop_areas) : suggestedAreas.length ? suggestedAreas.map(area => ({ crop_area_id: area.crop_area_id, geometry: area.geometry, crop: { farmer_crop_id: null, map_crop_id: area.map_crop_id }, sowing_date: null, past_sprays: [] })) : [{ crop_area_id: newId(), geometry: copy(parcel.geometry), crop: { farmer_crop_id: null, map_crop_id: null }, sowing_date: null, past_sprays: [] }];
          nextDrafts.set(parcel.parcel_id, { parcel: copy(parcel), fieldId: saved ? saved.field_id : `field-${parcel.parcel_id}`, areas, saved: Boolean(saved), suggested: suggestedAreas.length > 0 });
        });
        drafts = nextDrafts; currentId = drafts.has(currentId) ? currentId : parcels[0].parcel_id;
        editing = true; document.getElementById('drawer-content').hidden = true; panel.hidden = false; document.querySelector('.app').classList.add('cropping'); document.querySelector('.sheet').setAttribute('aria-labelledby', 'crop-heading'); status.textContent = ''; setDrawer(true); render();
        fitParcelPreview(drafts.get(currentId).parcel);
      } catch (_) { showError('Nie można pobrać danych upraw. Spróbuj ponownie.'); }
    }
    async function save() {
      for (const draft of drafts.values()) {
        if (!draft.areas.length || draft.areas.some(area => !area.crop.farmer_crop_id || !area.sowing_date || area.past_sprays.some(spray => !spray.date || !Number.isInteger(spray.protection_duration_days) || spray.protection_duration_days < 1))) {
          currentId = draft.parcel.parcel_id; render(); showError('Uzupełnij uprawę i datę siewu. Każdy oprysk wymaga daty i liczby dni ochrony.'); return;
        }
      }
      let savedCount = 0;
      try {
        for (const draft of drafts.values()) {
          const saved = await provider.saveField(draft.fieldId, { field_id: draft.fieldId, parcel: draft.parcel, crop_areas: copy(draft.areas) });
          draft.areas = copy(saved.crop_areas); draft.saved = true; savedCount++;
        }
        render(); showError(provider.mode === 'mock' ? 'Zapisano dane w podglądzie. Znikną po odświeżeniu strony.' : 'Zapisano dane działek.');
      } catch (_) { showError(savedCount ? `Zapisano ${savedCount} działek. Pozostałych nie udało się zapisać — spróbuj ponownie.` : 'Nie udało się zapisać danych. Sprawdź granice i spróbuj ponownie.'); }
    }
    return { open, isEditing: () => editing, isDrawing: () => drawing, addPoint };
  }
  root.CropWorkflow = { create };
})(globalThis);
