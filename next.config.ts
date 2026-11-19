import type { NextConfig } from "next";

const pollIntervalMs = process.env.NEXT_WATCH_POLL_INTERVAL_MS
  ? Number(process.env.NEXT_WATCH_POLL_INTERVAL_MS)
  : undefined;
if (pollIntervalMs !== undefined && !(Number.isInteger(pollIntervalMs) && pollIntervalMs > 0)) {
  throw new Error("NEXT_WATCH_POLL_INTERVAL_MS must be a positive integer (milliseconds).");
}

const nextConfig: NextConfig = {
  output: "standalone",
  // Project rules live in the umbrella repository; do not write AGENTS.md here.
  agentRules: false,
  // Turbopack polls only through this option. Set the variable for bind mounts in Docker.
  ...(pollIntervalMs ? { watchOptions: { pollIntervalMs } } : {}),
};

export default nextConfig;
