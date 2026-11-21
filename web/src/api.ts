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

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`/api${path}`, { signal })
  if (!r.ok) {
    const detail = await r.json().then((b) => b.detail, () => null)
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${r.status})`)
  }
  return r.json()
}

const id = encodeURIComponent

export const api = {
  plots: (s?: AbortSignal) => get<Plot[]>('/plots', s),
  greenness: (plotId: string, s?: AbortSignal) => get<GreennessPoint[]>(`/plots/${id(plotId)}/greenness`, s),
  plotEvents: (plotId: string, s?: AbortSignal) => get<EventSummary[]>(`/plots/${id(plotId)}/events`, s),
  aerial: (plotId: string, s?: AbortSignal) => get<AerialPhoto[]>(`/plots/${id(plotId)}/aerial`, s),
  greennessMaps: (plotId: string, s?: AbortSignal) => get<GreennessMap[]>(`/plots/${id(plotId)}/greenness-maps`, s),
  greennessAt: (mapId: string, lat: number, lon: number) =>
    get<{ ndvi: number | null }>(`/greenness-maps/${id(mapId)}/value?lat=${lat}&lon=${lon}`),
  microbiome: (plotId: string, s?: AbortSignal) => get<MicrobiomeSample[]>(`/plots/${id(plotId)}/microbiome`, s),
  composition: (sampleId: string, rank: TaxonRank, s?: AbortSignal) =>
    get<Composition>(`/microbiome/${id(sampleId)}?rank=${rank}`, s),
  event: (eventId: string, s?: AbortSignal) => get<EventDetail>(`/events/${id(eventId)}`, s),
}

export const getCropRiskUnits = (plotId: string, s?: AbortSignal) => get<RiskUnitRef[]>(`/plots/${id(plotId)}/crop-risk`, s)
export const getCropRisk = (plotId: string, unit: string, s?: AbortSignal) =>
  get<PlotCropRisk>(`/plots/${id(plotId)}/crop-risk/${id(unit)}`, s)
export const getCropContributions = (plotId: string, unit: string, crop: string, s?: AbortSignal) =>
  get<CropContributions>(`/plots/${id(plotId)}/crop-risk/${id(unit)}/${id(crop)}`, s)
