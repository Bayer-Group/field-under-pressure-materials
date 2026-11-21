import { useCallback, useEffect, useState } from 'react'
import { ErrorBoundary } from './ErrorBoundary'
import { Explorer } from './Explorer'
import { EventDetails } from './features/events/EventDetails'
import { Landing, landingWanted } from './Landing'
import { useRoute, type PlotTab, type Route } from './router'

const TAB_TITLE: Record<PlotTab, string> = {
  greenness: 'Greenness', microbes: 'Soil microbes', functions: 'Soil characteristics', risk: 'Crop disease risk', plan: 'Treatment plan',
}

/** Browser tab title of a route, so history entries and bookmarks can be told apart. */
function pageTitle(route: Route): string {
  if (route.page === 'event') return `Visit ${route.eventId} · Terranos`
  return route.plotId ? `${route.plotId} · ${TAB_TITLE[route.tab]} · Terranos` : 'Terranos'
}

export function App() {
  const route = useRoute()
  const title = pageTitle(route)
  useEffect(() => { document.title = title }, [title])
  // Decided once, on the first render: a fresh load of the overview gets the landing screen, deep links do not.
  const [landing, setLanding] = useState(landingWanted)
  const closeLanding = useCallback(() => setLanding(false), [])
  return (
    <>
      {landing && <Landing onDone={closeLanding} />}
      <div className="app" inert={landing}>
        <header className="topbar">
          <a href="#/" className="brand" aria-label="Terranos, all plots">
            <img src={`${import.meta.env.BASE_URL}terranos.png`} alt="Terranos" className="brand-logo" />
          </a>
          <span className="tagline">Satellite greenness, soil microbes and crop disease risk for each sampled plot</span>
          {import.meta.env.VITE_STATIC === '1' && <span className="static-badge">Static demo · light mode (5 plots)</span>}
        </header>
        <ErrorBoundary key={route.page}>
          {route.page === 'event' ? <EventDetails eventId={route.eventId} /> : <Explorer plotId={route.plotId} tab={route.tab} sampleId={route.sampleId} unit={route.unit} crop={route.crop} view={route.view} />}
        </ErrorBoundary>
      </div>
    </>
  )
}
