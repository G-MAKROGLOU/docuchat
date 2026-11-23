import { ChatPanel } from "@/components/chat/ChatPanel";
import styles from "./page.module.css";

export default function HomePage() {
  return (
    <section className={styles.chat} aria-label="Chat">
      <h1 className={styles.hidden}>Chat</h1>
      <ChatPanel />
    </section>
  );
}
