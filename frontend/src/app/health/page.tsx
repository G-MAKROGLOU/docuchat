import { HealthOverview } from "@/components/health/HealthOverview";

// The monitoring URLs are read at request time, so one image serves every deployment.
export const dynamic = "force-dynamic";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set.`);
  return value;
}

export default function HealthPage() {
  return (
    <section aria-label="Health">
      <HealthOverview
        grafanaUrl={required("GRAFANA_URL")}
        prometheusUrl={required("PROMETHEUS_URL")}
        // Optional, like tracing: no tile when it is empty.
        langfuseUrl={process.env.LANGFUSE_URL || null}
      />
    </section>
  );
}
