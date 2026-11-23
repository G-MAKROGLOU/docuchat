type LabelTitle = { name: string; generic: string; form: string; maker: string };

// Words in company names that stay in capitals, and small words that stay in lower case.
const CAPITALS = new Set(["LLC", "INC.", "INC", "LP", "LTD", "USA", "CORP", "PLC", "LLP", "HCL"]);
const SMALL = new Set(["AND", "OF", "THE", "FOR"]);

function titleCase(text: string): string {
  return text
    .split(" ")
    .map((word, index) => {
      const bare = word.replace(/,$/, "");
      if (CAPITALS.has(bare)) return word;
      const lower = word.toLowerCase();
      if (index > 0 && SMALL.has(bare)) return lower;
      // Each part of a hyphenated word starts with a capital.
      return lower.replace(
        /(^|-)([a-z])/g,
        (_, edge: string, letter: string) => edge + letter.toUpperCase(),
      );
    })
    .join(" ");
}

// A title without a generic name in brackets: the name runs up to the first dosage form word.
const FORM_WORD =
  /\s(?=(TABLET|CAPSULE|INJECTION|SOLUTION|SUSPENSION|CREAM|OINTMENT|GEL|PATCH|POWDER|SPRAY|LIQUID|SYRUP|LOZENGE|KIT|EMULSION|GRANULE|DROPS|AEROSOL|ELIXIR|FILM)\b)/;

function withoutGeneric(body: string, maker: string): LabelTitle | null {
  if (!body) return null;
  const cut = FORM_WORD.exec(body);
  const name = cut ? body.slice(0, cut.index) : body;
  const form = cut ? body.slice(cut.index).trim().toLowerCase() : "";
  return {
    name: titleCase(name),
    generic: "",
    form: form.charAt(0).toUpperCase() + form.slice(1),
    maker,
  };
}

// "BRAND (GENERIC) FORM [MAKER]" as DailyMed writes it. A title of several products gives the
// first name and "Several products" as the form. Null for an empty title.
export function parseTitle(title: string): LabelTitle | null {
  const makerMatch = /\[([^\]]+)\]\s*$/.exec(title);
  const body = (makerMatch ? title.slice(0, makerMatch.index) : title).trim();
  const maker = makerMatch?.[1] ? titleCase(makerMatch[1]) : "";
  const generics = [...body.matchAll(/\(([^()]+)\)/g)].map((m) => (m[1] ?? "").toLowerCase());
  const first = /^([^()]+?)\s+\(/.exec(body)?.[1];
  if (!first || generics.length === 0) return withoutGeneric(body, maker);
  if (generics.length > 1) {
    return {
      name: titleCase(first),
      generic: [...new Set(generics)].join(", "),
      form: "Several products",
      maker,
    };
  }
  const form = body
    .slice(body.indexOf(")") + 1)
    .trim()
    .toLowerCase();
  return {
    name: titleCase(first),
    generic: generics[0] ?? "",
    form: form.charAt(0).toUpperCase() + form.slice(1),
    maker,
  };
}
