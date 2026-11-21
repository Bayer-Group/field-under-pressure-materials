// Typed client for the local API (src/cropfit/api.py). One function per endpoint; the types mirror the
// response models there. New backend features get a type and a function here, nothing else talks to fetch.

export interface Plot {
  plot_id: string
  site: string
  lat: number
  lon: number
  half_m: number
}

export interface GreennessPoint {
  date: string // YYYY-MM-DD
  ndvi: number
}

export interface EventSummary {
  event_id: string
  date: string
}

export interface EventDetail extends EventSummary {
  plot_id: string
  site: string
  sampled: string[]
}

export interface AerialPhoto {
  photo_id: string
  date: string
  month_only: boolean
  source: string
  bounds: [[number, number], [number, number]] // [[south, west], [north, east]]
  url: string
}

export interface GreennessMap {
  map_id: string
  date: string
  bounds: [[number, number], [number, number]]
  url: string
}

export type MicrobeKind = 'bacteria' | 'fungi'
export type TaxonRank = 'phylum' | 'class' | 'genus'

export interface MicrobiomeSample {
  sample_id: string
  kind: MicrobeKind
  date: string
  year: number
  reads: number // reads the composition is computed from
  n_cores: number
  low_depth: boolean
}

export interface Taxon {
  name: string
  phylum: string | null // used for colour; the taxon itself at phylum rank
  pct: number // 0-100, share of the group's reads
  reads: number
  description?: string | null // genus rank only: plain-language hover text, else null
}

export interface Composition {
  sample_id: string
  kind: MicrobeKind
  plot_id: string
  date: string
  rank: TaxonRank
  reads: number
  n_taxa: number
  taxa: Taxon[] // every named taxon, largest first
  other_pct: number // named taxa beyond `taxa` (0 unless the API was asked for the top ones only)
  unassigned_pct: number // reads with no name at this rank
  notes: string[]
}

export type RiskMethod = 'current' | 'older'
export type CropStatus = 'ok' | 'no_knowledge' | 'insufficient_depth' | 'no_scored_genera'

export interface RiskUnitRef {
  unit: string // e.g. '2016-002'
  year: number
  product: string
  method: RiskMethod
  method_label: string
  collect_dates: string[]
  total_reads: number
  n_cores: number
  low_depth: boolean
}

export interface RiskPeer {
  plot_id: string
  risk_index: number
}

export interface CropRiskRow {
  crop: string
  label: string
  status: CropStatus
  risk_index: number | null
  from_detected: number | null
  from_not_detected: number | null
  rank: number | null // 1 = highest among peers
  n_peers: number
  n_peers_too_shallow: number
  percentile: number | null // 0-100
  peers: RiskPeer[] // includes this plot, sorted descending
  top_genus: string | null
  n_genera_contributing: number
  n_genera_not_detected: number
  small_reference: boolean
  same_as: string | null
}

export interface SkippedGenus {
  genus: string | null
  reads: number | null
  detail: string | null
}

export interface SkippedGroup {
  reason: string
  label: string
  n: number
  genera: SkippedGenus[]
  more: number
}

export interface KbSource {
  name: string
  source_version: string | null
  retrieved_utc: string | null
  url: string | null
}

export interface PlotCropRisk {
  plot_id: string
  site: string
  unit: string
  year: number
  product: string
  method: RiskMethod
  method_label: string
  collect_dates: string[]
  total_reads: number
  n_cores: number
  low_depth: boolean
  n_units_in_group: number
  crops: CropRiskRow[]
  skipped: SkippedGroup[]
  caveats: string[]
  notes: string[]
  kb: KbSource[]
  parameters: Record<string, number>
  index_type: string
}

export interface Contribution {
  genus: string
  members: string[]
  detected: boolean
  reads: number
  share_pct: number
  a: number
  percentile: number
  reference_n: number
  small_reference: boolean
  h: number
  n_species_on_crop: number
  n_species_documented: number
  species_on_crop: string[]
  n_species_more: number
  n_records_on_crop: number
  lifestyle: string | null
  passed_by: string | null
  contribution: number
}

