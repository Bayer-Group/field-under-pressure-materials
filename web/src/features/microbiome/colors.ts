import type { MicrobeKind } from '../../api'

// Colour follows the phylum, so a phylum keeps its colour across plots, years and ranks. The slots are the
// validated categorical palette in its fixed order (dataviz reference palette, light mode); phyla are listed by
// how common they are across all samples here. Every other phylum, and the "other" fold, is neutral grey.
const SLOTS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
const DARK_INK_ON = new Set(['#eda100']) // yellow takes near-black text; every other slot white

const PHYLA: Record<MicrobeKind, string[]> = {
  bacteria: ['Actinobacteria', 'Proteobacteria', 'Firmicutes', 'Gemmatimonadetes', 'Acidobacteria',
    'Planctomycetes', 'Bacteroidetes', 'Cyanobacteria'],
  fungi: ['Ascomycota', 'Basidiomycota', 'Mortierellomycota', 'Chytridiomycota', 'Glomeromycota',
    'Kickxellomycota', 'Mucoromycota', 'Olpidiomycota'],
}

export const OTHER = '#a9a8a1'
export const UNASSIGNED = '#e1e0d9'

export function phylumColor(kind: MicrobeKind, phylum: string | null): string {
  const i = phylum ? PHYLA[kind].indexOf(phylum) : -1
  return i < 0 ? OTHER : SLOTS[i]
}

/** Text colour inside a fill of `bg`. */
export const inkOn = (bg: string) => (bg === OTHER || bg === UNASSIGNED || DARK_INK_ON.has(bg) ? '#0b0b0b' : '#ffffff')

export const hasOwnColor = (kind: MicrobeKind, phylum: string | null) => phylumColor(kind, phylum) !== OTHER
