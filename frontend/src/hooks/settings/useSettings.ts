"use client";

import { useState } from "react";
import type { SettingsOptions, SettingsResponse, StatusResponse } from "@/lib/contract/generated";
import { fetchDocuments } from "@/lib/documents";
import {
  complete,
  type Draft,
  fetchOptions,
  fetchSettings,
  isValid,
  pick,
  saveSettings,
  SECTION_FIELDS,
  type Section,
  type SettingsFields,
  toFields,
} from "@/lib/settings";
import { fetchCorpusStats } from "@/lib/status";

// The corpus numbers feed only the re-embed estimate, so they are null when they fail.
export type Loaded = {
  settings: SettingsResponse;
  options: SettingsOptions;
  stats: StatusResponse | null;
  documents: number | null;
};

const NO_OPTIONS: SettingsOptions = { chat_models: [], embedding_models: [] };

export async function loadSettings(signal: AbortSignal): Promise<Loaded> {
  const [settings, stats, documents, options] = await Promise.allSettled([
    fetchSettings(signal),
    fetchCorpusStats(signal),
    fetchDocuments({ q: "", page: 1, pageSize: 1 }, signal),
    fetchOptions(signal),
  ]);
  if (settings.status === "rejected") throw settings.reason;
  return {
    settings: settings.value,
    stats: stats.status === "fulfilled" ? stats.value : null,
    documents: documents.status === "fulfilled" ? documents.value.total : null,
    // Without the lists the dropdowns offer only the current values.
    options: options.status === "fulfilled" ? options.value : NO_OPTIONS,
  };
}

// The saved values, the edits and the save of each section.
export function useSettings(initial: SettingsResponse) {
  const [saved, setSaved] = useState<SettingsFields>(() => toFields(initial));
  const [draft, setDraft] = useState<Draft>(() => toFields(initial));
  const [messages, setMessages] = useState<Partial<Record<Section, string>>>({});
  const [busy, setBusy] = useState<Section | null>(null);
  // The section whose save waits for the approval to embed every document again.
  const [confirming, setConfirming] = useState<Section | null>(null);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }));

  // The saved values with the edits of one card: what a save of that card sends.
  const candidate = (section: Section): SettingsFields | null =>
    complete({ ...saved, ...pick(draft, section) });
  const changed = (section: Section) =>
    SECTION_FIELDS[section].some((key) => draft[key] !== saved[key]);
  const savable = (section: Section) => {
    const fields = candidate(section);
    return changed(section) && fields !== null && isValid(fields);
  };
  const discard = (section: Section) =>
    setDraft((previous) => ({ ...previous, ...pick(saved, section) }));
  const say = (section: Section, text: string | undefined) =>
    setMessages((previous) => ({ ...previous, [section]: text }));

  const save = async (section: Section, confirmed: boolean) => {
    const fields = candidate(section);
    if (!fields) return;
    setBusy(section);
    setConfirming(null);
    say(section, undefined);
    try {
      const outcome = await saveSettings(fields, confirmed);
      if (outcome.kind === "saved") {
        const next = toFields(outcome.saved);
        setSaved(next);
        setDraft((previous) => ({ ...previous, ...pick(next, section) }));
        if (outcome.saved.reingest_started) {
          say(
            section,
            "Saved. Every document is embedded again now. Follow it on the Status page.",
          );
        } else if (confirmed) {
          say(section, "Saved. The next ingestion pass embeds every document again.");
        } else {
          say(section, "Saved.");
        }
      } else if (outcome.kind === "running") {
        say(section, "An ingestion pass is running. Try again when it is done.");
      } else if (outcome.kind === "confirm") {
        // The API asks for the approval: show the same question as for an indexing change.
        say(section, "This change embeds every document again. Approve it to save.");
        setConfirming(section);
      } else {
        say(section, "The settings could not be saved.");
      }
    } catch {
      say(section, "The settings could not be saved.");
    } finally {
      setBusy(null);
    }
  };

  // An indexing change embeds every document again, so it needs the approval first.
  const requestSave = (section: Section) =>
    section === "indexing" ? setConfirming(section) : save(section, false);

  return {
    saved,
    draft,
    messages,
    busy,
    confirming,
    setConfirming,
    set,
    candidate,
    changed,
    savable,
    discard,
    save,
    requestSave,
  };
}

export type SettingsState = ReturnType<typeof useSettings>;
