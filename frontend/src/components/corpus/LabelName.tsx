import { parseTitle } from "@/lib/labelTitle";
import styles from "./CorpusLabels.module.css";

// The name and the generic name on top; the form, the maker and the rest in a line below.
export function LabelName({
  title,
  extra,
  problem,
}: {
  title: string;
  extra?: string;
  problem?: string | null;
}) {
  const parsed = parseTitle(title);
  const meta = parsed ? [parsed.form, parsed.maker, extra] : [extra];
  return (
    <span className={styles.title}>
      <span className={styles.name}>
        {parsed ? parsed.name : title}
        {parsed ? <span className={styles.generic}>{parsed.generic}</span> : null}
      </span>
      <span className={styles.meta}>{meta.filter(Boolean).join(" · ")}</span>
      {problem ? <span className={styles.problem}>{problem}</span> : null}
    </span>
  );
}
