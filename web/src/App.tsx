import { Explorer } from './Explorer'
import { EventDetails } from './features/events/EventDetails'
import { useRoute } from './router'

export function App() {
  const route = useRoute()
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand" aria-label="Terranos, all plots">
          <img src="/terranos.png" alt="Terranos" className="brand-logo" />
        </a>
        <span className="tagline">Satellite greenness, aerial photos and soil microbes for each sampled plot</span>
      </header>
      {route.page === 'event' ? <EventDetails eventId={route.eventId} /> : <Explorer plotId={route.plotId} tab={route.tab} sampleId={route.sampleId} unit={route.unit} crop={route.crop} />}
    </div>
  )
}
