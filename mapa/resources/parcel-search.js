(function () {
  var ULDK_URL = 'https://uldk.gugik.gov.pl/';
  var NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search';

  var oldGeocoder = document.querySelector('.photon-geocoder-autocomplete');
  if (oldGeocoder) { oldGeocoder.parentNode.removeChild(oldGeocoder); }

  function parcelStyle(feature) {
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: '#e60000', width: 3 }),
      fill: new ol.style.Fill({ color: 'rgba(230, 0, 0, 0.15)' }),
      text: new ol.style.Text({
        text: feature.get('numer') || '',
        font: 'bold 16px Arial, sans-serif',
        fill: new ol.style.Fill({ color: '#ffffff' }),
        stroke: new ol.style.Stroke({ color: '#b00000', width: 4 }),
        overflow: true
      })
    });
  }
  var markerStyle = new ol.style.Style({
    image: new ol.style.Icon({
      anchor: [0.5, 1], scale: 0.7, src: './resources/marker.png'
    })
  });

  var resultLayer = new ol.layer.Vector({
    source: new ol.source.Vector(),
    zIndex: 1000,
    style: function (f) {
      return f.getGeometry().getType() === 'Point' ? markerStyle : parcelStyle(f);
    }
  });
  map.addLayer(resultLayer);

  var zamykacz = document.getElementById('popup-closer');
  if (zamykacz) {
    zamykacz.addEventListener('click', function () { resultLayer.getSource().clear(); });
  }

  function query(base, params) {
    return base + '?' + Object.keys(params).map(function (k) {
      return k + '=' + encodeURIComponent(params[k]);
    }).join('&');
  }

  var ULDK_FIELDS = 'geom_wkt,teryt,voivodeship,county,commune,region,parcel';

  function uldkParcels(params) {
    params.result = ULDK_FIELDS;
    params.srid = '4326';
    return fetch(query(ULDK_URL, params)).then(function (r) { return r.text(); }).then(function (text) {
      if (/^\s*</.test(text)) { return []; }
      var lines = text.trim().split(/\r?\n/);
      if (lines.shift().indexOf('-1') === 0) { return []; }
      return lines.filter(function (l) { return l.trim(); }).map(function (l) {
        var c = l.split('|');
        return {
          type: 'parcel',
          wkt: c[0].replace(/^SRID=\d+;/, ''),
          teryt: c[1], woj: c[2], powiat: c[3], gmina: c[4], obreb: c[5], numer: c[6],
          title: 'Działka ' + c[6] + ', obręb ' + c[5],
          details: 'gm. ' + c[4] + ', ' + c[3] + ', woj. ' + c[2] + ' — ' + c[1]
        };
      });
    }).catch(function () { return []; });
  }

  function searchParcels(q) {
    return uldkParcels({ request: 'GetParcelByIdOrNr', id: q });
  }

  function parcelAt(lon, lat) {
    return uldkParcels({ request: 'GetParcelByXY', xy: lon + ',' + lat + ',4326' });
  }

  function searchAddresses(q) {
    return fetch(query(NOMINATIM_URL, {
      format: 'jsonv2', q: q, countrycodes: 'pl', limit: '8', 'accept-language': 'pl'
    })).then(function (r) { return r.json(); }).then(function (list) {
      return list.map(function (a) {
        var parts = a.display_name.split(', ');
        return {
          type: 'address',
          lon: parseFloat(a.lon), lat: parseFloat(a.lat),
          title: parts.slice(0, 2).join(', '),
          details: parts.slice(2).join(', '),
          label: a.display_name
        };
      });
    }).catch(function () { return []; });
  }

  var wrapper = document.createElement('div');
  wrapper.className = 'unified-search ol-unselectable ol-control';

  var toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'unified-search-btn fa fa-search';
  toggle.title = 'Search';

  var panel = document.createElement('div');
  panel.className = 'unified-search-panel';
  panel.style.display = 'none';

  var form = document.createElement('form');
  var input = document.createElement('input');
  input.type = 'search';
  input.className = 'unified-search-input';
  input.placeholder = 'Search';
  form.appendChild(input);

  var results = document.createElement('ul');
  results.className = 'unified-search-results';

  panel.appendChild(form);
  panel.appendChild(results);
  wrapper.appendChild(toggle);
  wrapper.appendChild(panel);

  toggle.addEventListener('click', function () {
    var open = panel.style.display === 'none';
    panel.style.display = open ? 'block' : 'none';
    if (open) { input.focus(); }
  });

  function addItem(text, cls) {
    var li = document.createElement('li');
    li.className = cls;
    li.textContent = text;
    results.appendChild(li);
    return li;
  }

  function drawParcel(item) {
    var f = new ol.format.WKT().readFeature(item.wkt, {
      dataProjection: 'EPSG:4326', featureProjection: map.getView().getProjection()
    });
    f.set('numer', item.numer);
    resultLayer.getSource().clear();
    resultLayer.getSource().addFeature(f);
    return f;
  }

  function esc(t) {
    var d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  function formatArea(m2) {
    var ha = m2 / 10000;
    return Math.round(m2).toLocaleString('en-US') + ' m² (' +
      ha.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 }) + ' ha)';
  }

  var popupParts = { parcel: '', extra: '' }, popupCoord = null;

  function renderPopup() {
    if (typeof content === 'undefined' || typeof overlayPopup === 'undefined' || !popupCoord) { return; }
    content.innerHTML = popupParts.parcel + popupParts.extra;
    container.style.display = 'block';
    overlayPopup.setPosition(undefined);
    overlayPopup.setPosition(popupCoord);
  }

  function showPopup(html, coord) {
    popupParts.parcel = html;
    if (coord) { popupCoord = coord; }
    renderPopup();
  }

  window.mapPopup = {
    setExtra: function (html) { popupParts.extra = html || ''; renderPopup(); }
  };

  function hidePopup() {
    if (typeof container !== 'undefined') { container.style.display = 'none'; }
  }

  function showParcelInfo(item, feature, coord) {
    var area = ol.sphere.getArea(feature.getGeometry(), {
      projection: map.getView().getProjection()
    });
    var rows = [
      ['Parcel number', item.numer],
      ['Identifier', item.teryt],
      ['Cadastral district', item.obreb],
      ['Municipality', item.gmina],
      ['County', item.powiat],
      ['Voivodeship', item.woj],
      ['Area*', formatArea(area)]
    ];
    var html = '<div class="parcel-info"><b>Parcel ' + esc(item.numer) + '</b><table>' +
      rows.map(function (r) {
        return '<tr><th>' + esc(r[0]) + '</th><td>' + esc(r[1]) + '</td></tr>';
      }).join('') +
      '</table><small>* calculated from geometry, may differ from the registered area</small>' +
      '<a href="https://mapy.geoportal.gov.pl/imap/Imgp_2.html?identifyParcel=' +
      encodeURIComponent(item.teryt) + '" target="_blank" rel="noopener">Show in Geoportal</a></div>';
    showPopup(html, coord);
  }

  var clickId = 0;
  window.mapParcels = { parcelAt: parcelAt };

  map.on('singleclick', function (evt) {
    if (typeof measuring !== 'undefined' && measuring) { return; }
    if (window.analizaCDI && window.analizaCDI.zaznaczanie) { return; }
    var id = ++clickId;
    var coord = evt.coordinate;
    var ll = ol.proj.toLonLat(coord, map.getView().getProjection());
    popupParts.extra = '';
    showPopup('<div class="parcel-info">Looking for a parcel…</div>', coord);
    parcelAt(ll[0].toFixed(7), ll[1].toFixed(7)).then(function (list) {
      if (id !== clickId) { return; }
      if (!list.length) {
        showPopup('<div class="parcel-info">No parcel at this location.</div>', coord);
        return;
      }
      var f = drawParcel(list[0]);
      showParcelInfo(list[0], f, coord);
    });
  });

  function select(item) {
    var src = resultLayer.getSource();
    var proj = map.getView().getProjection();
    src.clear();
    results.innerHTML = '';
    if (item.type === 'parcel') {
      var f = drawParcel(item);
      map.getView().fit(f.getGeometry().getExtent(), {
        padding: [60, 60, 60, 60], maxZoom: 19, duration: 500
      });
      hidePopup();
      input.value = item.title + ' (' + item.teryt + ')';
    } else {
      hidePopup();
      var p = ol.proj.fromLonLat([item.lon, item.lat], proj);
      src.addFeature(new ol.Feature(new ol.geom.Point(p)));
      map.getView().animate({ center: p, zoom: 18, duration: 500 });
      input.value = item.label;
    }
  }

  function render(parcels, addresses) {
    results.innerHTML = '';
    if (!parcels.length && !addresses.length) {
      addItem('Brak wyników.', 'unified-search-msg');
      return;
    }
    [['Działki', parcels], ['Adresy', addresses]].forEach(function (group) {
      if (!group[1].length) { return; }
      addItem(group[0], 'unified-search-header');
      group[1].forEach(function (item) {
        var li = document.createElement('li');
        var strong = document.createElement('strong');
        strong.textContent = item.title;
        var small = document.createElement('small');
        small.textContent = item.details;
        li.appendChild(strong);
        li.appendChild(small);
        li.addEventListener('click', function () { select(item); });
        results.appendChild(li);
      });
    });
  }

  var searchId = 0;
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) { return; }
    var id = ++searchId;
    results.innerHTML = '';
    addItem('Szukam…', 'unified-search-msg');
    Promise.all([searchParcels(q), searchAddresses(q)]).then(function (res) {
      if (id !== searchId) { return; }
      var parcels = res[0], addresses = res[1];
      if (parcels.length === 1 && /^\d{6}_\d/.test(q)) { select(parcels[0]); return; }
      render(parcels, addresses);
    });
  });

  map.addControl(new ol.control.Control({ element: wrapper }));
  if (typeof topLeftContainerDiv !== 'undefined' && topLeftContainerDiv) {
    topLeftContainerDiv.appendChild(wrapper);
  }
})();
