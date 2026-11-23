import { use } from "react";
import { type ChatSession, ChatContext } from "@/components/chat/ChatProvider";

export function useChatSession(): ChatSession {
  const session = use(ChatContext);
  if (!session) throw new Error("useChatSession needs a ChatProvider above it");
  return session;
}
