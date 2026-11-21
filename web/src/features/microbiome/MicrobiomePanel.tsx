import { useState } from 'react'
import { Choice } from '../../Choice'
import { api, type MicrobeKind, type MicrobiomeSample, type TaxonRank } from '../../api'
import { formatDate, toTime } from '../../format'
import { microbesHref, navigate } from '../../router'
import { useFetch } from '../../useFetch'
import { CompositionView } from './CompositionView'

const KIND_LABEL: Record<MicrobeKind, string> = { bacteria: 'Bacteria and archaea', fungi: 'Fungi' }
const RANKS: { value: TaxonRank; label: string }[] = [
  { value: 'phylum', label: 'Phylum' }, { value: 'class', label: 'Class' }, { value: 'genus', label: 'Genus' },
]
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
const isCaution = (note: string) => note.startsWith('Few DNA reads') || note.startsWith('Processed with')
const dayOfYear = (iso: string) => (toTime(iso) - Date.UTC(Number(iso.slice(0, 4)), 0, 1)) / 86_400_000

/** The sample shown when the route names none: the latest well-sequenced bacterial one, else the latest. */
function defaultSample(list: MicrobiomeSample[]): MicrobiomeSample | undefined {
  const good = list.filter((s) => s.kind === 'bacteria' && !s.low_depth)
  return good.at(-1) ?? list.filter((s) => s.kind === 'bacteria').at(-1) ?? list.at(-1)
}

/** Of `options`, the sample closest in season to `from` (so switching year keeps summer on summer). */
function closestInSeason(options: MicrobiomeSample[], from: MicrobiomeSample): MicrobiomeSample {
  const d = dayOfYear(from.date)
  return options.reduce((best, s) => (Math.abs(dayOfYear(s.date) - d) < Math.abs(dayOfYear(best.date) - d) ? s : best))
}

/** Soil microbiome of one plot: choose bacteria or fungi, a year, a sampling day within it, and the taxonomic
 *  rank; shows the composition of that sample. The chosen sample is in the URL; the rank stays while browsing. */
export function MicrobiomePanel({ plotId, sampleId }: { plotId: string; sampleId: string | null }) {
  const samples = useFetch(`microbiome:${plotId}`, (s) => api.microbiome(plotId, s))
  const [rank, setRank] = useState<TaxonRank>('phylum')
  const [query, setQuery] = useState('') // kept while switching sample, so one taxon can be followed over the years
  const list = samples.data ?? []
  const current = list.find((s) => s.sample_id === sampleId) ?? defaultSample(list)
  const comp = useFetch(current ? `${current.sample_id}|${rank}` : null, (s) => api.composition(current!.sample_id, rank, s))

  if (samples.error) return <p className="message error">Could not load soil microbe data: {samples.error}</p>
  if (samples.loading) return <p className="message">Loading…</p>
  if (!current) return <p className="message">No soil microbe data for this plot.</p>
  if (sampleId && current.sample_id !== sampleId) {
    return <p className="message">Sample {sampleId} was not found for this plot. <a href={microbesHref(plotId)}>Show the latest</a></p>
  }

  const go = (s: MicrobiomeSample) => navigate(microbesHref(plotId, s.sample_id))
  const ofKind = (k: MicrobeKind) => list.filter((s) => s.kind === k)
  const mine = ofKind(current.kind)
  const years = [...new Set(mine.map((s) => s.year))]
  const sameYear = mine.filter((s) => s.year === current.year)
  const switchKind = (k: MicrobeKind) => {
    const options = ofKind(k)
    const inYear = options.filter((s) => s.year === current.year)
    go(inYear.length ? closestInSeason(inYear, current) : options.at(-1)!)
  }

  return (
    <div className="microbiome">
      <div className="controls">
        <Choice label="Organisms">
          {(['bacteria', 'fungi'] as const).map((k) => (
            <button key={k} aria-pressed={current.kind === k} disabled={ofKind(k).length === 0} onClick={() => switchKind(k)}>
              {KIND_LABEL[k]}
            </button>
          ))}
        </Choice>
        <Choice label="Year">
          {years.map((y) => (
            <button key={y} aria-pressed={current.year === y}
              onClick={() => go(closestInSeason(mine.filter((s) => s.year === y), current))}>{y}</button>
          ))}
        </Choice>
        {sameYear.length > 1 && (
          <Choice label="Sampled on">
            {sameYear.map((s) => (
              <button key={s.sample_id} aria-pressed={s.sample_id === current.sample_id} onClick={() => go(s)}
                title={s.low_depth ? 'Few DNA reads: compare with care' : undefined}>
                {formatDate(s.date)}{s.low_depth && <span className="few"> · few reads</span>}
              </button>
            ))}
          </Choice>
        )}
        <Choice label="Group by">
          {RANKS.map((r) => (
            <button key={r.value} aria-pressed={rank === r.value} onClick={() => setRank(r.value)}>{r.label}</button>
          ))}
        </Choice>
      </div>

      <div className="chart-head">
        <div>
          <h2>{KIND_LABEL[current.kind]} in the soil, {formatDate(current.date)}</h2>
          <p className="chart-sub">
            Share of DNA reads per {rank} · {compact.format(current.reads)} reads from {current.n_cores} soil {current.n_cores === 1 ? 'core' : 'cores'}
            {current.low_depth && <span className="badge caution">Few reads</span>}
          </p>
        </div>
      </div>
      {comp.error ? (
        <p className="message error">Could not load the composition: {comp.error}</p>
      ) : !comp.data ? (
        <p className="message">Loading…</p>
      ) : (
        <>
          {comp.data.notes.length > 0 && (
            <div className={`notes ${comp.data.notes.some(isCaution) ? 'has-caution' : ''}`} role="note">
              <b className="notes-title">About this sample</b>
              <ul>{comp.data.notes.map((n) => <li key={n} className={isCaution(n) ? 'caution' : ''}>{n}</li>)}</ul>
            </div>
          )}
          <CompositionView data={comp.data} query={query} onQuery={setQuery} />
        </>
      )}
    </div>
  )
}
