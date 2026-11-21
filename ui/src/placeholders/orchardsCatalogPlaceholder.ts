import type { GeoCoord, ObjectIdString, OrchardOption, UserPreferencesDoc } from '../types/orchard';

/**
 * [PLACEHOLDER] Snapshot of all 6 real `Orchard` parcels from local MongoDB `field_under_pressure`
 * (WGS 84 / EPSG:4326 outer polygon rings, areas, and representative centroids).
 *
 * `Grojec A` (`6b01933c1dc02a368703a020`) has a matching LiDAR file `ui/public/las/6b01933c1dc02a368703a020.las`.
 * Selecting any of the other 5 orchards demonstrates the automatic 3D geometric fallback!
 */

export interface PlaceholderOrchardCatalogEntry {
  _id: ObjectIdString;
  name: string;
  locationLabel: string;
  areaHectares: number;
  shapeAreaM2: number;
  shapeLengthM: number;
  centroid: { lat: number; long: number };
  geometry: GeoCoord[];
}

export const PLACEHOLDER_ORCHARDS_CATALOG: PlaceholderOrchardCatalogEntry[] = [
  {
    _id: '6b01933c1dc02a368703a020',
    name: 'Grojec A',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    areaHectares: 2.22,
    shapeAreaM2: 22195.94,
    shapeLengthM: 666.7,
    centroid: { lat: 51.84500651945899, long: 20.853053595656995 },
    geometry: [
      { lat: 51.84447031436461, lng: 20.85185092156493 },
      { lat: 51.845577735233036, lng: 20.85194842604751 },
      { lat: 51.845542724553376, lng: 20.853352285976772 },
      { lat: 51.845774353581064, lng: 20.853382621744633 },
      { lat: 51.845798670667115, lng: 20.855111625449258 },
      { lat: 51.84446227417943, lng: 20.853588952884014 },
    ],
  },
  {
    _id: '6b01933c1dc02a368703a01e',
    name: 'Orchard …a01e',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    areaHectares: 19.04,
    shapeAreaM2: 190438.91,
    shapeLengthM: 1808.63,
    centroid: { lat: 51.841167020382436, long: 20.860119492860083 },
    geometry: [
      { lat: 51.84018539948281, lng: 20.856746313955444 },
      { lat: 51.8427921918992, lng: 20.85714294258374 },
      { lat: 51.84266179554174, lng: 20.862781867362635 },
      { lat: 51.842181271348004, lng: 20.86271186748258 },
      { lat: 51.84214864128206, lng: 20.863457025563633 },
      { lat: 51.83848632235679, lng: 20.863032788517533 },
      { lat: 51.83855189594783, lng: 20.862408394465344 },
      { lat: 51.83857079304955, lng: 20.85762099945871 },
      { lat: 51.84012785920412, lng: 20.85773655907259 },
    ],
  },
  {
    _id: '6b01933c1dc02a368703a01f',
    name: 'Grojec B',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    areaHectares: 3.56,
    shapeAreaM2: 35620.67,
    shapeLengthM: 974.18,
    centroid: { lat: 51.8436659917444, long: 20.85386388022492 },
    geometry: [
      { lat: 51.842973021380104, lng: 20.850886850900565 },
      { lat: 51.84323546345967, lng: 20.850924157692553 },
      { lat: 51.844140845518474, lng: 20.85345616291046 },
      { lat: 51.84442228616163, lng: 20.85385257338865 },
      { lat: 51.84442685174037, lng: 20.855126742550315 },
      { lat: 51.84426680368923, lng: 20.855372301636507 },
      { lat: 51.84420972198844, lng: 20.855343413130925 },
      { lat: 51.843909820052644, lng: 20.855596490110457 },
      { lat: 51.842923262177514, lng: 20.855608995469755 },
      { lat: 51.842943431320094, lng: 20.853287541056492 },
      { lat: 51.84341902773542, lng: 20.853360158332645 },
      { lat: 51.843422163436166, lng: 20.852827351259513 },
      { lat: 51.84295875075324, lng: 20.85283698390525 },
    ],
  },
  {
    _id: '6b01933c1dc02a368703a021',
    name: 'Orchard …a021',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    areaHectares: 8.16,
    shapeAreaM2: 81571.94,
    shapeLengthM: 1641.47,
    centroid: { lat: 51.84734094419504, long: 20.853031624206896 },
    geometry: [
      { lat: 51.848298692049006, lng: 20.850300802300215 },
      { lat: 51.84822534054393, lng: 20.857407978418806 },
      { lat: 51.84711586428069, lng: 20.85736308685295 },
      { lat: 51.84706651576727, lng: 20.857301974221734 },
      { lat: 51.84707295085576, lng: 20.856892079900202 },
      { lat: 51.84748265247729, lng: 20.856669513168328 },
      { lat: 51.847509004438024, lng: 20.855816972804405 },
      { lat: 51.84719923591278, lng: 20.85583546013203 },
      { lat: 51.84718306633476, lng: 20.856042993738004 },
      { lat: 51.846867676181446, lng: 20.856009198438702 },
      { lat: 51.846857166372665, lng: 20.856675000361502 },
      { lat: 51.84701841109362, lng: 20.856671226559524 },
      { lat: 51.84700293278282, lng: 20.8572431365751 },
      { lat: 51.84676982632932, lng: 20.85730640813383 },
      { lat: 51.84665631252204, lng: 20.85714558767773 },
      { lat: 51.84672074825078, lng: 20.85019444146376 },
    ],
  },
  {
    _id: '6b01933c1dc02a368703a022',
    name: 'Orchard …a022',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    areaHectares: 11.19,
    shapeAreaM2: 111939.61,
    shapeLengthM: 1415.33,
    centroid: { lat: 51.84143727168639, long: 20.84772310583566 },
    geometry: [
      { lat: 51.83855836059556, lng: 20.843751566985567 },
      { lat: 51.84042036551417, lng: 20.843860175886586 },
      { lat: 51.84245417785861, lng: 20.84906641230588 },
      { lat: 51.838500160413645, lng: 20.84874176128978 },
    ],
  },
  {
    _id: '6b01933c1dc02a368703a023',
    name: 'Grojec C',
    locationLabel: 'Okolice Grójca · WGS 84 (EPSG:4326)',
    areaHectares: 5.59,
    shapeAreaM2: 55907.07,
    shapeLengthM: 1094.21,
    centroid: { lat: 51.83988434518401, long: 20.851755130713443 },
    geometry: [
      { lat: 51.84061583975802, lng: 20.848913664739563 },
      { lat: 51.84054349433929, lng: 20.851793390471467 },
      { lat: 51.84047526809633, lng: 20.8518005868284 },
      { lat: 51.84044801842261, lng: 20.8547083788363 },
      { lat: 51.83916246900566, lng: 20.854555578450217 },
      { lat: 51.839208540464405, lng: 20.85241833311339 },
      { lat: 51.83927708147489, lng: 20.852391158595776 },
      { lat: 51.83932067194541, lng: 20.84883437127679 },
    ],
  },
];

