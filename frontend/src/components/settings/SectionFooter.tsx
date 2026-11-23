"use client";

import { Button, Card } from "@geomak/ui";
import type { Section } from "@/lib/settings";
import { SECTION_TITLES } from "./settingsCopy";
import styles from "./SettingsForm.module.css";
import type { SettingsState } from "@/hooks/settings/useSettings";

export function SectionFooter({ section, state }: { section: Section; state: SettingsState }) {
  const message = state.messages[section];
  return (
    <Card.Footer>
      <div className={styles.actions}>
        {message ? <output className={styles.message}>{message}</output> : null}
        <Button
          content="Discard"
          aria-label={`Discard changes of ${SECTION_TITLES[section]}`}
          variant="ghost"
          disabled={!state.changed(section) || state.busy !== null}
          onClick={() => state.discard(section)}
        />
        <Button
          content="Save"
          aria-label={`Save ${SECTION_TITLES[section]}`}
          loading={state.busy === section}
          disabled={!state.savable(section) || state.busy !== null}
          onClick={() => state.requestSave(section)}
        />
      </div>
    </Card.Footer>
  );
}
