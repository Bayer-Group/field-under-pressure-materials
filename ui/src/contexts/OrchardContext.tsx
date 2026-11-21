import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchOrchardsList } from '../api/orchardApi';
import { apiConfig } from '../config/apiConfig';
import type { ObjectIdString, OrchardOption } from '../types/orchard';

interface OrchardContextValue {
  orchards: OrchardOption[];
  selectedOrchardId: ObjectIdString;
  selectedOrchard: OrchardOption | null;
  setSelectedOrchardId: (id: ObjectIdString) => void;
}

const STORAGE_KEY = 'fup-active-orchard-id';

const OrchardContext = createContext<OrchardContextValue | null>(null);

function readInitialOrchardId(): ObjectIdString {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && saved.trim().length > 0) {
      return saved;
    }
  } catch {
    // ignore storage errors
  }
  return apiConfig.defaultOrchardId;
}

export function OrchardProvider({ children }: { children: ReactNode }) {
  const [orchards, setOrchards] = useState<OrchardOption[]>([]);
  const [selectedOrchardId, setSelectedOrchardIdState] =
    useState<ObjectIdString>(readInitialOrchardId);

  useEffect(() => {
    const controller = new AbortController();
    fetchOrchardsList(controller.signal)
      .then((res) => {
        setOrchards(res.data);
        // Ensure stored orchard still exists in fetched catalog
        if (res.data.length > 0 && !res.data.some((o) => o._id === selectedOrchardId)) {
          const fallback = res.data[0]._id;
          setSelectedOrchardIdState(fallback);
          try {
            window.localStorage.setItem(STORAGE_KEY, fallback);
          } catch {
            // ignore
          }
        }
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to load orchards list:', err);
        }
      });

    return () => controller.abort();
  }, []);

  const setSelectedOrchardId = (id: ObjectIdString) => {
    setSelectedOrchardIdState(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // ignore storage errors
    }
  };

  const selectedOrchard = useMemo(
    () => orchards.find((o) => o._id === selectedOrchardId) ?? null,
    [orchards, selectedOrchardId],
  );

  const value = useMemo(
    () => ({
      orchards,
      selectedOrchardId,
      selectedOrchard,
      setSelectedOrchardId,
    }),
    [orchards, selectedOrchardId, selectedOrchard],
  );

  return <OrchardContext.Provider value={value}>{children}</OrchardContext.Provider>;
}

export function useOrchard(): OrchardContextValue {
  const ctx = useContext(OrchardContext);
  if (!ctx) {
    throw new Error('useOrchard must be used within OrchardProvider');
  }
  return ctx;
}
