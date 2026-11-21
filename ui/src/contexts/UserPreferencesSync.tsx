import { useEffect, useRef } from 'react';
import { fetchUserPreferences, updateUserPreferences } from '../api/orchardApi';
import { apiConfig } from '../config/apiConfig';
import type { UserPreferencesDoc, UserThemePreference } from '../types/orchard';
import { useLanguage } from './LanguageContext';
import { useOrchard } from './OrchardContext';
import { useTheme, type ThemePreference } from './ThemeContext';

function uiThemeToUserPref(pref: ThemePreference): UserThemePreference {
  if (pref === 'light') return 'Light';
  if (pref === 'dark') return 'Dark';
  return 'OS';
}

function userPrefToUiTheme(pref: UserThemePreference): ThemePreference {
  if (pref === 'Light') return 'light';
  if (pref === 'Dark') return 'dark';
  return 'system';
}

/**
 * Synchronizes the 3 topbar user selections (displayed Orchard, Theme, Language)
 * with MongoDB `User.preferences` via `GET` / `PATCH /api/v1/users/{userId}/preferences`.
 */
export function UserPreferencesSync() {
  const { preference: themePref, setPreference: setThemePref } = useTheme();
  const { language, setLanguage } = useLanguage();
  const { selectedOrchardId, setSelectedOrchardId } = useOrchard();

  const isHydratedRef = useRef(false);
  const lastSavedJsonRef = useRef<string>('');

  // Hydrate preferences from backend on mount when live API is enabled
  useEffect(() => {
    const controller = new AbortController();

    if (apiConfig.usePlaceholders) {
      isHydratedRef.current = true;
      return;
    }

    fetchUserPreferences(apiConfig.defaultUserId, controller.signal)
      .then((res) => {
        const prefs = res.data;
        setThemePref(userPrefToUiTheme(prefs.theme));
        setLanguage(prefs.lang === 'en' ? 'en' : 'pl');
        if (prefs.activeOrchardId) {
          setSelectedOrchardId(prefs.activeOrchardId);
        }
        lastSavedJsonRef.current = JSON.stringify({
          theme: prefs.theme,
          lang: prefs.lang,
          activeOrchardId: prefs.activeOrchardId,
        });
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.warn('Could not load remote user preferences:', err);
        }
      })
      .finally(() => {
        isHydratedRef.current = true;
      });

    return () => controller.abort();
  }, []);

  // Persist all 3 choices whenever any of them changes
  useEffect(() => {
    if (!isHydratedRef.current) return;

    const payload: UserPreferencesDoc = {
      theme: uiThemeToUserPref(themePref),
      lang: language,
      activeOrchardId: selectedOrchardId || null,
    };

    const serialized = JSON.stringify(payload);
    if (serialized === lastSavedJsonRef.current) return;
    lastSavedJsonRef.current = serialized;

    const controller = new AbortController();
    updateUserPreferences(payload, apiConfig.defaultUserId, controller.signal).catch((err) => {
      if ((err as Error).name !== 'AbortError') {
        console.warn('Failed to persist user preferences:', err);
      }
    });

    return () => controller.abort();
  }, [themePref, language, selectedOrchardId]);

  return null;
}
