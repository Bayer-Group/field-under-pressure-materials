import type { Plot } from './api'

// Readable names for the NEON site codes. A site missing here is shown by its code.
const SITE_NAMES: Record<string, string> = {
  KONA: 'Konza Prairie, Kansas',
  STER: 'North Sterling, Colorado',
}

export const siteName = (site: string) => SITE_NAMES[site] ?? site

/** Plots grouped by site, sites and plots in alphabetical order. */
export function bySite(plots: Plot[]): { site: string; plots: Plot[] }[] {
  const groups = new Map<string, Plot[]>()
  for (const p of [...plots].sort((a, b) => a.plot_id.localeCompare(b.plot_id))) {
    groups.set(p.site, [...(groups.get(p.site) ?? []), p])
  }
  return [...groups].sort(([a], [b]) => a.localeCompare(b)).map(([site, plots]) => ({ site, plots }))
}

/** 'KONA_001' -> '001': the part of the id after the site code. */
export const shortId = (p: Plot) => (p.plot_id.startsWith(p.site + '_') ? p.plot_id.slice(p.site.length + 1) : p.plot_id)

export const formatLatLon = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`
