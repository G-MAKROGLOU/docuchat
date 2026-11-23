import type { Section } from "@/lib/settings";
import styles from "./SettingsForm.module.css";

export const SECTION_TITLES: Record<Section, string> = {
  indexing: "indexing",
  search: "search",
  models: "models",
  checking: "answer checking",
};

export const SECTION_LABELS: Record<Section, string> = {
  indexing: "Indexing",
  search: "Search",
  models: "Models",
  checking: "Answer checking",
};

export const MODEL_FIELDS = [
  { key: "chat_model", label: "Chat", id: "chat-model" },
  { key: "rewrite_model", label: "Rewrite", id: "rewrite-model" },
  { key: "grade_model", label: "Grade", id: "grade-model" },
  { key: "generate_model", label: "Generate", id: "generate-model" },
] as const;

function GraderTile({ text, cost }: { text: string; cost: string }) {
  return (
    <span className={styles.tile}>
      <span>{text}</span>
      <span className={styles.legendCost}>{cost}</span>
    </span>
  );
}

// How long the models think before they answer, as radio tiles.
export const EFFORT_OPTIONS = [
  {
    value: "low",
    label: "Low",
    description: (
      <GraderTile
        text="The least thinking before the answer. The answer starts soonest."
        cost="Fastest, lowest cost"
      />
    ),
  },
  {
    value: "medium",
    label: "Medium",
    description: (
      <GraderTile
        text="More thinking first. Helps with compound questions."
        cost="The first token comes later, higher cost"
      />
    ),
  },
  {
    value: "high",
    label: "High",
    description: (
      <GraderTile
        text="The most thinking first. For hard questions about several drugs."
        cost="Slowest, highest cost"
      />
    ),
  },
];

// What each grader mode does and costs, as radio tiles.
export const GRADER_OPTIONS = [
  {
    value: "off",
    label: "Off",
    description: (
      <GraderTile
        text="No check. Every retrieved excerpt goes to the answer step."
        cost="Fastest, no extra call"
      />
    ),
  },
  {
    value: "rule",
    label: "Rules",
    description: (
      <GraderTile
        text="Drops empty excerpts and excerpts of drugs that the question does not name."
        cost="No model call"
      />
    ),
  },
  {
    value: "llm",
    label: "Model",
    description: (
      <GraderTile
        text="A model grades the excerpts and can ask for a second search when they do not answer the question."
        cost="About 9 seconds more in a turn that needs a second search"
      />
    ),
  },
];

export function Help({ children }: { children: string }) {
  return <p className={styles.help}>{children}</p>;
}

export function ChunkEffects() {
  return (
    <ul className={styles.effects}>
      <li>
        <strong>Larger chunks: each label is cut into fewer chunks.</strong> Each chunk keeps more
        context, so a table or a warning stays whole. Search is less precise, because a chunk covers
        more topics. Each excerpt takes more of the model input, and a citation points to a longer
        passage.
      </li>
      <li>
        <strong>Smaller chunks: each label is cut into more chunks.</strong> Search finds the exact
        sentence and citations are tighter. A fact can be split between two chunks and lose its
        context. The index holds more chunks, and embedding them uses more tokens.
      </li>
      <li>
        <strong>Overlap</strong> repeats the end of a chunk at the start of the next chunk, so a
        sentence on the border is not lost. More overlap means more chunks and more embedding
        tokens.
      </li>
    </ul>
  );
}
