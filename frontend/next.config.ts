import type { NextConfig } from "next";

const pollIntervalMs = process.env.NEXT_WATCH_POLL_INTERVAL_MS
  ? Number(process.env.NEXT_WATCH_POLL_INTERVAL_MS)
  : undefined;
if (pollIntervalMs !== undefined && !(Number.isInteger(pollIntervalMs) && pollIntervalMs > 0)) {
  throw new Error("NEXT_WATCH_POLL_INTERVAL_MS must be a positive integer (milliseconds).");
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Basic headers for every route. A full Content-Security-Policy needs nonces and is not set here.
  headers: async () => [
    {
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      ],
    },
  ],
  // Project rules live in the umbrella repository; do not write AGENTS.md here.
  agentRules: false,
  // Turbopack polls only through this option. Set the variable for bind mounts in Docker.
  ...(pollIntervalMs ? { watchOptions: { pollIntervalMs } } : {}),
};

export default nextConfig;
