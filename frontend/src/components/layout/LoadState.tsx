"use client";

import { Banner, Button, LoadingSpinner } from "@geomak/ui";

// The first load of a page: a spinner, or an error with a retry.
export function LoadState({
  error,
  label,
  onRetry,
}: {
  error: boolean;
  label: string;
  onRetry: () => void;
}) {
  if (!error) return <LoadingSpinner inline size="sm" />;
  return (
    <Banner tone="danger">
      The {label} could not be loaded.{" "}
      <Button content="Try again" variant="ghost" size="sm" onClick={onRetry} />
    </Banner>
  );
}
