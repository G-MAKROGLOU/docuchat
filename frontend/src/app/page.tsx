import { HealthIndicator } from "@/components/HealthIndicator";

export default function HomePage() {
  return (
    <div className="shell">
      <header className="shell-header">
        <h1>Assistant</h1>
        <HealthIndicator />
      </header>
      <main className="shell-chat" aria-label="Chat">
        <p>Chat area</p>
      </main>
      <aside className="shell-panel" aria-label="Sources">
        <p>Side panel</p>
      </aside>
    </div>
  );
}
