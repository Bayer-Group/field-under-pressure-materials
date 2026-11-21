import { Explorer } from './Explorer'
import { EventDetails } from './features/events/EventDetails'
import { useRoute } from './router'

export function App() {
  const route = useRoute()
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15" fill="currentColor" opacity="0.18" />
            <path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15M5 19 14 10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Field explorer
        </a>
        <span className="tagline">Satellite greenness, aerial photos and soil microbes for each sampled plot</span>
      </header>
      {route.page === 'event' ? <EventDetails eventId={route.eventId} /> : <Explorer plotId={route.plotId} tab={route.tab} sampleId={route.sampleId} unit={route.unit} crop={route.crop} view={route.view} />}
    </div>
  )
}
