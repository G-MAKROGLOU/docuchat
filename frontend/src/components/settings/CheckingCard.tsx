"use client";

import { Card, RadioTile } from "@geomak/ui";
import type { Draft } from "@/lib/settings";
import { SectionFooter } from "./SectionFooter";
import { GRADER_OPTIONS } from "./settingsCopy";
import type { SettingsState } from "@/hooks/settings/useSettings";

export function CheckingCard({ state }: { state: SettingsState }) {
  return (
    <Card>
      <Card.Header title="Answer checking" subtitle="Whether retrieved excerpts are graded." />
      <Card.Body>
        <RadioTile
          label="Grader"
          columns={3}
          options={GRADER_OPTIONS}
          value={state.draft.grader_mode}
          onChange={(value) => state.set("grader_mode", value as Draft["grader_mode"])}
        />
      </Card.Body>
      <SectionFooter section="checking" state={state} />
    </Card>
  );
}
