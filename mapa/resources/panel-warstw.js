

(function () {
  if (typeof map === 'undefined' || !window.ol || !ol.control || !ol.control.LayerSwitcher) return;

  if (typeof layerSwitcher !== 'undefined' && layerSwitcher) {
    map.removeControl(layerSwitcher);
  }

  var kolumna = document.createElement('div');
  kolumna.className = 'ol-unselectable panele-lewy-dol';
  map.addControl(new ol.control.Control({ element: kolumna }));

  function nowyPanel(tytul, klasaTresci, tresc, poRozwinieciu) {
    var p = document.createElement('div');
    p.className = 'rolnik-panel panel-warstw zwiniety';
    p.innerHTML =
      '<div class="rolnik-naglowek"><span>' + tytul + '</span>' +
      '<button type="button" class="rolnik-zwin" title="Collapse / expand">+</button></div>' +
      '<div class="rolnik-tresc ' + klasaTresci + '">' + (tresc || '') + '</div>';
    var b = p.querySelector('.rolnik-zwin');
    p.rozwin = function () { if (p.classList.contains('zwiniety')) b.onclick(); };
    b.onclick = function () {
      var zwiniety = p.classList.toggle('zwiniety');
      b.textContent = zwiniety ? '+' : '–';
      if (!zwiniety && poRozwinieciu) poRozwinieciu();
    };
    kolumna.appendChild(p);
    return p;
  }

  var panel = nowyPanel('Layers', 'panel-warstw-tresc',
    '<div class="panel-warstw-lista"></div>' +
    '<div class="panel-warstwy-analityczne"></div>' +
    '<div class="panel-mapy-zagrozenia"></div>', rysuj);
  var lista = panel.querySelector('.panel-warstw-lista');
  function rysuj() {
    ol.control.LayerSwitcher.renderPanel(map, lista, { reverse: true, groupSelectStyle: 'children' });
  }
  rysuj();
  map.getLayers().on('change:length', rysuj);

  window.panelSzczegoly = nowyPanel('Detailed data', 'panel-szczegoly',
    '<div class="panel-pusty">Select parcels in “Final analysis” and click “Calculate” – the results of each ' +
    'parameter will appear here.</div>');
  window.panelAnalizy = nowyPanel('Final analysis', 'panel-analiza-koncowa', '<div class="panel-pusty">Loading…</div>');

  var logo = document.createElement('div');
  logo.className = 'logo-mapy';
  logo.innerHTML = '<img src="images/logo_duze.png" alt="Farmer101">';
  map.addControl(new ol.control.Control({ element: logo }));

  var cel = panel.querySelector('.panel-warstwy-analityczne');
  cel.innerHTML = '<div class="rolnik-grupa">Analysis layers</div>';
  function przeniesRolnika() {
    var r = document.querySelector('.rolnik-panel.rolnik-ol');
    if (!r) return false;
    if (r.parentNode !== cel) {
      r.classList.remove('zwiniety');
      r.classList.add('rolnik-osadzony');
      cel.appendChild(r);
    }
    return true;
  }
  if (!przeniesRolnika()) {
    var obserwator = new MutationObserver(function () {
      if (przeniesRolnika()) obserwator.disconnect();
    });
    obserwator.observe(map.getTargetElement(), { childList: true, subtree: true });
  }
})();
