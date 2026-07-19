import { useEffect, useState, useCallback } from "react";
import { supabase } from "./supabase.js";
import AuthPage from "./components/AuthPage.jsx";
import ConversationList from "./components/ConversationList.jsx";
import ChatWindow from "./components/ChatWindow.jsx";
import { listConversations, getConversation } from "./api.js";

export default function App() {
  const [session, setSession] = useState(undefined); // undefined = loading
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [activeConversation, setActiveConversation] = useState(null);
  const [sessionKey, setSessionKey] = useState("new");

  // Subscribe to Supabase auth changes
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      if (!session) {
        // Clear state on logout
        setConversations([]);
        setActiveId(null);
        setActiveConversation(null);
        setSessionKey("new");
      }
    });
    return () => subscription.unsubscribe();
  }, []);

  const refreshList = useCallback(async () => {
    if (!session) return;
    setConversations(await listConversations(session.access_token));
  }, [session]);

  useEffect(() => { refreshList(); }, [refreshList]);

  useEffect(() => {
    if (!activeId || !session) { setActiveConversation(null); return; }
    getConversation(activeId, session.access_token).then(setActiveConversation);
  }, [activeId, session]);

  function handleSelect(id) {
    setActiveId(id);
    setSessionKey(id);
  }

  function handleNew() {
    setActiveId(null);
    setActiveConversation(null);
    setSessionKey(Date.now().toString());
  }

  function handleConversationCreated(newId) {
    setActiveId(newId);
    refreshList();
  }

  async function handleLogout() {
    await supabase.auth.signOut();
  }

  // Still loading auth state
  if (session === undefined) {
    return <div className="auth-loading">Loading…</div>;
  }

  // Not logged in — show auth page
  if (!session) {
    return <AuthPage />;
  }

  return (
    <div className="app-shell">
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
        userEmail={session.user.email}
        onLogout={handleLogout}
      />
      <ChatWindow
        key={sessionKey}
        conversation={activeConversation}
        conversationId={activeId}
        accessToken={session.access_token}
        onConversationCreated={handleConversationCreated}
        onMessagesChange={refreshList}
      />
    </div>
  );
}
