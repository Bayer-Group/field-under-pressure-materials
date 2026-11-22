import { useEffect, useState } from 'react'

export type Loadable<T> = { data: T | null; error: string | null; loading: boolean }

/** Runs `load` whenever `key` changes; a null key means "nothing to load". Stale answers are dropped. */
export function useFetch<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): Loadable<T> {
  const [state, setState] = useState<Loadable<T> & { key: string | null }>({ key, data: null, error: null, loading: key !== null })
  useEffect(() => {
    if (key === null) return
    const ctl = new AbortController()
    load(ctl.signal).then(
      (data) => setState({ key, data, error: null, loading: false }),
      (e: Error) => { if (!ctl.signal.aborted) setState({ key, data: null, error: e.message, loading: false }) },
    )
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  // Until the answer for the current key arrives, do not show the previous key's data.
  return state.key === key ? state : { data: null, error: null, loading: key !== null }
}
