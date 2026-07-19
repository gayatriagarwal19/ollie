import { useEffect, useRef, useState } from "react";
import { sendMessageStream, cancelConversation } from "../api.js";

const MODELS = [
  "llama-3.3-70b-versatile",
  "llama-3.1-8b-instant",
  "gemma2-9b-it",
  "claude-sonnet-4-6",
  "claude-opus-4-6",
  "gpt-4o",
  "gpt-4o-mini",
];

export default function ChatWindow({ conversation, conversationId, onConversationCreated, onMessagesChange }) {
  const [messages, setMessages] = useState(conversation?.messages ?? []);
  const [input, setInput] = useState("");
  const [model, setModel] = useState(MODELS[0]);
  const [streaming, setStreaming] = useState(false);
  const [draftReply, setDraftReply] = useState("");
  const controllerRef = useRef(null);
  const scrollRef = useRef(null);
  const draftRef = useRef("");

  useEffect(() => {
    setMessages(conversation?.messages ?? []);
  }, [conversation?.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, draftReply]);

  function handleSend() {
    if (!input.trim() || streaming) return;
    const userMsg = { id: `local-${Date.now()}`, role: "USER", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);
    setDraftReply("");
    draftRef.current = "";

    const currentInput = input;
    setInput("");

    controllerRef.current = sendMessageStream(
      { conversationId, model, message: currentInput },
      {
        conversation: ({ conversationId: newId }) => {
          if (!conversationId) onConversationCreated?.(newId);
        },
        delta: ({ delta }) => {
          draftRef.current += delta;
          setDraftReply(draftRef.current);
        },
        done: () => {
          setMessages((prev) => [...prev, { id: `local-r-${Date.now()}`, role: "ASSISTANT", content: draftRef.current }]);
          setStreaming(false);
          onMessagesChange?.();
        },
        cancelled: () => {
          setStreaming(false);
        },
        error: ({ message }) => {
          setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: "SYSTEM", content: `Error: ${message}` }]);
          setStreaming(false);
        },
      }
    );
  }

  async function handleCancel() {
    controllerRef.current?.abort();
    if (conversationId) await cancelConversation(conversationId);
    setStreaming(false);
  }

  return (
    <main className="chat-window">
      <div className="chat-toolbar">
        <select value={model} onChange={(e) => setModel(e.target.value)} disabled={!!conversationId}>
          {MODELS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        {streaming && (
          <button className="cancel-btn" onClick={handleCancel}>■ cancel</button>
        )}
      </div>

      <div className="messages" ref={scrollRef}>
        {messages.length === 0 && !streaming && (
          <div className="empty-hint centered">Send a message to start the conversation.</div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role.toLowerCase()}`}>
            <div className="bubble-role">{m.role.toLowerCase()}</div>
            <div className="bubble-content">{m.content}</div>
          </div>
        ))}
        {streaming && (
          <div className="bubble assistant streaming">
            <div className="bubble-role">assistant</div>
            <div className="bubble-content">{draftReply}<span className="cursor" /></div>
          </div>
        )}
      </div>

      <div className="composer">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          placeholder="Message the model…"
          rows={2}
        />
        <button onClick={handleSend} disabled={streaming || !input.trim()}>Send</button>
      </div>
    </main>
  );
}
