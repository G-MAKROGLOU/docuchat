"use client";

import { useEffect, useState } from "react";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { CatalogLabelResponse } from "@/lib/contract/generated";
import { isSetId, searchCatalog } from "@/lib/labels";

// The pause after the last key press before DailyMed is asked.
const DEBOUNCE_MS = 400;
const MIN_CHARACTERS = 2;

// The labels are null when the search failed.
type Found = { text: string; labels: CatalogLabelResponse[] | null };

// Searches DailyMed while the user types, after a pause. A newer text cancels the older request.
export function useCatalogSearch(text: string) {
  const query = useDebouncedValue(text, DEBOUNCE_MS);
  const searchable = query.length >= MIN_CHARACTERS && !isSetId(query);
  const [found, setFound] = useState<Found | null>(null);

  useEffect(() => {
    if (!searchable) return;
    const controller = new AbortController();
    searchCatalog(query, controller.signal).then(
      (labels) => setFound({ text: query, labels }),
      () => {
        if (!controller.signal.aborted) setFound({ text: query, labels: null });
      },
    );
    return () => controller.abort();
  }, [searchable, query]);

  // The live text decides at once whether results show, without the pause.
  const live = text.length >= MIN_CHARACTERS && !isSetId(text);
  const current = live && searchable && found?.text === query ? found : null;
  return {
    // True from the end of the pause until DailyMed answers.
    searching: live && searchable && current === null,
    failed: current !== null && current.labels === null,
    labels: current?.labels ?? [],
    // The answer is for the text as it is now, not for an older text.
    settled: current !== null && query === text,
  };
}
