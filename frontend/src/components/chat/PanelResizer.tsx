"use client";

import type { KeyboardEvent, PointerEvent } from "react";
import styles from "./PanelResizer.module.css";

export const MIN_PERCENT = 25;
export const MAX_PERCENT = 75;
const STEP = 5;

function clamp(percent: number): number {
  return Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, percent));
}

/** The width of the right panel, in percent of the layout, when the handle is at `clientX`. */
export function rightPercent(clientX: number, layout: { left: number; width: number }): number {
  return clamp(((layout.left + layout.width - clientX) / layout.width) * 100);
}

// The new width for a key: arrows step, Home and End go to the limits.
const KEYS: Record<string, (percent: number) => number> = {
  ArrowLeft: (percent) => clamp(percent + STEP),
  ArrowRight: (percent) => clamp(percent - STEP),
  Home: () => MIN_PERCENT,
  End: () => MAX_PERCENT,
};

/** A vertical handle that sets the width of the panel on its right. */
export function PanelResizer({
  percent,
  onChange,
  label,
}: {
  percent: number;
  onChange: (percent: number) => void;
  label: string;
}) {
  const move = (event: PointerEvent<HTMLHRElement>) => {
    const handle = event.currentTarget;
    const layout = handle.parentElement?.getBoundingClientRect();
    if (layout && handle.hasPointerCapture(event.pointerId)) {
      onChange(rightPercent(event.clientX, layout));
    }
  };
  const step = (event: KeyboardEvent<HTMLHRElement>) => {
    const next = KEYS[event.key];
    if (!next) return;
    event.preventDefault();
    onChange(next(percent));
  };

  // An <hr> has the separator role. With a tab stop and a value it is the WAI-ARIA window
  // splitter, an interactive widget that jsx-a11y does not know.
  /* oxlint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */
  return (
    <hr
      tabIndex={0}
      className={styles.handle}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={MIN_PERCENT}
      aria-valuemax={MAX_PERCENT}
      onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
      onPointerMove={move}
      onKeyDown={step}
    />
  );
  /* oxlint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */
}
