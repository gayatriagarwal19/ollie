const BASE = import.meta.env.VITE_API_URL || "/api";

function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function listConversations(token) {
  const res = await fetch(`${BASE}/conversations`, { headers: authHeaders(token) });
  return res.json();
}

export async function getConversation(id, token) {
  const res = await fetch(`${BASE}/conversations/${id}`, { headers: authHeaders(token) });
  return res.json();
}

export async function cancelConversation(id, token) {
  const res = await fetch(`${BASE}/conversations/${id}/cancel`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return res.json();
}

/**
 * Sends a message and streams the reply via SSE, calling handlers as events
 * arrive. Returns an object with an `abort()` you can call to cancel
 * client-side (the server-side cancel endpoint stops generation; this stops
 * the client from reading further).
 */
export function sendMessageStream({ conversationId, model, message, token }, handlers) {
  const controller = new AbortController();

  fetch(`${BASE}/chat`, {
    method: "POST",
    headers: authHeaders(token),
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
