import { api, type FunctionProfile, type FunctionSample, type FunctionTheme, type Fungi, type MeasuredSoil, type Pathway, type PresenceStatus } from '../../api'
import { formatDate } from '../../format'
import { functionsHref, navigate } from '../../router'
import { useFetch } from '../../useFetch'
import { CardLegend, DecisionCards } from './DecisionCards'

const THEMES: { theme: FunctionTheme; title: string }[] = [
  { theme: 'nitrogen', title: 'Nitrogen' },
  { theme: 'phosphorus', title: 'Phosphorus' },
  { theme: 'plant', title: 'Plant health' },
  { theme: 'pressure', title: 'Chemical pressure' },
]
const PRESENCE: Record<PresenceStatus, string> = {
  found: 'found', trace: 'trace', not_found: 'not found', too_few_genes: 'too few genes',
}
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

/** The sample shown when the route names none: the latest deep one, else the latest. */
function defaultSample(list: FunctionSample[]): FunctionSample | undefined {
  return list.filter((s) => s.deep_enough).at(-1) ?? list.at(-1)
}

/** The story one soil sample tells, on its own: what its bacteria, archaea and fungi are equipped to do and what
 *  NEON measured in it, as cards ordered by how much they can be trusted. No comparison with other plots. */
export function FunctionsPanel({ plotId, sampleId }: { plotId: string; sampleId: string | null }) {
  const samples = useFetch(`functions:${plotId}`, (s) => api.functionSamples(plotId, s))
  const list = samples.data ?? []
  const current = list.find((s) => s.sample_id === sampleId) ?? defaultSample(list)
  const prof = useFetch(current ? `profile:${current.sample_id}` : null, (s) => api.functionProfile(current!.sample_id, s))

  if (samples.error) return <p className="message error">Could not load soil function data: {samples.error}</p>
  if (samples.loading) return <p className="message">Loading…</p>
  if (!current) return <p className="message">No gene data (metagenomes) for this plot.</p>
  if (sampleId && current.sample_id !== sampleId) {
    return <p className="message">Sample {sampleId} was not found for this plot. <a href={functionsHref(plotId)}>Show the latest</a></p>
  }

  return (
    <div className="functions">
      <div className="controls">
        <div className="choice" role="group" aria-label="Sampled on">
          <span className="choice-label">Sampled on</span>
          <div className="segmented">
            {list.map((s) => (
              <button key={s.sample_id} aria-pressed={s.sample_id === current.sample_id}
                onClick={() => navigate(functionsHref(plotId, s.sample_id))}
                title={`${s.n_genes.toLocaleString('en')} genes`}>
                {formatDate(s.date)}{!s.deep_enough && <span className="few"> · few genes</span>}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="chart-head">
        <div>
          <h2>What this soil sample tells, {formatDate(current.date)}</h2>
          <p className="chart-sub">
            {compact.format(current.n_genes)} genes from the soil DNA, fungi from the same soil and NEON's measurements
            {!current.deep_enough && <span className="badge caution">Few genes</span>}
          </p>
        </div>
      </div>
      {prof.error ? (
        <p className="message error">Could not load the profile: {prof.error}</p>
      ) : !prof.data ? (
        <p className="message">Loading…</p>
      ) : (
        <Profile data={prof.data} />
      )}
    </div>
  )
}

/** Cards first (most trustworthy first, as ordered by the API), then the underlying detail folded away. */
function Profile({ data }: { data: FunctionProfile }) {
  return (
    <>
      <section className="fn-block">
        <CardLegend />
        <DecisionCards cards={data.cards} wide />
      </section>
      <details className="fn-details">
        <summary>Details: nitrogen pathways, fungal roles, measurements and genes</summary>
        <div className={`notes ${data.deep_enough ? '' : 'has-caution'}`} role="note">
          <b className="notes-title">How to read this</b>
          <ul>{data.notes.map((n) => <li key={n} className={n.startsWith('Too few genes') ? 'caution' : ''}>{n}</li>)}</ul>
        </div>
        <Pathways pathways={data.pathways} />
        {data.fungi && <FungalRoles fungi={data.fungi} />}
        <Measured m={data.measured} />
        <section className="fn-theme">
          <h3>All genes in the panel</h3>
          {THEMES.map(({ theme, title }) => {
            const groups = data.groups.filter((g) => g.theme === theme)
            if (!groups.length) return null
            return (
              <div key={theme} className="fn-genes-block">
                <h4>{title}</h4>
                <table className="fn-gene-table">
                  <tbody>
                    {groups.flatMap((g) => g.genes.map((x, i) => (
                      <tr key={`${g.group}-${x.gene}`}>
                        <th>{i === 0 ? g.title : ''}</th>
                        <td><b>{x.gene}</b> <span className="muted">{x.ko}</span></td>
                        <td className="num">{x.count.toLocaleString('en')}</td>
                        <td className="caveat">{x.caveat ?? ''}</td>
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
            )
          })}
        </section>
      </details>
    </>
  )
}

/** Each nitrogen pathway as its KEGG steps, marked found / trace / not found, with the gene copies per step. */
function Pathways({ pathways }: { pathways: Pathway[] }) {
  return (
    <section className="fn-theme">
      <h3>Nitrogen pathways in this sample</h3>
      {pathways.map((p) => (
        <div key={p.name} className="pw">
          <div className="pw-head">
            <b>{p.name}</b> <span className="muted">KEGG {p.kegg_module}</span>
            {p.complete && <span className="pw-complete">all steps found</span>}
          </div>
          <ol className="pw-steps">
            {p.steps.map((s) => (
              <li key={s.step} className={s.status} title={s.genes.join(', ')}>
                <span className="pw-step">{s.step}</span>
                <span className="pw-copies">{s.status === 'too_few_genes' ? '–' : `${s.copies.toLocaleString('en')} copies`} · {PRESENCE[s.status]}</span>
              </li>
            ))}
          </ol>
          {p.note && <p className="pw-note">{p.note}</p>}
        </div>
      ))}
    </section>
  )
}

/** Share of the fungal DNA (with a genus name) per ecological role, from FUNGuild. */
function FungalRoles({ fungi }: { fungi: Fungi }) {
  return (
    <section className="fn-theme">
      <h3>Fungal roles ({fungi.same_cores ? 'same soil cores' : `NEON visit ${formatDate(fungi.date)}`})</h3>
      <table className="fn-gene-table">
        <tbody>
          {fungi.roles.map((r) => (
            <tr key={r.role}>
              <th>{r.label}</th>
              <td className="num">{r.pct >= 0.5 ? `${r.pct.toFixed(0)}%` : r.pct >= 0.05 ? `${r.pct.toFixed(1)}%` : '<0.1%'}</td>
              <td className="caveat">{r.top.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="pw-note">
        Share of fungal DNA with a genus name ({fungi.named_pct.toFixed(0)}% of fungal reads{fungi.reads ? `, ${fungi.reads.toLocaleString('en')} reads` : ''}).
        Roles are the typical role of each genus in FUNGuild, not of every species in it.
      </p>
    </section>
  )
}

function Measured({ m }: { m: MeasuredSoil | null }) {
  if (!m) return <p className="message">NEON did not measure this soil within a week of the sample.</p>
  const rows: [string, number | null, string][] = [
    ['Ammonium', m.ammonium_n_mgkg, 'mg N per kg soil'],
    ['Nitrate', m.nitrate_n_mgkg, 'mg N per kg soil'],
    ['Net N mineralisation', m.net_n_min_mgkg_d, 'mg N per kg per day (negative: microbes took N up)'],
    ['Net nitrification', m.net_nitrif_mgkg_d, 'mg N per kg per day'],
    ['pH (water)', m.ph_water, ''],
    ['Organic carbon', m.organic_c_pct, '%'],
    ['Total nitrogen', m.total_n_pct, '%'],
    ['C:N ratio', m.cn_ratio, ''],
    ['Soil moisture', m.soil_moisture, 'g water per g dry soil'],
  ]
  return (
    <section className="fn-theme">
      <h3>Measured in this soil ({formatDate(m.date)})</h3>
      <table className="fn-measured">
        <tbody>
          {rows.filter(([, v]) => v !== null).map(([k, v, u]) => (
            <tr key={k}><th>{k}</th><td>{v!.toFixed(2)}</td><td className="unit">{u}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
