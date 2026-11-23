"use client";

import { useCallback, useState } from "react";
import { useLoad } from "@/hooks/useLoad";
import { fetchQueue } from "@/lib/labels";

// The label queue, one page at a time. Every load goes through useLoad: one request, one signal.
export function useQueue() {
  const [page, setPage] = useState(1);
  const queue = useLoad(`page:${page}`, (signal) => fetchQueue(page, signal));
  const { reload } = queue;

  // A new entry is on the first page. A page change and a reload in one render load once.
  const showFirstPage = useCallback(() => {
    setPage(1);
    reload();
  }, [reload]);

  return { ...queue, page, setPage, showFirstPage };
}

export type Queue = ReturnType<typeof useQueue>;
