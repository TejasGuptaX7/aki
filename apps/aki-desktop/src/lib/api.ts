import { invoke, Channel } from "@tauri-apps/api/core";

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type SseChunk = { text: string };

/**
 * Send a chat turn to the local Hermes agent via the Rust backend proxy.
 * Chunks of the SSE stream are delivered through `onChunk` as they arrive.
 */
export async function sendChatMessage(
  messages: ChatMessage[],
  onChunk: (chunk: string) => void
): Promise<void> {
  const channel = new Channel<SseChunk>();
  channel.onmessage = (msg) => onChunk(msg.text);
  await invoke("send_chat_message", { messages, onChunk: channel });
}
