"use client";

import { Tabs } from "@geomak/ui";
import { LoadState } from "@/components/layout/LoadState";
import { PageHeading } from "@/components/layout/PageHeading";
import { useLoad } from "@/hooks/useLoad";
import type { Section } from "@/lib/settings";
import { CheckingCard } from "./CheckingCard";
import { IndexingCard } from "./IndexingCard";
import { ModelsCard } from "./ModelsCard";
import { ReindexModal } from "./ReindexModal";
import { SearchCard } from "./SearchCard";
import { SECTION_LABELS } from "./settingsCopy";
import styles from "./SettingsForm.module.css";
import { type Loaded, loadSettings, useSettings } from "@/hooks/settings/useSettings";

const SECTIONS = Object.keys(SECTION_LABELS) as Section[];

function UnsavedMark() {
  return (
    <>
      <span aria-hidden="true">•</span>
      <span className={styles.hidden}>unsaved changes</span>
    </>
  );
}

// Mounts after the load, so the form state starts from the loaded settings.
function SettingsEditor({ loaded }: { loaded: Loaded }) {
  const state = useSettings(loaded.settings);
  return (
    <>
      <div className={styles.page}>
        <Tabs defaultValue="indexing" variant="underline">
          <Tabs.List aria-label="Settings sections">
            {SECTIONS.map((section) => (
              <Tabs.Trigger
                key={section}
                value={section}
                badge={state.changed(section) ? <UnsavedMark /> : undefined}
              >
                {SECTION_LABELS[section]}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Panel value="indexing">
            <IndexingCard state={state} options={loaded.options} />
          </Tabs.Panel>
          <Tabs.Panel value="search">
            <SearchCard state={state} />
          </Tabs.Panel>
          <Tabs.Panel value="models">
            <ModelsCard state={state} options={loaded.options} />
          </Tabs.Panel>
          <Tabs.Panel value="checking">
            <CheckingCard state={state} />
          </Tabs.Panel>
        </Tabs>
      </div>
      <ReindexModal state={state} loaded={loaded} />
    </>
  );
}

export function SettingsForm() {
  const load = useLoad("settings", loadSettings);
  return (
    <>
      <PageHeading title="Settings" note="Indexing, search, models and answer checking." />
      {load.data ? (
        <SettingsEditor loaded={load.data} />
      ) : (
        <LoadState error={load.error} label="settings" onRetry={load.reload} />
      )}
    </>
  );
}
