"use client";

import { Card, NumberInput } from "@geomak/ui";
import { LIMITS } from "@/lib/settings";
import { SectionFooter } from "./SectionFooter";
import { Help } from "./settingsCopy";
import type { SettingsState } from "@/hooks/settings/useSettings";

export function SearchCard({ state }: { state: SettingsState }) {
  return (
    <Card>
      <Card.Header title="Search" subtitle="What each question retrieves." />
      <Card.Body>
        <NumberInput
          label="Chunks per search (top-k)"
          htmlFor="top-k"
          value={state.draft.top_k ?? ""}
          min={LIMITS.top_k.min}
          max={LIMITS.top_k.max}
          onChange={({ target }) => state.set("top_k", target.value)}
        />
        <Help>
          The vector search and the keyword search each return this many chunks. A higher value
          misses less, but the prompt gets longer and the answer costs more and starts later. A
          lower value is faster and may miss the passage that answers the question.
        </Help>
      </Card.Body>
      <SectionFooter section="search" state={state} />
    </Card>
  );
}