export function findPlaceholderOrchard(orchardId: ObjectIdString): PlaceholderOrchardCatalogEntry {
  return (
    PLACEHOLDER_ORCHARDS_CATALOG.find((o) => o._id === orchardId) ?? PLACEHOLDER_ORCHARDS_CATALOG[0]
  );
}

const DEMO_ORCHARD_IDS = [
  '6b01933c1dc02a368703a020', // Grojec A
  '6b01933c1dc02a368703a01f', // Grojec B
  '6b01933c1dc02a368703a023', // Grojec C
];

export function getPlaceholderOrchardsList(): OrchardOption[] {
  return DEMO_ORCHARD_IDS.map((id) => findPlaceholderOrchard(id)).map((o) => ({
    _id: o._id,
    name: o.name,
    areaHectares: o.areaHectares,
    centroid: o.centroid,
  }));
}

const PREFS_STORAGE_KEY = 'fup-user-preferences-cache';

export function getPlaceholderUserPreferences(): UserPreferencesDoc {
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<UserPreferencesDoc>;
      const theme =
        parsed.theme === 'Light' || parsed.theme === 'Dark' || parsed.theme === 'OS'
          ? parsed.theme
          : 'OS';
      const lang = parsed.lang === 'pl' ? 'pl' : 'en';
      const activeOrchardId =
        typeof parsed.activeOrchardId === 'string' && DEMO_ORCHARD_IDS.includes(parsed.activeOrchardId)
          ? parsed.activeOrchardId
          : PLACEHOLDER_ORCHARDS_CATALOG[0]._id;
      return { theme, lang, activeOrchardId };
    }
  } catch {
    // ignore storage errors
  }

  return {
    theme: 'OS',
    lang: 'en',
    activeOrchardId: PLACEHOLDER_ORCHARDS_CATALOG[0]._id,
  };
}

export function savePlaceholderUserPreferences(
  patch: Partial<UserPreferencesDoc>,
): UserPreferencesDoc {
  const merged: UserPreferencesDoc = {
    ...getPlaceholderUserPreferences(),
    ...patch,
  };
  try {
    window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(merged));
  } catch {
    // ignore storage errors
  }
  return merged;
}