export interface CropContributions {
  plot_id: string
  unit: string
  crop: string
  label: string
  row: CropRiskRow
  contributions: Contribution[] // largest first
  n_scored_zero_h: number
}

export interface FunctionSample {
  sample_id: string // same ids as the soil microbes view
  date: string
  year: number
  n_genes: number // genes assembled and annotated
  deep_enough: boolean // enough genes to read absences and balances at all
}

export type FunctionTheme = 'nitrogen' | 'phosphorus' | 'plant' | 'pressure'
export type PresenceStatus = 'found' | 'trace' | 'not_found' | 'too_few_genes'

export interface FunctionGroup {
  group: string
  title: string
  meaning: string
  theme: FunctionTheme
  status: PresenceStatus
  genes: { gene: string; ko: string; count: number; caveat: string | null }[]
  term_id?: string | null
}

export interface Pathway {
  name: string
  kegg_module: string
  steps: { step: string; genes: string[]; copies: number; status: PresenceStatus }[]
  complete: boolean
  note: string | null
  term_id?: string | null
}

export interface Fungi {
  date: string
  same_cores: boolean // from exactly the soil cores of the gene data
  reads: number | null
  named_pct: number // share of fungal reads with a genus name
  roles: { role: string; label: string; pct: number; top: string[]; term_id?: string | null }[]
}

export interface MeasuredSoil {
  date: string
  ammonium_n_mgkg: number | null
  nitrate_n_mgkg: number | null
  net_n_min_mgkg_d: number | null
  net_nitrif_mgkg_d: number | null
  ph_water: number | null
  organic_c_pct: number | null
  total_n_pct: number | null
  cn_ratio: number | null
  soil_moisture: number | null // g water per g dry soil
}

export type CardStatus = 'good' | 'watch' | 'act' | 'notice' | 'info' | 'unknown'

export interface Implication {
  kind: 'upside' | 'risk' | 'neutral'
  text: string
}

export interface DecisionCard {
  card: string
  title: string
  status: CardStatus // good/watch/act: measured threshold; notice: a stated rule on this sample; info: nothing stands out
  headline: string // one short line for the card face
  flag: string | null // why the card is coloured, when it is
  finding: string // what is there
  implications: Implication[] // what it can mean: possible upsides and risks
  basis: 'measured' | 'genes' | 'fungi' | 'names'
  confidence: 'high' | 'medium' | 'low'
  evidence: string[]
  carrier_terms?: string[] // term ids to look up in FunctionProfile.carriers
}

export interface FunctionProfile {
  sample_id: string
  plot_id: string
  date: string
  n_genes: number
  deep_enough: boolean
  cards: DecisionCard[] // most trustworthy first
  pathways: Pathway[]
  fungi: Fungi | null
  groups: FunctionGroup[]
  measured: MeasuredSoil | null
  notes: string[]
  carriers?: Carriers[]
}

export type SummaryClassId = 'useful' | 'mixed' | 'harmful' | 'context' | 'background' | 'unknown'
export type RolePolarity = 'useful' | 'harmful' | 'context' | 'background' | 'unknown'
export type RoleConfidence = 'high' | 'medium' | 'low'
export type RoleEvidence = 'curated_db' | 'well_known_genus' | 'some_species' | 'inferred'

export interface RoleSummary {
  class_id: SummaryClassId
  label: string
  pct: number // share of the group's reads
  pct_of_named: number // share of reads with a genus name; the six add up to 100
  n_genera: number
  top: string[]
}

export interface RoleGenus {
  name: string
  domain: string | null
  phylum: string | null
  pct: number
  reads: number
  term_id: string
  confidence: RoleConfidence
  evidence: RoleEvidence
  source: string // funguild | fungaltraits | llm:<model>[+reviewed] | unannotated
  species_examples: string[]
  note: string | null
  summary_class: SummaryClassId
  description: string | null
}

export interface RoleTerm {
  term_id: string
  parent_id: string | null
  label: string
  description: string
  polarity: RolePolarity
  depth: number
  ko_groups: string[]
  pct: number // genera with this role or a sub-role; terms overlap
  n_genera: number
  genera: RoleGenus[] // largest first, capped
  other_genera_pct: number
}

