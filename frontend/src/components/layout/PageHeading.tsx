"use client";

import { Typography } from "@geomak/ui";

// OxygenUI uses React context, so it renders in client components only.
export function PageHeading({ title, note }: { title: string; note?: string }) {
  return (
    <header>
      <Typography variant="h2" as="h1">
        {title}
      </Typography>
      {note ? <Typography color="foreground-muted">{note}</Typography> : null}
    </header>
  );
}
