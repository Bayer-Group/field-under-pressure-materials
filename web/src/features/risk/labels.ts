import type { CropStatus } from '../../api'

/** 1 -> '1st', 2 -> '2nd', 3 -> '3rd', 11 -> '11th', 22 -> '22nd'. */
export function ordinal(n: number): string {
  const r100 = n % 100
  if (r100 >= 11 && r100 <= 13) return `${n}th`
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`
}

/** Badge text for crops that could not be given an index (crop and reason labels come from the backend). */
export const STATUS_LABEL: Record<Exclude<CropStatus, 'ok'>, string> = {
  no_knowledge: 'No host records',
  insufficient_depth: 'Too few reads',
  no_scored_genera: 'No pathogens scored',
}

export const rankText = (rank: number, nPeers: number) =>
  `${rank === 1 ? 'Highest' : `${ordinal(rank)} highest`} of ${nPeers} plots`

export const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