export interface RoleComposition {
  sample_id: string
  kind: MicrobeKind
  plot_id: string
  date: string
  reads: number
  n_genera: number
  summary: RoleSummary[]
  terms: RoleTerm[]
  annotated_pct: number
  unassigned_pct: number
  sources: string[]
  notes: string[]
}

export type Agreement = 'both' | 'genes_only' | 'names_only' | 'neither' | 'unknown'

export interface CarrierGenus {
  name: string
  pct: number // share of classified bacterial + archaeal reads
  term_id: string
  confidence: 'high' | 'medium'
  evidence: string
  species_examples: string[]
  description: string | null
}

export interface Carriers {
  term_id: string
  label: string
  ko_groups: string[]
  pct: number
  n_genera: number
  top: CarrierGenus[]
  genes: PresenceStatus
  agreement: Agreement
  agreement_text: string
}

const STATIC = import.meta.env.VITE_STATIC === '1'

declare global {
  interface Window {
    __BAKED__?: Record<string, unknown>
  }
}

// Static mode: data is pre-baked into data/<key>.js scripts (fetch of file:// is blocked).
const bakedKey = (path: string) => path.replace(/\//g, '__').replace(/\?/g, '~').replace(/=/g, '-').replace(/&/g, '+')
const bakedCache = new Map<string, Promise<unknown>>()

function loadBaked(path: string): Promise<unknown> {
  const key = bakedKey(path)
  let p = bakedCache.get(key)
  if (!p) {
    p = new Promise((resolve, reject) => {
      const fail = () => reject(new Error('Not available in the static demo'))
      const tag = document.createElement('script')
      tag.src = `data/${key}.js`
      tag.async = true
      tag.onload = () => {
        const v = window.__BAKED__?.[path]
        if (v === undefined) fail()
        else resolve(v)
        tag.remove()
      }
      tag.onerror = () => {
        tag.remove()
        fail()
      }
      document.head.appendChild(tag)
    })
    bakedCache.set(key, p)
  }
  return p
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (STATIC) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const data = await loadBaked(path)
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return data as T
  }
  const r = await fetch(`/api${path}`, { signal })
  if (!r.ok) {
    const detail = await r.json().then((b) => b.detail, () => null)
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${r.status})`)
  }
  return r.json()
}

interface BakedGrid { s: number; w: number; n: number; e: number; width: number; height: number; codes: string }
const gridBytes = new Map<string, Uint8Array>()
let decodeTable: Promise<(number | null)[]> | null = null
const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))

async function staticGreennessAt(mapId: string, lat: number, lon: number): Promise<{ ndvi: number | null }> {
  const grid = (await loadBaked(`/greenness-maps/${encodeURIComponent(mapId)}/grid`)) as BakedGrid
  decodeTable ??= (loadBaked('/ndvi-decode') as Promise<{ values: (number | null)[] }>).then((d) => d.values)
  const values = await decodeTable
  const { s, w, n, e, width, height } = grid
  if (lat < s || lat > n || lon < w || lon > e) return { ndvi: null }
  let bytes = gridBytes.get(mapId)
  if (!bytes) {
    bytes = Uint8Array.from(atob(grid.codes), (c) => c.charCodeAt(0))
    gridBytes.set(mapId, bytes)
  }
  const col = Math.min(width - 1, Math.max(0, Math.floor(((lon - w) / (e - w)) * width)))
  const row = Math.min(height - 1, Math.max(0, Math.floor(((mercY(n) - mercY(lat)) / (mercY(n) - mercY(s))) * height)))
  const v = values[bytes[row * width + col]]
  return { ndvi: v == null ? null : Math.round(v * 100) / 100 }
}

const id = encodeURIComponent

export const api = {
  plots: (s?: AbortSignal) => get<Plot[]>('/plots', s),
  greenness: (plotId: string, s?: AbortSignal) => get<GreennessPoint[]>(`/plots/${id(plotId)}/greenness`, s),
  plotEvents: (plotId: string, s?: AbortSignal) => get<EventSummary[]>(`/plots/${id(plotId)}/events`, s),
  aerial: (plotId: string, s?: AbortSignal) => get<AerialPhoto[]>(`/plots/${id(plotId)}/aerial`, s),
  greennessMaps: (plotId: string, s?: AbortSignal) => get<GreennessMap[]>(`/plots/${id(plotId)}/greenness-maps`, s),
  greennessAt: (mapId: string, lat: number, lon: number): Promise<{ ndvi: number | null }> =>
    STATIC ? staticGreennessAt(mapId, lat, lon) : get<{ ndvi: number | null }>(`/greenness-maps/${id(mapId)}/value?lat=${lat}&lon=${lon}`),
  microbiome: (plotId: string, s?: AbortSignal) => get<MicrobiomeSample[]>(`/plots/${id(plotId)}/microbiome`, s),
  composition: (sampleId: string, rank: TaxonRank, s?: AbortSignal) =>
    get<Composition>(`/microbiome/${id(sampleId)}?rank=${rank}`, s),
  roles: (sampleId: string, s?: AbortSignal) => get<RoleComposition>(`/microbiome/${id(sampleId)}/roles`, s),
  event: (eventId: string, s?: AbortSignal) => get<EventDetail>(`/events/${id(eventId)}`, s),
  functionSamples: (plotId: string, s?: AbortSignal) => get<FunctionSample[]>(`/plots/${id(plotId)}/functions`, s),
  functionProfile: (sampleId: string, s?: AbortSignal) => get<FunctionProfile>(`/functions/${id(sampleId)}`, s),
}

export type TestTrigger = 'resolve_species' | 'confirm_detection' | 'blind_spot' | 'sampling'

export interface TestSuggestion {
  test_id: string
  kind: string
  trigger: TestTrigger
  trigger_label: string
  priority: number // 0-1, only orders the list
  genus: string | null
  target: string | null
  disease: string | null
  method: string
  sample: string | null
  tells_you: string | null
  reason: string
  inoculum: string | null
  source: string | null
  verified: boolean
}

export interface FollowupTests {
  plot_id: string
  unit: string
  crop: string
  label: string
  suggestions: TestSuggestion[] // most useful first
  note: string
}

export type ProductTrigger = 'pathogen_high' | 'confirm_first' | 'site_favoured' | 'soil_signal'
export type ProductTiming = 'before_planting' | 'during_growth'

export interface ProductRecommendation {
  product_id: string
  category: string // fungicide_seed | fungicide_foliar | biocontrol | fertiliser | inhibitor | inoculant | amendment | no_product | caution | note
  category_label: string
  product_class: string
  timing: ProductTiming
  stage: string | null
  trigger: ProductTrigger
  trigger_label: string
  priority: number // 0-1, only orders the list
  basis: 'measured' | 'genes' | 'fungi' | 'site' | 'history'
  confidence: string
  genus: string | null
  reason: string
  works_because: string | null
  caution: string | null
  confirm_with: { test_id: string; name: string }[] // follow-up tests that would confirm the finding
  source: string | null
  verified: boolean
}

export interface ProductPlan {
  plot_id: string
  unit: string
  crop: string
  label: string
  recommendations: ProductRecommendation[] // highest priority first
  unchecked: { product_id: string; product_class: string }[] // soil rules whose values are missing
  sources: string[]
  note: string
}

export const getProductPlan = (plotId: string, unit: string, crop: string, s?: AbortSignal) =>
  get<ProductPlan>(`/plots/${id(plotId)}/crop-risk/${id(unit)}/${id(crop)}/products`, s)
export const getCropRiskUnits = (plotId: string, s?: AbortSignal) => get<RiskUnitRef[]>(`/plots/${id(plotId)}/crop-risk`, s)
export const getCropRisk = (plotId: string, unit: string, s?: AbortSignal) =>
  get<PlotCropRisk>(`/plots/${id(plotId)}/crop-risk/${id(unit)}`, s)
export const getCropContributions = (plotId: string, unit: string, crop: string, s?: AbortSignal) =>
  get<CropContributions>(`/plots/${id(plotId)}/crop-risk/${id(unit)}/${id(crop)}`, s)
export const getFollowupTests = (plotId: string, unit: string, crop: string, s?: AbortSignal) =>
  get<FollowupTests>(`/plots/${id(plotId)}/crop-risk/${id(unit)}/${id(crop)}/tests`, s)
