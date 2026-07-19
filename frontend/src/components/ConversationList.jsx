export default function ConversationList({ conversations, activeId, onSelect, onNew }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="brand">ollive</span>
        <button className="new-btn" onClick={onNew}>+ new</button>
      </div>
      <div className="conv-list">
        {conversations.length === 0 && (
          <div className="empty-hint">No conversations yet — start one.</div>
        )}
        {conversations.map((c) => (
          <button
            key={c.id}
            className={`conv-item ${c.id === activeId ? "active" : ""}`}
            onClick={() => onSelect(c.id)}
          >
            <div className="conv-title">{c.title || "Untitled"}</div>
            <div className="conv-meta">
              <span className={`status-dot ${c.status.toLowerCase()}`} />
              {c.status.toLowerCase()} · {c._count?.messages ?? 0} msgs
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
