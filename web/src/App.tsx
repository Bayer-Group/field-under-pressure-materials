import { Explorer } from './Explorer'
import { EventDetails } from './features/events/EventDetails'
import { useRoute } from './router'

export function App() {
  const route = useRoute()
  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">Field explorer</a>
      </header>
      {route.page === 'event' ? <EventDetails eventId={route.eventId} /> : <Explorer plotId={route.plotId} tab={route.tab} sampleId={route.sampleId} />}
    </div>
  )
}
