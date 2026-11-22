

(function () {
  'use strict';
  if (typeof map === 'undefined' || !window.ol) return;

  var OD_ROKU = 1991, SMA_DNI = 10, DNI_GLEBY = 3;
  var NDDI_DNI = 60, NDDI_OD_ROKU = 2018, NDDI_CZYSTE = 0.8, NDDI_MAKS_SCEN = 6, NDVI_MIN = 0.3;
  var PC = 'https://planetarycomputer.microsoft.com/api';
  var OPEN_METEO = 'https://archive-api.open-meteo.com/v1/archive';

  var PROGI_KBW = {
    "Zboża ozime": {"I":[-129,-132,-137,-145,-154,-165,-180,-199,-220,null,null,null,null,null],"II":[-150,-153,-158,-166,-175,-186,-201,-220,-241,null,null,null,null,null],"III":[-188,-191,-196,-204,-213,-224,-239,-258,-279,null,null,null,null,null],"IV":[-215,-218,-223,-231,-240,-251,-266,-285,-306,null,null,null,null,null]},
    "Zboża jare": {"I":[-125,-127,-130,-135,-142,-153,-169,-186,-207,null,null,null,null,null],"II":[-144,-146,-149,-154,-161,-172,-188,-205,-226,null,null,null,null,null],"III":[-174,-176,-179,-184,-191,-202,-218,-235,-256,null,null,null,null,null],"IV":[-194,-196,-199,-204,-211,-222,-238,-255,-276,null,null,null,null,null]},
    "Kukurydza na ziarno": {"I":[null,null,null,-168,-161,-156,-153,-152,-153,-154,-156,-158,-161,-164],"II":[null,null,null,-200,-193,-188,-185,-184,-185,-186,-188,-190,-193,-196],"III":[null,null,null,-236,-229,-224,-221,-220,-221,-222,-224,-226,-229,-232],"IV":[null,null,null,-271,-264,-259,-256,-255,-256,-257,-259,-261,-264,-267]},
    "Kukurydza na kiszonkę": {"I":[null,null,null,-168,-161,-156,-153,-152,-152,-152,-153,-155,-157,-160],"II":[null,null,null,-200,-193,-188,-185,-184,-184,-184,-185,-187,-189,-192],"III":[null,null,null,-236,-229,-224,-221,-220,-220,-220,-221,-223,-225,-228],"IV":[null,null,null,-271,-264,-259,-256,-255,-255,-255,-256,-258,-260,-263]},
    "Rzepak i rzepik": {"I":[-207,-187,-170,-155,-142,-132,null,null,null,null,null,null,-138,-138],"II":[-232,-211,-193,-177,-165,-155,null,null,null,null,null,null,-158,-158],"III":[-275,-254,-236,-220,-208,-198,null,null,null,null,null,null,-205,-205],"IV":[-297,-276,-258,-242,-230,-220,null,null,null,null,null,null,-230,-230]},
    "Ziemniaki": {"I":[null,null,-238,-232,-226,-219,-210,-200,-189,-178,-168,-157,-147,null],"II":[null,null,-257,-251,-245,-238,-229,-219,-208,-197,-187,-176,-166,null],"III":[null,null,-286,-280,-274,-267,-258,-248,-237,-226,-216,-205,-195,null],"IV":[null,null,-306,-300,-294,-287,-278,-268,-257,-246,-236,-225,-215,null]},
    "Burak cukrowy": {"I":[null,null,null,null,null,null,null,null,null,null,null,null,null,null],"II":[-250,-248,-245,-241,-237,-232,-226,-220,-212,-202,-192,-182,-169,-155],"III":[-277,-275,-272,-268,-264,-259,-253,-247,-239,-229,-219,-209,-196,-182],"IV":[-296,-294,-291,-287,-283,-278,-272,-266,-258,-248,-238,-228,-215,-201]},
    "Chmiel": {"I":[null,null,null,-230,-220,-212,-205,-199,-194,-190,-186,-182,null,null],"II":[null,null,null,-248,-238,-230,-223,-217,-212,-208,-204,-200,null,null],"III":[null,null,null,-285,-275,-267,-260,-254,-249,-245,-241,-237,null,null],"IV":[null,null,null,-302,-292,-284,-277,-271,-266,-262,-258,-254,null,null]},
    "Tytoń": {"I":[null,null,null,-189,-187,-186,-185,-186,-187,-190,-195,-200,null,null],"II":[null,null,null,-201,-199,-198,-197,-198,-199,-202,-207,-212,null,null],"III":[null,null,null,-227,-225,-224,-223,-224,-225,-228,-233,-238,null,null],"IV":[null,null,null,-240,-238,-237,-236,-237,-238,-241,-246,-251,null,null]},
    "Warzywa gruntowe": {"I":[null,null,null,-189,-187,-185,-184,-184,-184,-185,-187,-188,null,null],"II":[null,null,null,-207,-205,-203,-202,-202,-202,-203,-205,-206,null,null],"III":[null,null,null,-243,-241,-239,-238,-238,-238,-239,-241,-242,null,null],"IV":[null,null,null,-263,-261,-259,-258,-258,-258,-259,-261,-262,null,null]},
    "Krzewy owocowe": {"I":[-149,-148,-147,-147,-149,-154,-159,-162,-163,-162,-160,-157,null,null],"II":[-166,-165,-164,-164,-166,-171,-176,-179,-180,-179,-177,-174,null,null],"III":[-200,-199,-198,-198,-200,-205,-210,-213,-214,-213,-211,-208,null,null],"IV":[-217,-216,-215,-215,-217,-222,-227,-230,-231,-230,-228,-225,null,null]},
    "Drzewa owocowe": {"I":[-168,-171,-175,-180,-187,-193,-199,-205,-210,-215,-220,-223,null,null],"II":[-190,-193,-197,-202,-209,-215,-221,-227,-232,-237,-242,-245,null,null],"III":[-229,-232,-236,-241,-248,-254,-260,-266,-271,-276,-281,-284,null,null],"IV":[-249,-252,-256,-261,-268,-274,-280,-286,-291,-296,-301,-304,null,null]},
    "Truskawki": {"I":[-133,-137,-143,-152,-163,-178,-190,-198,-202,null,null,null,null,null],"II":[-150,-154,-160,-169,-180,-195,-207,-215,-219,null,null,null,null,null],"III":[-183,-187,-193,-202,-213,-228,-240,-248,-252,null,null,null,null,null],"IV":[-204,-208,-214,-223,-234,-249,-261,-269,-273,null,null,null,null,null]},
    "Rośliny strączkowe": {"I":[null,null,null,-161,-161,-163,-165,-166,-167,-168,-170,-172,-174,-176],"II":[null,null,null,-182,-182,-184,-186,-187,-188,-189,-191,-193,-195,-197],"III":[null,null,null,-213,-213,-215,-217,-218,-219,-220,-222,-224,-226,-228],"IV":[null,null,null,-234,-234,-236,-238,-239,-240,-241,-243,-245,-247,-249]}
  };
  var OKRESY = [['03-21', '05-20'], ['04-01', '05-31'], ['04-11', '06-10'], ['04-21', '06-20'], ['05-01', '06-30'],
    ['05-11', '07-10'], ['05-21', '07-20'], ['06-01', '07-31'], ['06-11', '08-10'], ['06-21', '08-20'],
    ['07-01', '08-31'], ['07-11', '09-10'], ['07-21', '09-20'], ['08-01', '09-30']];
  var KATEGORIA_GATUNKU = {
    'pl': 'I', 'plp': 'I', 'ps': 'I', 'psp': 'I',
    'pgl': 'II', 'pglp': 'II', 'pgm': 'II', 'pgmp': 'II',
    'gl': 'III', 'glp': 'III', 'płg': 'III', 'płz': 'III', 'płp': 'III',
    'gs': 'IV', 'gsp': 'IV', 'gc': 'IV', 'gcp': 'IV', 'płi': 'IV', 'i': 'IV', 'ip': 'IV'
  };
  var UPRAWA_KBW = { pszenica_jara: 'Zboża jare', pszenica_ozima: 'Zboża ozime', ziemniak: 'Ziemniaki',
    kukurydza: 'Kukurydza na ziarno' };
  var UPRAWY_DOMYSLNE = [{ id: 'pszenica_jara', nazwa: 'Spring wheat' }, { id: 'pszenica_ozima', nazwa: 'Winter wheat' },
    { id: 'ziemniak', nazwa: 'Potato' }, { id: 'kukurydza', nazwa: 'Corn' }];
  var POZIOMY_CDI = [
    { nazwa: 'No drought', kolor: '#2e7d32' }, { nazwa: 'Watch', kolor: '#f9a825' },
    { nazwa: 'Warning', kolor: '#ef6c00' }, { nazwa: 'Alert', kolor: '#c62828' }
  ];
  var KOLORY_KLAS = ['#1a9641', '#ffd92f', '#f46d43', '#b2182b'];
  var RZYM = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];

  var stan = { zaznaczanie: false, dzialki: [] };
  window.analizaCDI = stan;

  var css = document.createElement('style');
  css.textContent =
    '.cdi-przyciski{display:flex;gap:6px;margin:2px 0 6px}' +
    '.cdi-przyciski button,.cdi-oblicz{font:600 12px system-ui,sans-serif;padding:4px 8px;border-radius:4px;cursor:pointer;' +
    'border:1px solid #2e5e2a;background:#fff;color:#2e5e2a}' +
    '.cdi-przyciski button.aktywny,.cdi-oblicz{background:#2e5e2a;color:#fff}' +
    '.cdi-oblicz{width:100%;margin-top:6px;padding:6px}.cdi-oblicz:disabled{opacity:.45;cursor:default}' +
    '.cdi-pomoc{font-size:11px;color:#666;margin-bottom:4px}' +
    '.cdi-ustawienia{display:grid;grid-template-columns:auto 1fr;gap:3px 6px;align-items:center;font-size:12px;margin:4px 0 6px}' +
    '.cdi-ustawienia select,.cdi-ustawienia input{font-size:12px;min-width:0;width:100%;box-sizing:border-box}' +
    '.cdi-lista{list-style:none;margin:0;padding:0;font-size:12px}' +
    '.cdi-lista li{display:flex;align-items:center;gap:5px;padding:3px 0;border-bottom:1px solid #eee}' +
    '.cdi-lista .cdi-nazwa{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '.cdi-lista select{font-size:11px;padding:0}' +
    '.cdi-lista .cdi-status{font-size:11px;color:#888;white-space:nowrap}' +
    '.cdi-lista button{border:0;background:none;color:#999;cursor:pointer;font-size:15px;padding:0 2px;line-height:1}' +
    '.cdi-wynik{margin-top:8px;font-size:12px}' +
    '.cdi-poziom{color:#fff;border-radius:4px;padding:6px 8px;font-weight:700;font-size:14px;margin-bottom:6px}' +
    '.cdi-poziom.jasny{color:#222}' +
    '.cdi-poziom small{display:block;font-weight:400;font-size:11px;opacity:.9}' +
    '.cdi-linia{margin:3px 0;font-size:12px}.cdi-linia b.tak{color:#c62828}.cdi-linia b.nie{color:#2e7d32}' +
    '.cdi-tab{width:100%;border-collapse:collapse;font-size:11.5px;margin-bottom:4px}' +
    '.cdi-tab td,.cdi-tab th{padding:2px 3px;border-bottom:1px solid #f0f0f0;text-align:right;min-width:0;white-space:nowrap}' +
    '.cdi-tab td:first-child,.cdi-tab th:first-child{text-align:left}' +
    '.cdi-tab th{color:#666;font-weight:500}.cdi-tab tr.obszar td{font-weight:600;border-top:1px solid #ccc}' +
    '.cdi-kropka{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:3px;vertical-align:middle}' +
    '.cdi-klasa{display:inline-block;border-radius:3px;padding:0 5px;font-size:11px;color:#fff}' +
    '.cdi-uwaga{font-size:11px;color:#666;margin-top:6px}' +
    '.cdi-sekcja{margin:8px 0 2px;font-weight:600;color:#2e5e2a;border-bottom:1px solid #e3e3e3;font-size:12.5px}' +
    '.cdi-sekcja small{font-weight:400;color:#777}' +
    '.cdi-ocena{display:inline-block;min-width:30px;text-align:center;border-radius:3px;padding:0 4px;color:#fff;font-weight:600}' +
    '.cdi-ocena.jasna{color:#222}' +
    '.cdi-skala{position:relative;height:12px;border-radius:3px;margin:2px 0 1px}' +
    '.cdi-skala i{position:absolute;top:-4px;width:4px;height:20px;background:#222;border:1px solid #fff;border-radius:2px;transform:translateX(-50%)}' +
    '.cdi-skala-opis{display:flex;justify-content:space-between;font-size:11px;color:#555;margin-bottom:6px}' +
    '.cdi-os{margin-top:10px;border-top:1px solid #ddd;padding-top:6px;font-size:12px}' +
    '.cdi-os select{font-size:12px;width:100%;margin:3px 0}' +
    '.cdi-os canvas{width:100%;height:120px;display:block;background:#fafafa;border:1px solid #e3e3e3;border-radius:3px}' +
    '.cdi-os input[type=range]{width:100%;margin:4px 0 2px}' +
    '.cdi-os-odczyt{font-size:11.5px;margin-top:2px}.cdi-os-odczyt b{font-size:12.5px}' +
    '.cdi-os-przycisk{width:100%;margin-top:4px;font:600 12px system-ui,sans-serif;padding:4px;border-radius:4px;cursor:pointer;' +
    'border:1px solid #2e5e2a;background:#fff;color:#2e5e2a}.cdi-os-przycisk:disabled{opacity:.5;cursor:default}' +
    '.cdi-zaznaczanie .ol-viewport{cursor:copy}';
  document.head.appendChild(css);

  var SKALA = [[26, 150, 65], [166, 217, 106], [255, 217, 47], [253, 174, 97], [215, 25, 28]];
  function kolorSkali(t, alfa) {
    t = Math.min(Math.max(isFinite(t) ? t : 0, 0), 1) * (SKALA.length - 1);
    var i = Math.min(Math.floor(t), SKALA.length - 2), f = t - i;
    var c = [0, 1, 2].map(function (k) { return Math.round(SKALA[i][k] + f * (SKALA[i + 1][k] - SKALA[i][k])); });
    return alfa === undefined ? 'rgb(' + c.join(',') + ')' : 'rgba(' + c.join(',') + ',' + alfa + ')';
  }
  var GRADIENT = 'linear-gradient(to right,' + SKALA.map(function (c) { return 'rgb(' + c.join(',') + ')'; }).join(',') + ')';
  function ocena(tekst, t) {
    if (!isFinite(t)) return tekst;
    return '<span class="cdi-ocena' + (t > 0.3 && t < 0.7 ? ' jasna' : '') + '" style="background:' + kolorSkali(t) + '">' + tekst + '</span>';
  }
  function pasekSkali(t, lewy, prawy) {
    return '<div class="cdi-skala" style="background:' + GRADIENT + '">' + (isFinite(t) ? '<i style="left:' + (100 * t).toFixed(1) + '%"></i>' : '') +
      '</div><div class="cdi-skala-opis"><span>' + lewy + '</span><span>' + prawy + '</span></div>';
  }
  function ocenaDzialki(d) {
    var am = analizaMeta(), p = d && d.wynik && d.wynik.punkty;
    return am && p && p.wynik !== null ? p.wynik / am.maks_punktow : NaN;
  }

  function stylDzialki(f) {
    var d = f.get('dzialka'), czas = d && isFinite(d.wynikCzasu);
    var t = czas ? d.wynikCzasu / analizaMeta().maks_punktow : ocenaDzialki(d), jest = isFinite(t);
    var kolor = jest ? kolorSkali(t) : '#1565c0', mozaika = !czas && !!(d && d.warstwaPikseli);
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: mozaika ? 'rgba(0,0,0,0.75)' : kolor, width: mozaika ? 2 : 3 }),
      fill: new ol.style.Fill({ color: mozaika ? 'rgba(0,0,0,0)' : jest ? kolorSkali(t, 0.55) : 'rgba(21,101,192,0.2)' }),
      text: new ol.style.Text({
        text: d ? d.numer + (jest ? '\n' + (czas ? Math.round(d.wynikCzasu) : d.wynik.punkty.wynik) + ' pts' : '') : '',
        font: 'bold 14px Arial, sans-serif', overflow: true,
        fill: new ol.style.Fill({ color: '#fff' }), stroke: new ol.style.Stroke({ color: 'rgba(0,0,0,0.7)', width: 4 })
      })
    });
  }
  var zrodlo = new ol.source.Vector();
  map.addLayer(new ol.layer.Vector({ source: zrodlo, zIndex: 999, style: stylDzialki }));
  var grupaPikseli = new ol.layer.Group({ zIndex: 998 });
  map.addLayer(grupaPikseli);
  function usunMozaike(d) {
    if (d.warstwaPikseli) { grupaPikseli.getLayers().remove(d.warstwaPikseli); d.warstwaPikseli = null; }
  }

  var tresc = document.querySelector('.panel-analiza-koncowa');
  var szczegoly = document.querySelector('.panel-szczegoly');
  if (!tresc || !szczegoly) return;
  var PUSTE_SZCZEGOLY = szczegoly.innerHTML;
  var dzis = new Date().toISOString().slice(0, 10);
  tresc.innerHTML =
    '<div class="cdi-przyciski"><button type="button" class="cdi-zaznacz">Select parcels</button>' +
    '<button type="button" class="cdi-wyczysc">Clear</button></div>' +
    '<div class="cdi-pomoc">Turn on “Select parcels”, then click parcels on the map (click again to remove).</div>' +
    '<div class="cdi-ustawienia"><label>Crop</label><select class="cdi-uprawa"></select>' +
    '<label>Date</label><input type="date" class="cdi-data" max="' + dzis + '" min="' + (NDDI_OD_ROKU + 1) + '-01-01" value="' + dzis + '"></div>' +
    '<ul class="cdi-lista"></ul>' +
    '<button type="button" class="cdi-oblicz" disabled>Calculate</button>' +
    '<div class="cdi-wynik"></div><div class="cdi-os"></div>';
  var $ = function (s) { return tresc.querySelector(s); };
  var przyciskZaznacz = $('.cdi-zaznacz'), lista = $('.cdi-lista'), przyciskOblicz = $('.cdi-oblicz'), wynik = $('.cdi-wynik');
  var poleUprawa = $('.cdi-uprawa'), poleData = $('.cdi-data');
  var liczenie = false;

  function analizaMeta() { var m = window.rolnikMeta && window.rolnikMeta(); return m && m.zrodla && m.zrodla.analiza; }
  function uprawy() { var am = analizaMeta(); return (am && am.uprawy) || UPRAWY_DOMYSLNE; }
  function wypelnijUprawy() {
    var wybrana = poleUprawa.value || 'pszenica_jara';
    poleUprawa.innerHTML = uprawy().map(function (u) {
      return '<option value="' + u.id + '"' + (u.id === wybrana ? ' selected' : '') + '>' + esc(u.nazwa) + '</option>';
    }).join('');
  }
  wypelnijUprawy();
  (function czekajNaMete(n) {
    if (analizaMeta()) { wypelnijUprawy(); return; }
    if (n < 100) setTimeout(function () { czekajNaMete(n + 1); }, 200);
  })(0);

  przyciskZaznacz.onclick = function () {
    stan.zaznaczanie = !stan.zaznaczanie;
    przyciskZaznacz.classList.toggle('aktywny', stan.zaznaczanie);
    przyciskZaznacz.textContent = stan.zaznaczanie ? 'Selecting… (click to stop)' : 'Select parcels';
    document.documentElement.classList.toggle('cdi-zaznaczanie', stan.zaznaczanie);
    if (stan.zaznaczanie && window.container) container.style.display = 'none';
  };
  $('.cdi-wyczysc').onclick = function () { stan.dzialki = []; zrodlo.clear(); wyczyscWyniki(); };
  przyciskOblicz.onclick = function () { oblicz(); };
  poleUprawa.onchange = poleData.onchange = function () { wyczyscWyniki(); };

  function f1(v) { return isFinite(v) ? v.toFixed(1) : '–'; }
  function f2(v) { return isFinite(v) ? v.toFixed(2) : '–'; }
  function f0(v) { return isFinite(v) ? String(Math.round(v)) : '–'; }
  function esc(t) { var d = document.createElement('div'); d.textContent = t == null ? '' : String(t); return d.innerHTML; }
  function srednia(a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : NaN; }
  function etykietaOkresu(o) {
    var a = o[0].split('-'), b = o[1].split('-');
    return (+a[1]) + ' ' + RZYM[+a[0]] + '–' + (+b[1]) + ' ' + RZYM[+b[0]];
  }
  function wyczyscWyniki() {
    grupaPikseli.getLayers().clear();
    grupaPikseli.setVisible(true);
    stan.dzialki.forEach(function (d) { d.wynik = null; d.warstwaPikseli = null; d.wynikCzasu = NaN; d.feature.changed(); });
    wynik.innerHTML = '';
    var os = tresc.querySelector('.cdi-os');
    if (os) os.innerHTML = '';
    seria = null;
    szczegoly.innerHTML = PUSTE_SZCZEGOLY;
    odswiezListe();
  }

  function odswiezListe() {
    lista.innerHTML = '';
    stan.dzialki.forEach(function (d) {
      var li = document.createElement('li'), p = d.wynik && d.wynik.punkty;
      var status = d.blad ? 'error' : (p && p.klasa ? 'class ' + RZYM[p.klasa] : 'selected');
      li.innerHTML = '<span class="cdi-nazwa" title="' + esc(d.teryt + (d.gleba ? ' · ' + d.gleba : '')) + '">' +
        esc(d.numer) + ' · ' + esc(d.obreb) + ' <small>(' + d.ha.toFixed(2) + ' ha)</small></span>' +
        '<select title="Soil category (Dz.U. 2019 poz. 739)">' + ['I', 'II', 'III', 'IV'].map(function (k) {
          return '<option' + (k === d.kategoria ? ' selected' : '') + '>' + k + '</option>';
        }).join('') + '</select><span class="cdi-status">' + status + '</span><button type="button" title="Remove">×</button>';
      li.querySelector('select').onchange = function () { d.kategoria = this.value; wyczyscWyniki(); };
      li.querySelector('button').onclick = function () { usun(d); };
      lista.appendChild(li);
    });
    var n = stan.dzialki.length;
    przyciskOblicz.disabled = liczenie || !n;
    if (!liczenie) przyciskOblicz.textContent = !n ? 'Calculate' : 'Calculate (' + n + (n === 1 ? ' parcel)' : ' parcels)');
  }

  function usun(d) {
    stan.dzialki = stan.dzialki.filter(function (x) { return x !== d; });
    zrodlo.removeFeature(d.feature);
    usunMozaike(d);
    wyczyscWyniki();
  }

  map.on('singleclick', function (evt) {
    if (!stan.zaznaczanie || liczenie) return;
    var trafiona = null;
    map.forEachFeatureAtPixel(evt.pixel, function (f) { if (f.get('dzialka')) { trafiona = f.get('dzialka'); return true; } },
      { layerFilter: function (l) { return l.getSource() === zrodlo; } });
    if (trafiona) { usun(trafiona); return; }
    var ll = ol.proj.toLonLat(evt.coordinate, map.getView().getProjection());
    if (!window.mapParcels) return;
    window.mapParcels.parcelAt(ll[0].toFixed(7), ll[1].toFixed(7)).then(function (wyn) {
      if (!wyn.length) return;
      var p = wyn[0];
      if (stan.dzialki.some(function (d) { return d.teryt === p.teryt; })) return;
      dodaj(p);
    });
  });

  function punktWewnatrz(geom) {
    var g = geom.getType() === 'MultiPolygon' ? geom.getPolygon(0) : geom;
    return g.getInteriorPoint ? g.getInteriorPoint().getCoordinates() : ol.extent.getCenter(geom.getExtent());
  }

  function dodaj(p) {
    var proj = map.getView().getProjection();
    var feature = new ol.format.WKT().readFeature(p.wkt, { dataProjection: 'EPSG:4326', featureProjection: proj });
    var wgs = new ol.format.WKT().readFeature(p.wkt);
    var srodek = punktWewnatrz(wgs.getGeometry());
    var geo = new ol.format.GeoJSON().writeFeatureObject(wgs);
    geo.properties = {};
    var d = {
      teryt: p.teryt, numer: p.numer, obreb: p.obreb, gmina: p.gmina, feature: feature, geojson: geo,
      lon: srodek[0], lat: srodek[1], kategoria: 'II', gleba: null, nddiCache: {},
      ha: ol.sphere.getArea(feature.getGeometry(), { projection: proj }) / 1e4
    };
    feature.set('dzialka', d);
    zrodlo.addFeature(feature);
    stan.dzialki.push(d);
    wyczyscWyniki();
    if (window.rolnikWartosc) {
      window.rolnikWartosc('gleba_klasa', d.lon, d.lat).then(function (v) {
        if (v && v.tekst) { d.gleba = v.tekst; d.kategoria = kategoriaGleby(v.tekst) || d.kategoria; odswiezListe(); }
      });
    }
  }

  function kategoriaGleby(tekst) {
    var m = /\(([^)]+)\)\s*$/.exec(tekst || '');
    return m ? KATEGORIA_GATUNKU[m[1].trim().toLowerCase()] : null;
  }

  var klimatCache = {};
  function daneKlimatu(lon, lat) {
    var klucz = lon.toFixed(1) + ',' + lat.toFixed(1);
    if (klimatCache[klucz]) return klimatCache[klucz];
    var url = OPEN_METEO + '?latitude=' + lat.toFixed(3) + '&longitude=' + lon.toFixed(3) +
      '&start_date=' + OD_ROKU + '-01-01&end_date=' + dzis +
      '&daily=precipitation_sum,et0_fao_evapotranspiration,soil_moisture_0_to_100cm_mean,soil_moisture_0_to_7cm_mean,' +
      'soil_temperature_0_to_7cm_mean&timezone=Europe%2FWarsaw';
    klimatCache[klucz] = fetch(url).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error('Open-Meteo ' + r.status + ' ' + t.slice(0, 80)); });
      return r.json();
    }).then(function (d) {
      var dl = d.daily, k = { t: dl.time, p: dl.precipitation_sum, et: dl.et0_fao_evapotranspiration,
        sm: dl.soil_moisture_0_to_100cm_mean, sm7: dl.soil_moisture_0_to_7cm_mean, st7: dl.soil_temperature_0_to_7cm_mean, idx: {} };
      k.t.forEach(function (x, i) { k.idx[x] = i; });
      var o = k.t.length - 1;
      while (o > 0 && (k.p[o] === null || k.sm[o] === null || k.et[o] === null)) o--;
      k.ostatni = k.t[o];
      return k;
    });
    klimatCache[klucz].catch(function () { delete klimatCache[klucz]; });
    return klimatCache[klucz];
  }

  function wskaznikiKlimatu(k, data, uprawaKbw, kategoria) {
    var koniec = data > k.ostatni ? k.ostatni : data, i1 = k.idx[koniec], rokK = +koniec.slice(0, 4);
    function okno(tab, j1, n, suma) {
      if (j1 - n + 1 < 0) return null;
      var s = 0;
      for (var j = j1 - n + 1; j <= j1; j++) { if (tab[j] === null) return null; s += tab[j]; }
      return suma ? s : s / n;
    }
    function zLat(tab, n, suma) {
      var w = [];
      for (var r = OD_ROKU; r < rokK; r++) {
        var j = k.idx[r + koniec.slice(4)];
        if (j === undefined) j = k.idx[r + '-02-28'];
        if (j === undefined) continue;
        var v = okno(tab, j, n, suma);
        if (v !== null) w.push(v);
      }
      return w;
    }
    function spi(n) {
      var x = okno(k.p, i1, n, true), h = zLat(k.p, n, true);
      return { wartosc: spiZGammy(x, h), suma: x, norma: srednia(h) };
    }
    var smX = okno(k.sm, i1, SMA_DNI, false), smH = zLat(k.sm, SMA_DNI, false), smS = srednia(smH);
    var smSd = Math.sqrt(smH.reduce(function (a, b) { return a + (b - smS) * (b - smS); }, 0) / (smH.length - 1));

    var kbw = null;
    for (var o = OKRESY.length - 1; o >= 0; o--) {
      var od = rokK + '-' + OKRESY[o][0], doD = rokK + '-' + OKRESY[o][1];
      if (doD <= koniec) {
        var j0 = k.idx[od], j2 = k.idx[doD], sp = 0, se = 0, ok = true;
        for (var j = j0; j <= j2; j++) { if (k.p[j] === null || k.et[j] === null) { ok = false; break; } sp += k.p[j]; se += k.et[j]; }
        var prog = (PROGI_KBW[uprawaKbw] && PROGI_KBW[uprawaKbw][kategoria]) ? PROGI_KBW[uprawaKbw][kategoria][o] : null;
        kbw = { okres: o, opad: ok ? sp : NaN, et0: ok ? se : NaN, wartosc: ok ? sp - se : NaN, prog: prog,
          susza: ok && prog !== null && sp - se < prog, poSezonie: koniec > rokK + '-09-30' };
        break;
      }
    }
    return {
      data: koniec, spi1: spi(30), spi3: spi(90),
      sma: { wartosc: (smX - smS) / smSd, teraz: smX, norma: smS },
      tGleby: okno(k.st7, i1, DNI_GLEBY, false), wilg7: okno(k.sm7, i1, DNI_GLEBY, false), kbw: kbw
    };
  }

  function spiZGammy(x, hist) {
    if (x === null || hist.length < 10) return NaN;
    var dod = hist.filter(function (v) { return v > 0; }), q = 1 - dod.length / hist.length;
    if (dod.length < 5) return NaN;
    var sr = srednia(dod), srLn = srednia(dod.map(Math.log));
    var A = Math.log(sr) - srLn, alfa = (1 + Math.sqrt(1 + 4 * A / 3)) / (4 * A), beta = sr / alfa;
    var H = x <= 0 ? q : q + (1 - q) * gammaP(alfa, x / beta);
    return odwrNormalny(Math.min(Math.max(H, 1e-6), 1 - 1e-6));
  }
  function lnGamma(z) {
    var c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155,
      0.1208650973866179e-2, -0.5395239384953e-5];
    var y = z, tmp = z + 5.5, ser = 1.000000000190015;
    tmp -= (z + 0.5) * Math.log(tmp);
    for (var j = 0; j < 6; j++) ser += c[j] / ++y;
    return -tmp + Math.log(2.5066282746310005 * ser / z);
  }
  function gammaP(a, x) {
    if (x <= 0) return 0;
    var gln = lnGamma(a), n;
    if (x < a + 1) {
      var ap = a, sum = 1 / a, del = sum;
      for (n = 0; n < 300; n++) { ap++; del *= x / ap; sum += del; if (Math.abs(del) < Math.abs(sum) * 1e-12) break; }
      return sum * Math.exp(-x + a * Math.log(x) - gln);
    }
    var b = x + 1 - a, c = 1e300, d = 1 / b, h = d;
    for (n = 1; n < 300; n++) {
      var an = -n * (n - a); b += 2;
      d = an * d + b; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = b + an / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d; var del2 = d * c; h *= del2;
      if (Math.abs(del2 - 1) < 1e-12) break;
    }
    return 1 - Math.exp(-x + a * Math.log(x) - gln) * h;
  }
  function odwrNormalny(p) {
    var a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    var b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01];
    var c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    var d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
    var q, r;
    if (p < 0.02425) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - 0.02425) { q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    q = p - 0.5; r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  var NDVI_X = '(B08-B04)/(B08+B04)', NDWI_X = '(B08-B11)/(B08+B11)';
  var WYRAZENIA = [NDVI_X, NDWI_X, '(' + NDVI_X + '-' + NDWI_X + ')/(' + NDVI_X + '+' + NDWI_X + ')',
    'where((SCL>=4)&(SCL<=6),1.0,0.0)'];

  function przesun(data, dni) { return new Date(new Date(data + 'T12:00:00Z').getTime() + dni * 864e5).toISOString().slice(0, 10); }

  function nddiOkna(d, od, doD) {
    var klucz = od + '/' + doD;
    if (d.nddiCache[klucz]) return d.nddiCache[klucz];
    d.nddiCache[klucz] = fetch(PC + '/stac/v1/search', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        collections: ['sentinel-2-l2a'], intersects: d.geojson.geometry,
        datetime: od + 'T00:00:00Z/' + doD + 'T23:59:59Z', query: { 'eo:cloud_cover': { lt: 60 } },
        sortby: [{ field: 'eo:cloud_cover', direction: 'asc' }], limit: 30
      })
    }).then(function (r) { if (!r.ok) throw new Error('STAC ' + r.status); return r.json(); })
      .then(function (dane) {
        var dni = {}, sceny = [];
        (dane.features || []).forEach(function (s) {
          var dz = s.properties.datetime.slice(0, 10);
          if (!dni[dz]) { dni[dz] = 1; sceny.push({ id: s.id, data: dz }); }
        });
        return poKolei(sceny.slice(0, NDDI_MAKS_SCEN), function (s) { return statystykiSceny(s, d.geojson); }, 3);
      })
      .then(function (w) {
        var ok = w.filter(function (s) { return s && s.czyste >= NDDI_CZYSTE && isFinite(s.nddi); });
        var pole = function (k) { return srednia(ok.map(function (s) { return s[k]; })); };
        var lista = ok.slice().sort(function (a, b) { return a.data < b.data ? 1 : -1; });
        return { nddi: pole('nddi'), ndvi: pole('ndvi'), ndwi: pole('ndwi'), sceny: ok.length, listaScen: lista };
      });
    d.nddiCache[klucz].catch(function () { delete d.nddiCache[klucz]; });
    return d.nddiCache[klucz];
  }

  function statystykiSceny(scena, feature) {
    var url = PC + '/data/v1/item/statistics?collection=sentinel-2-l2a&item=' + encodeURIComponent(scena.id) +
      '&expression=' + encodeURIComponent(WYRAZENIA.join(';')) + '&asset_as_band=true&max_size=1024';
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(feature) })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        var st = d.properties && d.properties.statistics;
        if (!st) return null;
        var v = WYRAZENIA.map(function (x) { return st[x]; });
        if (!v[0] || !v[0].count) return null;
        return { id: scena.id, data: scena.data, ndvi: v[0].mean, ndwi: v[1].mean, nddi: v[2].median, czyste: v[3] ? v[3].mean : 0 };
      })
      .catch(function () { return null; });
  }

  function poKolei(lst, fn, rownolegle) {
    var wyniki = new Array(lst.length), i = 0;
    function nastepny() {
      if (i >= lst.length) return Promise.resolve();
      var k = i++;
      return fn(lst[k]).then(function (w) { wyniki[k] = w; return nastepny(); });
    }
    var start = [];
    for (var j = 0; j < Math.min(rownolegle, lst.length); j++) start.push(nastepny());
    return Promise.all(start).then(function () { return wyniki; });
  }

  function roslinnosc(d, data) {
    var mies = +data.slice(5, 7), rok = +data.slice(0, 4), od = przesun(data, -NDDI_DNI), lata = [];
    for (var r = NDDI_OD_ROKU; r < rok; r++) lata.push(r);
    return nddiOkna(d, od, data).then(function (teraz) {
      var w = { nddi: teraz.nddi, ndvi: teraz.ndvi, ndwi: teraz.ndwi, sceny: teraz.sceny, listaScen: teraz.listaScen,
        od: od, z: NaN, lat: 0, powod: '' };
      if (mies < 4 || mies > 9) { w.powod = 'outside growing season (IV–IX)'; return w; }
      if (!teraz.sceny) { w.powod = 'no cloud-free image'; return w; }
      if (!(teraz.ndvi >= NDVI_MIN)) { w.powod = 'NDVI < ' + NDVI_MIN + ' (bare soil)'; return w; }
      return poKolei(lata, function (r) {
        return nddiOkna(d, r + od.slice(4), r + data.slice(4)).catch(function () { return null; });
      }, 2).then(function (hist) {
        var h = hist.filter(function (x) { return x && x.sceny && isFinite(x.nddi); }).map(function (x) { return x.nddi; });
        w.lat = h.length;
        if (h.length < 3) { w.powod = 'fewer than 3 years of history'; return w; }
        var s = srednia(h), sd = Math.sqrt(h.reduce(function (a, b) { return a + (b - s) * (b - s); }, 0) / (h.length - 1));
        w.norma = s;
        w.z = sd > 0 ? (teraz.nddi - s) / sd : NaN;
        return w;
      });
    });
  }

  function klasaKryterium(k, uprawa, v) {
    if (!v) return null;
    if (k.grupy) {
      var nazwa = String(v.tekst || '').split(' (')[0].trim().toLowerCase(), grupy = k.grupy[uprawa] || [];
      for (var i = 0; i < grupy.length; i++) {
        if (grupy[i].some(function (n) { return n.toLowerCase() === nazwa; })) return i + 1;
      }
      return null;
    }
    if (!isFinite(v.liczba)) return null;
    var wiersze = k.przedzialy[uprawa] || k.przedzialy['*'] || [];
    for (var j = 0; j < wiersze.length; j++) {
      var od = wiersze[j][0], doo = wiersze[j][1];
      if ((od === null || v.liczba >= od) && (doo === null || v.liczba < doo)) return wiersze[j][2];
    }
    return null;
  }

  function punktyUprawy(am, uprawa, wart) {
    var suma = 0, maks = 0, komplet = true;
    var wiersze = am.kryteria.map(function (k) {
      var v = wart[k.warstwa], klasa = klasaKryterium(k, uprawa, v), max = Math.max.apply(null, k.punkty);
      var punkty = klasa ? k.punkty[klasa - 1] : null;
      if (punkty !== null) { suma += punkty; maks += max; } else if (k.wymagane) komplet = false;
      return { k: k, v: v, klasa: klasa, punkty: punkty, max: max };
    });
    var wynikP = (komplet && maks > 0) ? Math.floor(suma * am.maks_punktow / maks + 0.5) : null;
    return { wiersze: wiersze, suma: suma, maks: maks, wynik: wynikP, klasa: klasaZagrozenia(am, wynikP) };
  }
  function klasaZagrozenia(am, wynikP) {
    var klasa = null;
    if (wynikP !== null && isFinite(wynikP)) am.klasy.forEach(function (c, i) { if (wynikP >= c.od && wynikP <= c.do) klasa = i + 1; });
    return klasa;
  }

  function poziomCDI(spi1, spi3, sma, kbwSusza, zNddi) {
    var watch = spi3 < -1 || spi1 < -2 || !!kbwSusza;
    var warning = watch && sma < -1;
    var alert = warning && zNddi > 1;
    return alert ? 3 : warning ? 2 : watch ? 1 : 0;
  }

  var PIKSEL_M = 10, MAKS_PIKSELI = 200000, PIKSELE_SCEN = 3, PROBKI_GLEBY = 25;
  var WYR_PIKSELI = [NDVI_X, '(' + NDVI_X + '-' + NDWI_X + ')/(' + NDVI_X + '+' + NDWI_X + ')',
    'where((SCL>=4)&(SCL<=6),1.0,0.0)'];

  function siatkaDzialki(d) {
    if (d.siatka) return d.siatka;
    var geom = new ol.format.GeoJSON().readGeometry(d.geojson.geometry), e = geom.getExtent();
    var lat = (e[1] + e[3]) / 2;
    var w = Math.max(1, Math.ceil((e[2] - e[0]) / (PIKSEL_M / (111320 * Math.cos(lat * Math.PI / 180)))));
    var h = Math.max(1, Math.ceil((e[3] - e[1]) / (PIKSEL_M / 110574)));
    var k = Math.sqrt(w * h / MAKS_PIKSELI);
    if (k > 1) { w = Math.ceil(w / k); h = Math.ceil(h / k); }
    var maska = new Uint8Array(w * h), n = 0, dx = (e[2] - e[0]) / w, dy = (e[3] - e[1]) / h;
    for (var r = 0; r < h; r++) {
      for (var c = 0; c < w; c++) {
        if (geom.intersectsCoordinate([e[0] + (c + 0.5) * dx, e[3] - (r + 0.5) * dy])) { maska[r * w + c] = 1; n++; }
      }
    }
    d.siatka = { w: w, h: h, bbox: e, dx: dx, dy: dy, maska: maska, n: n, bokM: Math.round(dx * 111320 * Math.cos(lat * Math.PI / 180)) };
    return d.siatka;
  }

  function czytajNpy(buf) {
    var b = new Uint8Array(buf), dv = new DataView(buf), wersja = b[6];
    var dl = wersja >= 2 ? dv.getUint32(8, true) : dv.getUint16(8, true), start = (wersja >= 2 ? 12 : 10);
    var naglowek = new TextDecoder('latin1').decode(b.subarray(start, start + dl)), off = start + dl;
    var typ = /'descr':\s*'([^']+)'/.exec(naglowek)[1];
    var ksztalt = /'shape':\s*\(([^)]*)\)/.exec(naglowek)[1].split(',').filter(function (x) { return x.trim(); }).map(Number);
    var kopia = buf.slice(off);
    var dane = typ === '<f8' ? new Float64Array(kopia) : typ === '<f4' ? new Float32Array(kopia) : new Uint8Array(kopia);
    return { dane: dane, ksztalt: ksztalt };
  }

  function pikseleSceny(d, scena) {
    var s = siatkaDzialki(d);
    var url = PC + '/data/v1/item/bbox/' + s.bbox.join(',') + '/' + s.w + 'x' + s.h + '.npy?collection=sentinel-2-l2a&item=' +
      encodeURIComponent(scena.id) + '&expression=' + encodeURIComponent(WYR_PIKSELI.join(';')) + '&asset_as_band=true';
    return fetch(url).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
      .then(czytajNpy).catch(function () { return null; });
  }

  function mediana(a) {
    if (!a.length) return NaN;
    a.sort(function (x, y) { return x - y; });
    var m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  }

  function pikseleDzialki(d, rosl) {
    var sceny = (rosl.listaScen || []).slice(0, PIKSELE_SCEN);
    if (!sceny.length) return Promise.resolve(null);
    var s = siatkaDzialki(d), n = s.w * s.h;
    return Promise.all(sceny.map(function (sc) { return pikseleSceny(d, sc); })).then(function (tab) {
      tab = tab.filter(function (t) { return t && t.ksztalt[0] >= 4 && t.ksztalt[1] === s.h && t.ksztalt[2] === s.w; });
      if (!tab.length) return null;
      var nddi = new Float32Array(n), ndvi = new Float32Array(n);
      for (var i = 0; i < n; i++) {
        nddi[i] = ndvi[i] = NaN;
        if (!s.maska[i]) continue;
        var a = [], v = [];
        tab.forEach(function (t) {
          var D = t.dane;
          if (D[3 * n + i] > 0 && D[2 * n + i] >= 1 && isFinite(D[n + i]) && isFinite(D[i])) { v.push(D[i]); a.push(D[n + i]); }
        });
        if (a.length) { nddi[i] = mediana(a); ndvi[i] = mediana(v); }
      }
      return { siatka: s, nddi: nddi, ndvi: ndvi, sceny: tab.length, daty: sceny.slice(0, tab.length).map(function (x) { return x.data; }) };
    });
  }

  function glebaDzialki(d) {
    if (!window.rolnikWartosc) return Promise.resolve({ gleba: null, porowatosc: NaN, probki: 0, typy: {} });
    var s = siatkaDzialki(d), punkty = [], krok = Math.max(1, Math.floor(s.n / PROBKI_GLEBY)), k = 0;
    for (var i = 0; i < s.w * s.h; i++) {
      if (!s.maska[i]) continue;
      if (k++ % krok === 0) punkty.push([s.bbox[0] + ((i % s.w) + 0.5) * s.dx, s.bbox[3] - (Math.floor(i / s.w) + 0.5) * s.dy]);
    }
    if (!punkty.length) punkty.push([d.lon, d.lat]);
    return Promise.all(punkty.map(function (p) {
      return Promise.all([window.rolnikWartosc('gleba_klasa', p[0], p[1]), window.rolnikWartosc('porowatosc', p[0], p[1])]);
    })).then(function (w) {
      var typy = {}, por = [];
      w.forEach(function (x) {
        if (x[0] && x[0].tekst) typy[x[0].tekst] = (typy[x[0].tekst] || 0) + 1;
        if (x[1] && isFinite(x[1].liczba)) por.push(x[1].liczba);
      });
      var gleba = Object.keys(typy).sort(function (a, b) { return typy[b] - typy[a]; })[0] || null;
      return { gleba: gleba, porowatosc: srednia(por), probki: punkty.length, typy: typy };
    });
  }

  function mozaikaDzialki(d, am, uprawa, wartDzialki) {
    var px = d.wynik.piksele;
    if (!px || !am) return;
    var s = px.siatka, n = s.w * s.h, wynikPx = new Float32Array(n), klasy = [0, 0, 0, 0], ile = 0, suma = 0;
    var cache = {};
    for (var i = 0; i < n; i++) {
      wynikPx[i] = NaN;
      if (!s.maska[i]) continue;
      var nd = px.nddi[i], ok = isFinite(nd) && px.ndvi[i] >= 0.2;
      var klucz = ok ? nd.toFixed(3) : 'brak';
      if (cache[klucz] === undefined) {
        var wart = Object.assign({}, wartDzialki, { nddi: ok ? { liczba: nd } : null });
        cache[klucz] = punktyUprawy(am, uprawa, wart).wynik;
      }
      var p = cache[klucz];
      if (p === null) continue;
      wynikPx[i] = p; ile++; suma += p;
      var kl = klasaZagrozenia(am, p);
      if (kl) klasy[kl - 1]++;
    }
    px.wynik = wynikPx; px.ile = ile; px.srednia = ile ? suma / ile : NaN; px.klasy = klasy;
    if (!ile) return;
    var c = document.createElement('canvas');
    c.width = s.w; c.height = s.h;
    var ctx = c.getContext('2d'), obraz = ctx.createImageData(s.w, s.h), D = obraz.data;
    for (var j = 0; j < n; j++) {
      if (!isFinite(wynikPx[j])) continue;
      var rgb = /\d+,\d+,\d+/.exec(kolorSkali(wynikPx[j] / am.maks_punktow))[0].split(',');
      D[j * 4] = +rgb[0]; D[j * 4 + 1] = +rgb[1]; D[j * 4 + 2] = +rgb[2]; D[j * 4 + 3] = 215;
    }
    ctx.putImageData(obraz, 0, 0);
    usunMozaike(d);
    d.warstwaPikseli = new ol.layer.Image({
      source: new ol.source.ImageStatic({ url: c.toDataURL('image/png'), imageExtent: s.bbox, projection: 'EPSG:4326', interpolate: false })
    });
    grupaPikseli.getLayers().push(d.warstwaPikseli);
  }

  var OS_DNI = 365, OS_KROK = 10;
  var seria = null;
  var PARAMETRY_OSI = [
    { id: 'punkty', nazwa: 'Hazard score [pts]', miejsca: 1 },
    { id: 'nddi', nazwa: 'NDDI (Sentinel-2, 60 days)', miejsca: 2 },
    { id: 'ndvi', nazwa: 'NDVI (Sentinel-2, 60 days)', miejsca: 2 },
    { id: 'woda', nazwa: 'Soil water – pore filling [%]', miejsca: 0 },
    { id: 'tGleby', nazwa: 'Soil temperature 0–7 cm [°C]', miejsca: 1 },
    { id: 'kbw', nazwa: 'Climatic water balance, 60 days [mm]', miejsca: 0 },
    { id: 'spi1', nazwa: 'SPI-1 (30 days)', miejsca: 2 },
    { id: 'spi3', nazwa: 'SPI-3 (90 days)', miejsca: 2 },
    { id: 'sma', nazwa: 'SMA – soil moisture anomaly', miejsca: 2 }
  ];

  function scenyOkresu(d, od, doD, postep) {
    var klucz = 'seria:' + od + '/' + doD;
    if (d.nddiCache[klucz]) return d.nddiCache[klucz];
    d.nddiCache[klucz] = fetch(PC + '/stac/v1/search', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        collections: ['sentinel-2-l2a'], intersects: d.geojson.geometry,
        datetime: od + 'T00:00:00Z/' + doD + 'T23:59:59Z', query: { 'eo:cloud_cover': { lt: 60 } },
        sortby: [{ field: 'datetime', direction: 'asc' }], limit: 400
      })
    }).then(function (r) { if (!r.ok) throw new Error('STAC ' + r.status); return r.json(); })
      .then(function (dane) {
        var dni = {}, sceny = [];
        (dane.features || []).forEach(function (s) {
          var dz = s.properties.datetime.slice(0, 10);
          if (!dni[dz]) { dni[dz] = 1; sceny.push({ id: s.id, data: dz }); }
        });
        var zrobione = 0;
        return poKolei(sceny, function (s) {
          return statystykiSceny(s, d.geojson).then(function (w) { if (postep) postep(++zrobione, sceny.length); return w; });
        }, 4);
      })
      .then(function (w) { return w.filter(function (s) { return s && s.czyste >= NDDI_CZYSTE && isFinite(s.nddi); }); });
    d.nddiCache[klucz].catch(function () { delete d.nddiCache[klucz]; });
    return d.nddiCache[klucz];
  }

  function kbw60(k, data) {
    var i1 = k.idx[data > k.ostatni ? k.ostatni : data], s = 0;
    if (i1 === undefined || i1 < 59) return NaN;
    for (var j = i1 - 59; j <= i1; j++) { if (k.p[j] === null || k.et[j] === null) return NaN; s += k.p[j] - k.et[j]; }
    return s;
  }

  function policzSerie(dane, uprawa, daty, klucz) {
    var am = analizaMeta(), uprawaKbw = UPRAWA_KBW[uprawa] || 'Zboża jare';
    var obszar = {}, dzialki = dane.map(function (d) { return { d: d, wart: {} }; });
    PARAMETRY_OSI.forEach(function (p) { obszar[p.id] = []; dzialki.forEach(function (x) { x.wart[p.id] = []; }); });
    daty.forEach(function (t, it) {
      var od = przesun(t, -NDDI_DNI);
      dzialki.forEach(function (x) {
        var d = x.d, k = d.osDane.klimat, kl = wskaznikiKlimatu(k, t, uprawaKbw, d.kategoria);
        var okno = d.osDane.sceny.filter(function (s) { return s.data > od && s.data <= t; });
        var nddi = srednia(okno.map(function (s) { return s.nddi; })), ndvi = srednia(okno.map(function (s) { return s.ndvi; }));
        var por = d.wynik.porowatosc;
        var woda = isFinite(por) && kl.wilg7 !== null ? Math.min(100, Math.max(0, 100 * kl.wilg7 / (por / 100))) : NaN;
        var punkty = NaN;
        if (am) {
          var p = punktyUprawy(am, uprawa, {
            nddi: isFinite(nddi) && ndvi >= 0.2 ? { liczba: nddi } : null,
            gleba_klasa: d.gleba ? { tekst: d.gleba } : null,
            porowatosc: isFinite(por) ? { liczba: por } : null,
            t_gleby_era5: kl.tGleby !== null ? { liczba: kl.tGleby } : null,
            woda_w_porach: isFinite(woda) ? { liczba: woda } : null
          });
          if (p.wynik !== null) punkty = p.wynik;
        }
        var w = { punkty: punkty, nddi: nddi, ndvi: ndvi, woda: woda, tGleby: kl.tGleby === null ? NaN : kl.tGleby,
          kbw: kbw60(k, t), spi1: kl.spi1.wartosc, spi3: kl.spi3.wartosc, sma: kl.sma.wartosc };
        PARAMETRY_OSI.forEach(function (pp) { x.wart[pp.id][it] = w[pp.id]; });
      });
      PARAMETRY_OSI.forEach(function (pp) {
        obszar[pp.id][it] = srW(dzialki.map(function (x) { return x.d; }), function (d) {
          return dzialki.filter(function (x) { return x.d === d; })[0].wart[pp.id][it];
        });
      });
    });
    return { klucz: klucz, daty: daty, obszar: obszar, dzialki: dzialki, param: 'punkty' };
  }

  function przygotujOs(dane, uprawa) {
    var os = tresc.querySelector('.cdi-os');
    if (!os) return;
    grupaPikseli.setVisible(true);
    dane.forEach(function (d) { d.wynikCzasu = NaN; d.feature.changed(); });
    var data = dane[0].wynik.kl.data;
    var klucz = uprawa + '|' + dane.map(function (d) { return d.teryt + ':' + d.kategoria; }).join(',');
    if (seria && seria.klucz === klucz && data >= seria.daty[0] && data <= seria.daty[seria.daty.length - 1]) {
      var idx = 0;
      seria.daty.forEach(function (t, i) { if (t <= data) idx = i; });
      rysujOs(os, idx, true);
      return;
    }
    seria = null;
    os.innerHTML = '<div class="rolnik-sekcja">Timeline</div>' +
      '<div class="cdi-uwaga" style="margin-top:0">How the parameters changed in the 12 months before ' + data +
      ' (every ' + OS_KROK + ' days). All Sentinel-2 images of the year are analysed – this can take 0.5–2 minutes.</div>' +
      '<button type="button" class="cdi-os-przycisk">Load timeline</button>';
    os.querySelector('button').onclick = function () { zaladujOs(dane, uprawa, data, klucz, os); };
  }

  function zaladujOs(dane, uprawa, data, klucz, os) {
    var btn = os.querySelector('button');
    btn.disabled = true;
    var daty = [];
    for (var t = przesun(data, -OS_DNI); t < data; t = przesun(t, OS_KROK)) daty.push(t);
    daty.push(data);
    var od = przesun(daty[0], -NDDI_DNI), nr = 0;
    poKolei(dane, function (d) {
      var ktora = ++nr;
      return Promise.all([daneKlimatu(d.lon, d.lat), scenyOkresu(d, od, data, function (i, n) {
        btn.textContent = 'Loading Sentinel-2: parcel ' + ktora + '/' + dane.length + ', image ' + i + '/' + n + '…';
      })]).then(function (w) { d.osDane = { klimat: w[0], sceny: w[1] }; });
    }, 1).then(function () {
      seria = policzSerie(dane, uprawa, daty, klucz);
      rysujOs(os, daty.length - 1, true);
    }).catch(function (e) {
      os.innerHTML = '<div class="rolnik-blad">Timeline failed: ' + esc(e.message) + '</div>';
    });
  }

  function rysujOs(os, idx, nowy) {
    var am = analizaMeta(), S = seria;
    if (nowy || !os.querySelector('canvas')) {
      os.innerHTML = '<div class="rolnik-sekcja">Timeline <small>' + S.daty[0] + ' – ' + S.daty[S.daty.length - 1] + '</small></div>' +
        '<select class="cdi-os-param">' + PARAMETRY_OSI.map(function (p) {
          return '<option value="' + p.id + '"' + (p.id === S.param ? ' selected' : '') + '>' + p.nazwa + '</option>';
        }).join('') + '</select><canvas width="520" height="240"></canvas>' +
        '<input type="range" class="cdi-os-suwak" min="0" max="' + (S.daty.length - 1) + '" step="1" value="' + idx + '">' +
        '<div class="cdi-os-odczyt"></div>' +
        '<button type="button" class="cdi-os-przycisk">Analyse this date in detail</button>' +
        '<div class="cdi-uwaga">Move the slider – the parcels on the map are coloured by the hazard score on that date ' +
        '(green = good, red = bad). Points are coloured the same way.</div>';
      os.querySelector('.cdi-os-param').onchange = function () { S.param = this.value; rysujOs(os, +os.querySelector('.cdi-os-suwak').value); };
      os.querySelector('.cdi-os-suwak').oninput = function () { rysujOs(os, +this.value); };
      os.querySelector('.cdi-os-przycisk').onclick = function () {
        poleData.value = S.daty[+os.querySelector('.cdi-os-suwak').value];
        oblicz();
      };
    }
    os.querySelector('.cdi-os-suwak').value = idx;

    var c = os.querySelector('canvas'), g = c.getContext('2d'), W = c.width, H = c.height, L = 44, R = 8, T = 10, B = 26;
    var y = S.obszar[S.param], par = PARAMETRY_OSI.filter(function (p) { return p.id === S.param; })[0];
    var wart = y.filter(isFinite), lo, hi;
    if (S.param === 'punkty' && am) { lo = 0; hi = am.maks_punktow; }
    else {
      lo = Math.min.apply(null, wart); hi = Math.max.apply(null, wart);
      if (/spi|sma/.test(S.param)) { lo = Math.min(lo, -2); hi = Math.max(hi, 2); }
      if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
      var pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    }
    var X = function (i) { return L + (W - L - R) * i / Math.max(1, S.daty.length - 1); };
    var Y = function (v) { return T + (H - T - B) * (1 - (v - lo) / (hi - lo)); };
    g.clearRect(0, 0, W, H);
    g.font = '18px system-ui, sans-serif';
    if (S.param === 'punkty' && am) {
      am.klasy.forEach(function (k, i) {
        g.fillStyle = kolorSkali((k.od + k.do) / 2 / am.maks_punktow, 0.18);
        g.fillRect(L, Y(Math.min(hi, k.do + 0.5)), W - L - R, Y(Math.max(lo, k.od - 0.5)) - Y(Math.min(hi, k.do + 0.5)));
      });
    }
    g.strokeStyle = '#ccc'; g.lineWidth = 1; g.fillStyle = '#666';
    [lo, (lo + hi) / 2, hi].forEach(function (v) {
      g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W - R, Y(v)); g.stroke();
      g.fillText(v.toFixed(par.miejsca === 0 || Math.abs(hi - lo) > 20 ? 0 : 1), 2, Y(v) + 6);
    });
    if (lo < 0 && hi > 0) { g.strokeStyle = '#888'; g.beginPath(); g.moveTo(L, Y(0)); g.lineTo(W - R, Y(0)); g.stroke(); }
    g.fillStyle = '#666';
    var ostX = -99;
    S.daty.forEach(function (t, i) {
      if ((i === 0 || t.slice(5, 7) !== S.daty[i - 1].slice(5, 7)) && X(i) - ostX > 30) {
        g.fillText(RZYM[+t.slice(5, 7)], X(i) - 6, H - 6);
        ostX = X(i);
      }
    });
    g.strokeStyle = '#2e5e2a'; g.lineWidth = 2.5; g.beginPath();
    var start = true;
    y.forEach(function (v, i) {
      if (!isFinite(v)) { start = true; return; }
      if (start) g.moveTo(X(i), Y(v)); else g.lineTo(X(i), Y(v));
      start = false;
    });
    g.stroke();
    y.forEach(function (v, i) {
      if (!isFinite(v)) return;
      var pk = S.obszar.punkty[i];
      g.fillStyle = isFinite(pk) && am ? kolorSkali(pk / am.maks_punktow) : '#2e5e2a';
      g.beginPath(); g.arc(X(i), Y(v), i === idx ? 7 : 4.5, 0, 2 * Math.PI); g.fill();
      if (i === idx) { g.strokeStyle = '#222'; g.lineWidth = 2; g.stroke(); }
    });
    g.strokeStyle = 'rgba(0,0,0,0.6)'; g.lineWidth = 1.5; g.setLineDash([5, 4]);
    g.beginPath(); g.moveTo(X(idx), T); g.lineTo(X(idx), H - B); g.stroke(); g.setLineDash([]);

    var o = function (id) { return S.obszar[id][idx]; }, pk0 = o('punkty');
    var kl = am && isFinite(pk0) ? klasaZagrozenia(am, Math.round(pk0)) : null;
    os.querySelector('.cdi-os-odczyt').innerHTML = '<b>' + S.daty[idx] + '</b> · Hazard ' +
      ocena(f1(pk0) + ' pts', am ? pk0 / am.maks_punktow : NaN) + (kl ? ' ' + esc(am.klasy[kl - 1].nazwa) : '') + '<br>' +
      'NDDI ' + f2(o('nddi')) + ' · NDVI ' + f2(o('ndvi')) + ' · water ' + f0(o('woda')) + '% · soil ' + f1(o('tGleby')) + ' °C<br>' +
      'KBW ' + f0(o('kbw')) + ' mm · SPI-1 ' + f2(o('spi1')) + ' · SPI-3 ' + f2(o('spi3')) + ' · SMA ' + f2(o('sma'));

    var d0 = S.dzialki[0] && S.dzialki[0].d, naDacieAnalizy = !!(d0 && d0.wynik && d0.wynik.kl.data === S.daty[idx]);
    S.dzialki.forEach(function (x) { x.d.wynikCzasu = naDacieAnalizy ? NaN : x.wart.punkty[idx]; x.d.feature.changed(); });
    grupaPikseli.setVisible(naDacieAnalizy);
  }

  function oblicz() {
    var data = poleData.value || dzis, uprawa = poleUprawa.value, uprawaKbw = UPRAWA_KBW[uprawa] || 'Zboża jare';
    var dane = stan.dzialki.slice();
    if (!dane.length) return;
    liczenie = true;
    odswiezListe();
    var gotowe = 0;
    przyciskOblicz.textContent = 'Downloading data (0/' + dane.length + ')…';
    wynik.innerHTML = '';
    szczegoly.innerHTML = '<div class="panel-pusty">Downloading data…</div>';
    poKolei(dane, function (d) {
      d.wynik = null; d.blad = null;
      usunMozaike(d);
      return Promise.all([daneKlimatu(d.lon, d.lat), glebaDzialki(d)]).then(function (w) {
        var kl = wskaznikiKlimatu(w[0], data, uprawaKbw, d.kategoria), gl = w[1];
        if (gl.gleba) d.gleba = gl.gleba;
        var porowatosc = gl.porowatosc;
        return roslinnosc(d, kl.data).catch(function (e) { return { z: NaN, powod: e.message }; }).then(function (r) {
          return pikseleDzialki(d, r).catch(function () { return null; }).then(function (piksele) {
            var woda = isFinite(porowatosc) && kl.wilg7 !== null ? Math.min(100, Math.max(0, 100 * kl.wilg7 / (porowatosc / 100))) : NaN;
            d.wynik = { kl: kl, rosl: r, porowatosc: porowatosc, woda: woda, glebaProbki: gl, piksele: piksele };
            d.wynik.cdi = poziomCDI(kl.spi1.wartosc, kl.spi3.wartosc, kl.sma.wartosc, kl.kbw && kl.kbw.susza, r.z);
            var am = analizaMeta();
            if (am) {
              var wart = {
                nddi: isFinite(r.nddi) && r.ndvi >= 0.2 ? { liczba: r.nddi } : null,
                gleba_klasa: d.gleba ? { tekst: d.gleba } : null,
                porowatosc: isFinite(porowatosc) ? { liczba: porowatosc } : null,
                t_gleby_era5: kl.tGleby !== null ? { liczba: kl.tGleby } : null,
                woda_w_porach: isFinite(woda) ? { liczba: woda } : null
              };
              d.wynik.punkty = punktyUprawy(am, uprawa, wart);
              mozaikaDzialki(d, am, uprawa, wart);
            }
          });
        });
      }).catch(function (e) { d.blad = e.message; }).then(function () {
        d.feature.changed();
        przyciskOblicz.textContent = 'Downloading data (' + (++gotowe) + '/' + dane.length + ')…';
      });
    }, 2).then(function () {
      var ok = dane.filter(function (d) { return d.wynik; });
      if (!ok.length) {
        wynik.innerHTML = '<div class="rolnik-blad">Could not download the data: ' + esc((dane[0] && dane[0].blad) || '') + '</div>';
        szczegoly.innerHTML = PUSTE_SZCZEGOLY;
        return;
      }
      pokazWynik(ok, uprawa);
      pokazSzczegoly(ok, uprawa);
      if (window.panelSzczegoly && window.panelSzczegoly.rozwin) window.panelSzczegoly.rozwin();
    }).then(function () { liczenie = false; odswiezListe(); });
  }

  function srW(dane, fn) {
    var s = 0, w = 0;
    dane.forEach(function (d) { var v = fn(d); if (isFinite(v)) { s += v * d.ha; w += d.ha; } });
    return w ? s / w : NaN;
  }
  function nazwaUprawy(id) { var u = uprawy().filter(function (x) { return x.id === id; })[0]; return u ? u.nazwa : id; }
  function znaczekKlasy(am, klasa) {
    if (!klasa) return '–';
    return '<span class="cdi-klasa" style="background:' + KOLORY_KLAS[klasa - 1] + (klasa === 2 ? ';color:#222' : '') + '">' +
      esc(am ? am.klasy[klasa - 1].nazwa : RZYM[klasa]) + '</span>';
  }

  function pokazWynik(dane, uprawa) {
    var am = analizaMeta(), ha = dane.reduce(function (a, d) { return a + d.ha; }, 0), dataD = dane[0].wynik.kl.data;
    var h = '';
    var zPunktami = dane.filter(function (d) { return d.wynik.punkty && d.wynik.punkty.wynik !== null; });
    if (am && zPunktami.length) {
      var wynikP = Math.round(srW(zPunktami, function (d) { return d.wynik.punkty.wynik; }));
      var klasa = klasaZagrozenia(am, wynikP), tObszar = wynikP / am.maks_punktow;
      h += '<div class="cdi-poziom' + (tObszar > 0.3 && tObszar < 0.7 ? ' jasny' : '') + '" style="background:' + kolorSkali(tObszar) + '">' +
        'Hazard: ' + esc(klasa ? am.klasy[klasa - 1].nazwa : '–') + ' · ' + wynikP + ' / ' + am.maks_punktow + ' pts' +
        '<small>' + esc(nazwaUprawy(uprawa)) + ' · ' + dane.length + (dane.length === 1 ? ' parcel' : ' parcels') + ', ' +
        ha.toFixed(2) + ' ha · data to ' + dataD + '</small></div>';
      h += pasekSkali(tObszar, '0 pts – good', am.maks_punktow + ' pts – bad');
      h += '<table class="cdi-tab"><tr><th>Criterion</th><th>Points</th></tr>' + am.kryteria.map(function (k, i) {
        var pk = srW(zPunktami, function (d) { var x = d.wynik.punkty.wiersze[i]; return x.punkty === null ? NaN : x.punkty; });
        var max = Math.max.apply(null, k.punkty);
        return '<tr><td>' + esc(k.nazwa) + '</td><td>' + ocena((isFinite(pk) ? f1(pk) : '–') + ' / ' + max, pk / max) + '</td></tr>';
      }).join('') + '<tr class="obszar"><td>Total (scaled to ' + am.maks_punktow + ')</td><td>' +
        ocena(wynikP + ' / ' + am.maks_punktow, tObszar) + '</td></tr></table>';
    } else {
      h += '<div class="cdi-uwaga">Multi-criteria scoring unavailable (no analysis data on the map or missing soil data).</div>';
    }

    var cdi = poziomCDI(srW(dane, function (d) { return d.wynik.kl.spi1.wartosc; }), srW(dane, function (d) { return d.wynik.kl.spi3.wartosc; }),
      srW(dane, function (d) { return d.wynik.kl.sma.wartosc; }), false, srW(dane, function (d) { return d.wynik.rosl.z; }));
    var haKbw = dane.reduce(function (a, d) { return a + (d.wynik.kl.kbw && d.wynik.kl.kbw.susza ? d.ha : 0); }, 0);
    var udzialKbw = 100 * haKbw / ha;
    if (udzialKbw >= 50 && cdi === 0) cdi = 1;
    var kbw0 = dane[0].wynik.kl.kbw, stosuje = dane.some(function (d) { return d.wynik.kl.kbw && d.wynik.kl.kbw.prog !== null; });
    h += '<div class="cdi-linia"><span class="cdi-kropka" style="background:' + POZIOMY_CDI[cdi].kolor + '"></span>Drought (CDI): <b>' +
      POZIOMY_CDI[cdi].nazwa + '</b></div>';
    h += '<div class="cdi-linia">Drought risk (Dz.U. 2019 poz. 739): ' + (!kbw0 ? '<i>no complete period yet</i>' :
      !stosuje ? '<i>not applicable (' + etykietaOkresu(OKRESY[kbw0.okres]) + ')</i>' :
        '<b class="' + (haKbw ? 'tak' : 'nie') + '">' + (haKbw ? 'YES' : 'NO') + '</b> – ' + udzialKbw.toFixed(0) + '% of area') + '</div>';

    if (dane.length > 1) {
      h += '<table class="cdi-tab" style="margin-top:6px"><tr><th>Parcel</th><th>Points</th><th>Hazard</th><th>CDI</th></tr>' +
        dane.map(function (d) {
          var p = d.wynik.punkty, c = POZIOMY_CDI[d.wynik.cdi];
          return '<tr><td title="' + esc(d.teryt) + '">' + esc(d.numer) + '</td><td>' + (p && p.wynik !== null ? ocena(p.wynik, ocenaDzialki(d)) : '–') +
            '</td><td>' + znaczekKlasy(am, p && p.klasa) + '</td><td><span class="cdi-kropka" style="background:' + c.kolor + '"></span>' +
            c.nazwa + '</td></tr>';
        }).join('') + '</table>';
    }
    h += '<div class="cdi-uwaga">Values of each parameter: see <b>Detailed data</b>.<br>' +
      'Hazard = sum of points (0, 2, 4 or 6) for NDDI, soil type, soil temperature and soil water; classes ' +
      'I 0–4, II 5–13, III 14–20, IV 21–24 (skrypty/analiza_mapa.py). CDI = SPI, SMA, KBW and NDDI anomaly (EDO scheme).</div>';
    wynik.innerHTML = h;
    przygotujOs(dane, uprawa);
  }

  function sekcja(tytul, opis, kolumny, dane) {
    var h = '<div class="cdi-sekcja">' + tytul + (opis ? ' <small>' + opis + '</small>' : '') + '</div><table class="cdi-tab"><tr>' +
      (dane.length > 1 ? '<th>Parcel</th>' : '') + kolumny.map(function (k) { return '<th>' + k[0] + '</th>'; }).join('') + '</tr>';
    dane.forEach(function (d) {
      h += '<tr>' + (dane.length > 1 ? '<td title="' + esc(d.teryt) + '">' + esc(d.numer) + '</td>' : '') +
        kolumny.map(function (k) { return '<td>' + k[1](d) + '</td>'; }).join('') + '</tr>';
    });
    if (dane.length > 1) {
      h += '<tr class="obszar"><td>Area</td>' + kolumny.map(function (k) { return '<td>' + (k[2] ? k[2](dane) : '') + '</td>'; }).join('') + '</tr>';
    }
    return h + '</table>';
  }

  function pokazSzczegoly(dane, uprawa) {
    var w0 = dane[0].wynik, kl0 = w0.kl, am = analizaMeta();
    var sr = function (fn, fmt) { return function (ds) { return fmt(srW(ds, fn)); }; };
    var punktyKr = function (i) {
      return function (d) {
        var p = d.wynik.punkty, x = p && p.wiersze[i];
        return x && x.punkty !== null ? ocena(x.punkty + ' / ' + x.max, x.punkty / x.max) : '–';
      };
    };
    var idx = {};
    if (am) am.kryteria.forEach(function (k, i) { idx[k.warstwa] = i; });
    var kolPunkty = function (warstwa) { return am && idx[warstwa] !== undefined ? [['Points', punktyKr(idx[warstwa])]] : []; };

    var h = '<div class="cdi-uwaga" style="margin-top:0">' + esc(nazwaUprawy(uprawa)) + ' · data to ' + kl0.data + ' · ' +
      dane.length + (dane.length === 1 ? ' parcel (' + esc(dane[0].numer) + ', ' + esc(dane[0].obreb) + ')' : ' parcels') + '</div>';

    h += sekcja('Soil type', 'SoilGrids; category per Dz.U. 2019 poz. 739', [
      ['Type', function (d) { return esc(d.gleba || '–'); }],
      ['Cat.', function (d) { return d.kategoria; }]
    ].concat(kolPunkty('gleba_klasa')), dane);
    h += sekcja('Total porosity', 'SoilGrids; used for soil water (pore filling)', [
      ['%', function (d) { return f1(d.wynik.porowatosc); }, sr(function (d) { return d.wynik.porowatosc; }, f1)]
    ].concat(kolPunkty('porowatosc')), dane);

    h += sekcja('Soil temperature', '0–7 cm, ' + DNI_GLEBY + '-day mean (ERA5-Land)', [
      ['°C', function (d) { return f1(d.wynik.kl.tGleby); }, sr(function (d) { return d.wynik.kl.tGleby; }, f1)]
    ].concat(kolPunkty('t_gleby_era5')), dane);

    h += sekcja('Soil water', 'ERA5-Land', [
      ['0–7 cm', function (d) { return f2(d.wynik.kl.wilg7) + ' m³/m³'; }, sr(function (d) { return d.wynik.kl.wilg7; }, function (v) { return f2(v) + ' m³/m³'; })],
      ['Pores', function (d) { return f0(d.wynik.woda) + ' %'; }, sr(function (d) { return d.wynik.woda; }, function (v) { return f0(v) + ' %'; })]
    ].concat(kolPunkty('woda_w_porach')), dane);
    h += sekcja('Soil moisture anomaly (SMA)', '0–100 cm, ' + SMA_DNI + ' days vs ' + OD_ROKU + '–' + (+kl0.data.slice(0, 4) - 1), [
      ['Now', function (d) { return f2(d.wynik.kl.sma.teraz); }],
      ['Normal', function (d) { return f2(d.wynik.kl.sma.norma); }],
      ['SMA', function (d) { return f2(d.wynik.kl.sma.wartosc); }, sr(function (d) { return d.wynik.kl.sma.wartosc; }, f2)]
    ], dane);

    h += sekcja('Precipitation', 'ERA5, sum vs normal 1991–' + (+kl0.data.slice(0, 4) - 1), [
      ['30 d', function (d) { return f0(d.wynik.kl.spi1.suma) + '/' + f0(d.wynik.kl.spi1.norma) + ' mm'; }],
      ['SPI-1', function (d) { return f2(d.wynik.kl.spi1.wartosc); }, sr(function (d) { return d.wynik.kl.spi1.wartosc; }, f2)],
      ['90 d', function (d) { return f0(d.wynik.kl.spi3.suma) + '/' + f0(d.wynik.kl.spi3.norma) + ' mm'; }],
      ['SPI-3', function (d) { return f2(d.wynik.kl.spi3.wartosc); }, sr(function (d) { return d.wynik.kl.spi3.wartosc; }, f2)]
    ], dane);

    var kbw0 = kl0.kbw;
    h += sekcja('Climatic water balance (KBW)', kbw0 ? etykietaOkresu(OKRESY[kbw0.okres]) + ', Dz.U. 2019 poz. 739' : 'no complete period yet', [
      ['P', function (d) { return f0(d.wynik.kl.kbw && d.wynik.kl.kbw.opad); }],
      ['ET0', function (d) { return f0(d.wynik.kl.kbw && d.wynik.kl.kbw.et0); }],
      ['KBW', function (d) { return f0(d.wynik.kl.kbw && d.wynik.kl.kbw.wartosc); }, sr(function (d) { return d.wynik.kl.kbw ? d.wynik.kl.kbw.wartosc : NaN; }, f0)],
      ['Thr.', function (d) { var k = d.wynik.kl.kbw; return !k ? '–' : k.prog === null ? 'x' : k.prog; }],
      ['Drought', function (d) { var k = d.wynik.kl.kbw; return !k || k.prog === null ? '–' : (k.susza ? '<b style="color:#c62828">YES</b>' : 'no'); }]
    ], dane);

    h += sekcja('Vegetation', 'Sentinel-2, ' + NDDI_DNI + ' days to ' + kl0.data, [
      ['NDVI', function (d) { return f2(d.wynik.rosl.ndvi); }, sr(function (d) { return d.wynik.rosl.ndvi; }, f2)],
      ['NDWI', function (d) { return f2(d.wynik.rosl.ndwi); }],
      ['NDDI', function (d) { return f2(d.wynik.rosl.nddi); }, sr(function (d) { return d.wynik.rosl.nddi; }, f2)],
      ['Img.', function (d) { return d.wynik.rosl.sceny || 0; }]
    ].concat(kolPunkty('nddi')), dane);
    h += sekcja('NDDI anomaly', 'vs same weeks ' + NDDI_OD_ROKU + '–' + (+kl0.data.slice(0, 4) - 1), [
      ['Normal', function (d) { return f2(d.wynik.rosl.norma); }],
      ['z', function (d) { return isFinite(d.wynik.rosl.z) ? f2(d.wynik.rosl.z) : '<span title="' + esc(d.wynik.rosl.powod || '') + '">–</span>'; },
        sr(function (d) { return d.wynik.rosl.z; }, f2)],
      ['Years', function (d) { return d.wynik.rosl.lat || 0; }]
    ], dane);
    var procKlasy = function (k) {
      return function (d) {
        var p = d.wynik.piksele;
        return p && p.ile ? f0(100 * p.klasy[k] / p.ile) + '%' : '–';
      };
    };
    var zPikselami = dane.filter(function (d) { return d.wynik.piksele && d.wynik.piksele.ile; });
    if (am && zPikselami.length) {
      var p0 = zPikselami[0].wynik.piksele;
      h += sekcja('Within-parcel map', 'Sentinel-2 pixels ~' + p0.siatka.bokM + ' m, median of ' + p0.sceny + ' image(s): ' + p0.daty.join(', '), [
        ['Pixels', function (d) { var p = d.wynik.piksele; return p ? p.ile : '–'; }],
        ['Mean', function (d) { var p = d.wynik.piksele; return p && p.ile ? ocena(f1(p.srednia), p.srednia / am.maks_punktow) : '–'; },
          sr(function (d) { return d.wynik.piksele ? d.wynik.piksele.srednia : NaN; }, function (v) { return ocena(f1(v), v / am.maks_punktow); })],
        ['I', procKlasy(0)], ['II', procKlasy(1)], ['III', procKlasy(2)], ['IV', procKlasy(3)]
      ], dane);
      h += '<div class="cdi-uwaga">Map colours per 10 m pixel: NDDI of the pixel + parcel-average soil type, soil ' +
        'temperature and soil water (these come from coarser data). Columns I–IV: share of pixels in each hazard class.</div>';
    } else {
      h += '<div class="cdi-uwaga">Within-parcel map unavailable: no cloud-free Sentinel-2 image in the last ' + NDDI_DNI + ' days.</div>';
    }
    var gp = dane[0].wynik.glebaProbki;
    if (gp && gp.probki) {
      h += '<div class="cdi-uwaga">Soil averaged over ' + gp.probki + ' points inside the parcel' +
        (Object.keys(gp.typy).length > 1 ? ' (types: ' + Object.keys(gp.typy).map(function (t) { return esc(t) + ' ×' + gp.typy[t]; }).join(', ') + ' – most frequent used)' : '') + '.</div>';
    }

    var bez = dane.filter(function (d) { return !isFinite(d.wynik.rosl.z); });
    if (bez.length) h += '<div class="cdi-uwaga">NDDI anomaly not calculated: ' + esc(bez[0].wynik.rosl.powod || 'no data') + '.</div>';
    h += '<div class="cdi-uwaga">Sources: ERA5 / ERA5-Land (Copernicus) via Open-Meteo; Sentinel-2 L2A via Microsoft Planetary ' +
      'Computer; soil – SoilGrids (ISRIC); KBW thresholds – Dz.U. 2019 poz. 739. KBW = precipitation − ET0 (FAO); IUNG uses its ' +
      'own evapotranspiration formula from IMGW stations, so ERA5 KBW is usually ~10–20 mm lower.</div>';
    szczegoly.innerHTML = h;
  }
})();
