"use client";

import { Card, Dropdown, RadioTile } from "@geomak/ui";
import type { SettingsOptions } from "@/lib/contract/generated";
import { choices, type Draft } from "@/lib/settings";
import { SectionFooter } from "./SectionFooter";
import { EFFORT_OPTIONS, MODEL_FIELDS } from "./settingsCopy";
import styles from "./SettingsForm.module.css";
import type { SettingsState } from "@/hooks/settings/useSettings";

export function ModelsCard({ state, options }: { state: SettingsState; options: SettingsOptions }) {
  const { draft, set } = state;
  return (
    <Card>
      <Card.Header title="Models" subtitle="Models of OpenRouter for each step of a chat turn." />
      <Card.Body>
        <div className={styles.row}>
          {MODEL_FIELDS.map(({ key, label, id }) => (
            <Dropdown
              key={key}
              label={label}
              layout="vertical"
              htmlFor={id}
              hasSearch
              items={choices(options.chat_models, draft[key])}
              value={draft[key]}
              onChange={({ target }) => set(key, String(target.value))}
            />
          ))}
        </div>
        <div className={styles.field}>
          <RadioTile
            label="Reasoning effort"
            columns={3}
            options={EFFORT_OPTIONS}
            value={draft.reasoning_effort}
            onChange={(value) => set("reasoning_effort", value as Draft["reasoning_effort"])}
          />
        </div>
        {options.chat_models.length === 0 ? (
          <p className={styles.fixed}>
            The model list of OpenRouter could not be loaded, so only the current models are
            offered.
          </p>
        ) : null}
      </Card.Body>
      <SectionFooter section="models" state={state} />
    </Card>
  );
}
