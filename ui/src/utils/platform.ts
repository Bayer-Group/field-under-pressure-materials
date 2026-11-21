/**
 * Detects whether the user is on macOS/iOS to display `⌘` vs `Ctrl` in zoom hints.
 */
export function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  const uaDataPlatform = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData?.platform;
  const source = `${uaDataPlatform ?? ''} ${navigator.platform ?? ''} ${navigator.userAgent ?? ''}`;
  return /mac|iphone|ipad|ipod/i.test(source);
}

export function getZoomModifierLabel(): '⌘' | 'Ctrl' {
  return isApplePlatform() ? '⌘' : 'Ctrl';
}
