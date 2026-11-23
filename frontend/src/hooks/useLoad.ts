"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";

type Loaded<T> = { token: string | null; data: T | undefined; failed: boolean };

export type Load<T> = {
  // The last loaded data. It stays while a newer request runs or after it fails.
  data: T | undefined;
  error: boolean;
  loading: boolean;
  reload: () => void;
};

// Loads again when `key` changes or on reload(). A newer request aborts the older one.
export function useLoad<T>(key: string, load: (signal: AbortSignal) => Promise<T>): Load<T> {
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded<T>>({
    token: null,
    data: undefined,
    failed: false,
  });
  const token = `${attempt}:${key}`;
  const run = useEffectEvent(load);

  useEffect(() => {
    const controller = new AbortController();
    run(controller.signal).then(
      (data) => setLoaded({ token, data, failed: false }),
      () => {
        if (!controller.signal.aborted) {
          setLoaded((previous) => ({ token, data: previous.data, failed: true }));
        }
      },
    );
    return () => controller.abort();
  }, [token]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return {
    data: loaded.data,
    error: loaded.token === token && loaded.failed,
    loading: loaded.token !== token,
    reload,
  };
}
