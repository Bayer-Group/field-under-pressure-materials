import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';

export interface DropdownOption {
  value: string;
  label: string;
}

export interface DropdownGroup {
  label: string;
  options: DropdownOption[];
}

export interface DropdownProps {
  value: string;
  onChange: (value: string) => void;
  options?: DropdownOption[];
  groups?: DropdownGroup[];
  ariaLabel?: string;
  title?: string;
  icon?: ReactNode;
  variant?: 'default' | 'topbar' | 'calendar' | 'compact';
  className?: string;
  disabled?: boolean;
  placeholder?: string;
}

interface MenuCoords {
  top: number;
  left: number;
  minWidth: number;
  maxHeight: number;
  openUpward: boolean;
}

export function Dropdown({
  value,
  onChange,
  options,
  groups,
  ariaLabel,
  title,
  icon,
  variant = 'default',
  className = '',
  disabled = false,
  placeholder = '—',
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [coords, setCoords] = useState<MenuCoords | null>(null);

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const listboxId = useId();

  const flatOptions = useMemo<DropdownOption[]>(() => {
    if (groups && groups.length > 0) {
      return groups.flatMap((g) => g.options);
    }
    return options ?? [];
  }, [options, groups]);

  const selectedOption = useMemo(
    () => flatOptions.find((opt) => opt.value === value) ?? null,
    [flatOptions, value],
  );

  const computeCoords = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;
    const gap = 6;
    const spaceBelow = viewportH - rect.bottom - gap - 12;
    const spaceAbove = rect.top - gap - 12;
    const openUpward = spaceBelow < 140 && spaceAbove > spaceBelow;
    const maxHeight = Math.max(120, Math.min(300, openUpward ? spaceAbove : spaceBelow));
    const minWidth = Math.max(rect.width, variant === 'compact' ? 150 : 168);
    const maxLeft = Math.max(10, viewportW - minWidth - 10);
    const left = Math.min(Math.max(10, rect.left), maxLeft);
    const top = openUpward ? rect.top - gap : rect.bottom + gap;

    setCoords({ top, left, minWidth, maxHeight, openUpward });
  }, [variant]);

  useLayoutEffect(() => {
    if (!open) return;
    computeCoords();
  }, [open, computeCoords]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    };

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };

    const handleViewportChange = (event: Event) => {
      if (event.type === 'scroll' && menuRef.current?.contains(event.target as Node | null)) {
        return;
      }
      computeCoords();
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('resize', handleViewportChange);
    window.addEventListener('scroll', handleViewportChange, true);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('resize', handleViewportChange);
      window.removeEventListener('scroll', handleViewportChange, true);
    };
  }, [open, computeCoords]);

  // Scroll the selected/active option into view when opened
  useEffect(() => {
    if (!open) return;
    const idx = flatOptions.findIndex((opt) => opt.value === value);
    setActiveIndex(idx >= 0 ? idx : 0);
    const raf = window.requestAnimationFrame(() => {
      const selectedEl = menuRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
      selectedEl?.scrollIntoView({ block: 'nearest' });
    });
    return () => window.cancelAnimationFrame(raf);
  }, [open, flatOptions, value]);

  const selectOption = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      if (flatOptions.length === 0) return;
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex((prev) => {
        const next = prev < 0 ? 0 : (prev + step + flatOptions.length) % flatOptions.length;
        const item = menuRef.current?.querySelector<HTMLElement>(`[data-opt-index="${next}"]`);
        item?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      } else if (activeIndex >= 0 && flatOptions[activeIndex]) {
        selectOption(flatOptions[activeIndex].value);
      } else {
        setOpen(false);
      }
    }
  };

  let runningIndex = -1;

  const renderOption = (opt: DropdownOption) => {
    runningIndex += 1;
    const idx = runningIndex;
    const isSelected = opt.value === value;
    const isActive = idx === activeIndex;
    return (
      <button
        key={opt.value}
        type="button"
        role="option"
        aria-selected={isSelected}
        data-opt-index={idx}
        className={`sage-dropdown-option${isSelected ? ' is-selected' : ''}${isActive ? ' is-active' : ''}`}
        onMouseEnter={() => setActiveIndex(idx)}
        onClick={() => selectOption(opt.value)}
      >
        <span className="sage-dropdown-option-label">{opt.label}</span>
        {isSelected && <Check size={14} className="sage-dropdown-check" aria-hidden="true" />}
      </button>
    );
  };

  const menuNode =
    open && coords
      ? createPortal(
          <div
            ref={menuRef}
            id={listboxId}
            role="listbox"
            aria-label={ariaLabel}
            className={`sage-dropdown-menu${coords.openUpward ? ' is-upward' : ''}`}
            style={{
              top: coords.openUpward ? undefined : `${coords.top}px`,
              bottom: coords.openUpward ? `${window.innerHeight - coords.top}px` : undefined,
              left: `${coords.left}px`,
              minWidth: `${coords.minWidth}px`,
              maxHeight: `${coords.maxHeight}px`,
            }}
          >
            {groups && groups.length > 0
              ? groups.map((group) => (
                  <div key={group.label} className="sage-dropdown-group" role="group" aria-label={group.label}>
                    <div className="sage-dropdown-group-label">{group.label}</div>
                    {group.options.map(renderOption)}
                  </div>
                ))
              : flatOptions.map(renderOption)}
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-label={ariaLabel}
        title={title}
        disabled={disabled}
        className={`sage-dropdown-trigger is-${variant}${open ? ' is-open' : ''}${className ? ` ${className}` : ''}`}
        onClick={() => !disabled && setOpen((prev) => !prev)}
        onKeyDown={handleTriggerKeyDown}
      >
        {icon && <span className="sage-dropdown-icon" aria-hidden="true">{icon}</span>}
        <span className="sage-dropdown-value">{selectedOption?.label ?? placeholder}</span>
        <ChevronDown size={14} className="sage-dropdown-chevron" aria-hidden="true" />
      </button>
      {menuNode}
    </>
  );
}
