var wms_layers = [];


        var lyr_OpenTopoMap_0 = new ol.layer.Tile({
            'title': 'OpenTopoMap',
            'opacity': 1.000000,
            
            
            source: new ol.source.XYZ({
            attributions: '<a href="https://www.openstreetmap.org/copyright">Kartendaten: © OpenStreetMap-Mitwirkende, SRTM | Kartendarstellung: © OpenTopoMap (CC-BY-SA)</a>',
                url: 'https://a.tile.opentopomap.org/{z}/{x}/{y}.png'
            })
        });

        var lyr_ESRISatellite_1 = new ol.layer.Tile({
            'title': 'ESRI Satellite',
            'opacity': 1.000000,
            
            
            source: new ol.source.XYZ({
            attributions: ' ',
                url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
            })
        });
var group_Podkady = new ol.layer.Group({
                                layers: [lyr_OpenTopoMap_0,lyr_ESRISatellite_1,],
                                fold: 'open',
                                title: 'Base map'});

lyr_OpenTopoMap_0.setVisible(true);lyr_ESRISatellite_1.setVisible(true);

        // Działki ewidencyjne – Krajowa Integracja Ewidencji Gruntów (GUGiK)
        var lyr_KIEG_dzialki = new ol.layer.Image({
            'title': 'Cadastral parcels (KIEG)',
            'opacity': 1.000000,
            minZoom: 15,
            source: new ol.source.ImageWMS({
                url: 'https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow',
                attributions: 'Działki: <a href="https://www.geoportal.gov.pl">GUGiK – KIEG</a>',
                params: {
                    'LAYERS': 'dzialki,numery_dzialek',
                    'FORMAT': 'image/png',
                    'TRANSPARENT': true,
                    'VERSION': '1.3.0'
                },
                ratio: 1
            })
        });
        wms_layers.push([lyr_KIEG_dzialki, 0]);
var group_Dane = new ol.layer.Group({
                                layers: [lyr_KIEG_dzialki,],
                                fold: 'open',
                                title: 'Data'});
lyr_KIEG_dzialki.setVisible(true);
var layersList = [group_Podkady,group_Dane];
