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

const ALLOWED_ORCHARD_ORDER: ObjectIdString[] = [
  '6b01933c1dc02a368703a020', // Grojec A
  '6b01933c1dc02a368703a01f', // Grojec B
  '6b01933c1dc02a368703a023', // Grojec C
];
const ALLOWED_ORCHARD_NAMES = new Set(['Grojec A', 'Grojec B', 'Grojec C']);

function filterAllowedOrchards(items: OrchardOption[]): OrchardOption[] {
  const filtered = items.filter(
    (o) => ALLOWED_ORCHARD_ORDER.includes(o._id) || ALLOWED_ORCHARD_NAMES.has(o.name),
  );
  return filtered.sort((a, b) => {
    const ia = ALLOWED_ORCHARD_ORDER.indexOf(a._id);
    const ib = ALLOWED_ORCHARD_ORDER.indexOf(b._id);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

function readInitialOrchardId(): ObjectIdString {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && ALLOWED_ORCHARD_ORDER.includes(saved)) {
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
        const visible = filterAllowedOrchards(res.data);
        setOrchards(visible);
        // Ensure stored orchard still exists in the allowed Grojec A/B/C list
        if (visible.length > 0 && !visible.some((o) => o._id === selectedOrchardId)) {
          const fallback = visible[0]._id;
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
