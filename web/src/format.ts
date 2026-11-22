const DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const MONTH = new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })

/** '2017-08-07' -> '7 Aug 2017' (or 'Aug 2017' when only the month is known). */
export function formatDate(iso: string, monthOnly = false): string {
  return (monthOnly ? MONTH : DAY).format(new Date(iso + 'T00:00:00Z'))
}

export const toTime = (iso: string) => Date.parse(iso + 'T00:00:00Z')

/** Whole days from `a` to `b` (positive when b is later). */
export const daysBetween = (a: string, b: string) => Math.round((toTime(b) - toTime(a)) / 86_400_000)
