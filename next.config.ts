import type { NextConfig } from "next";

const pollIntervalMs = process.env.NEXT_WATCH_POLL_INTERVAL_MS;

const nextConfig: NextConfig = {
  output: "standalone",
  // Turbopack polls only through this option. Set the variable for bind mounts in Docker.
  ...(pollIntervalMs ? { watchOptions: { pollIntervalMs: Number(pollIntervalMs) } } : {}),
};

export default nextConfig;
