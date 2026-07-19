const BASE = import.meta.env.VITE_API_URL || "/api";

export async function listConversations() {
  const res = await fetch(`${BASE}/conversations`);
  return res.json();
}

export async function getConversation(id) {
  const res = await fetch(`${BASE}/conversations/${id}`);
  return res.json();
}

export async function cancelConversation(id) {
  const res = await fetch(`${BASE}/conversations/${id}/cancel`, { method: "POST" });
  return res.json();
}

/**
 * Sends a message and streams the reply via SSE, calling handlers as events
 * arrive. Returns an object with an `abort()` you can call to cancel
 * client-side (the server-side cancel endpoint stops generation; this stops
 * the client from reading further).
 */
export function sendMessageStream({ conversationId, model, message }, handlers) {
  const controller = new AbortController();

  fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversationId, model, message }),
    signal: controller.signal,
  }).then(async (res) => {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();

      for (const chunk of chunks) {
        const eventMatch = chunk.match(/^event: (.+)$/m);
        const dataMatch = chunk.match(/^data: (.+)$/m);
        if (!eventMatch || !dataMatch) continue;
        const event = eventMatch[1];
        const data = JSON.parse(dataMatch[1]);
        handlers[event]?.(data);
      }
    }
  }).catch((err) => {
    if (err.name !== "AbortError") handlers.error?.({ message: err.message });
  });

  return controller;
}
