import { useEffect, useState, useCallback } from "react";
import ConversationList from "./components/ConversationList.jsx";
import ChatWindow from "./components/ChatWindow.jsx";
import { listConversations, getConversation } from "./api.js";

export default function App() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeConversation, setActiveConversation] = useState(null);

  const refreshList = useCallback(async () => {
    setConversations(await listConversations());
  }, []);

  useEffect(() => { refreshList(); }, [refreshList]);

  useEffect(() => {
    if (!activeId) { setActiveConversation(null); return; }
    getConversation(activeId).then(setActiveConversation);
  }, [activeId]);

  function handleSelect(id) {
    setActiveId(id);
  }

  function handleNew() {
    setActiveId(null);
    setActiveConversation(null);
  }

  function handleConversationCreated(newId) {
    setActiveId(newId);
    refreshList();
  }

  return (
    <div className="app-shell">
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
      />
      <ChatWindow
        key={activeId ?? "new"}
        conversation={activeConversation}
        conversationId={activeId}
        onConversationCreated={handleConversationCreated}
        onMessagesChange={refreshList}
      />
    </div>
  );
}
