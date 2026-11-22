import type { NavSectionId } from '../components/layout/Sidebar';

const STORAGE_PREFIX = 'sage-page-prefs:';

export const SECTION_PATHS: Record<NavSectionId, string> = {
  dashboard: '/dashboard',
  'row-editor': '/row-editor',
  analytics: '/analytics',
  calendar: '/calendar',
};

const PATH_TO_SECTION: Record<string, NavSectionId> = {
  '/dashboard': 'dashboard',
  '/row-editor': 'row-editor',
  '/analytics': 'analytics',
  '/calendar': 'calendar',
};

export function sectionFromPathname(pathname: string): NavSectionId | null {
  const normalized = pathname.replace(/\/+$/, '').toLowerCase() || '/';
  return PATH_TO_SECTION[normalized] ?? null;
}

export function pathForSection(section: NavSectionId): string {
  return SECTION_PATHS[section];
}

export function readPagePref<T>(pageKey: string, fallback: T, validate?: (value: unknown) => value is T): T {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${pageKey}`);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (validate) {
      return validate(parsed) ? parsed : fallback;
    }
    return parsed as T;
  } catch {
    return fallback;
  }
}

export function writePagePref<T>(pageKey: string, value: T): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${pageKey}`, JSON.stringify(value));
  } catch {
    // Ignore private-mode / quota storage errors
  }
}
