const API_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * Fetch all chat sessions for a user from FastAPI backend
 */
export async function fetchChatHistory(email) {
  if (!email) return [];
  try {
    const res = await fetch(`${API_URL}/chat/api/history/?email=${encodeURIComponent(email)}`);
    const data = await res.json();
    return data.sessions || [];
  } catch (error) {
    console.error('Failed to fetch chat history:', error);
    return [];
  }
}

/**
 * Save or update a chat session to the Django backend
 */
export async function saveChatSession(email, sessionId, messages, title) {
  if (!email || !messages || messages.length === 0) return null;
  try {
    const res = await fetch(`${API_URL}/chat/api/save/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        session_id: sessionId,
        title,
        messages,
      }),
    });
    const data = await res.json();
    return data;
  } catch (error) {
    console.error('Failed to save chat session:', error);
    return null;
  }
}

/**
 * Delete a specific chat session
 */
export async function deleteChatSession(email, sessionId) {
  if (!sessionId) return false;
  try {
    const res = await fetch(`${API_URL}/chat/api/session/${sessionId}/?email=${encodeURIComponent(email)}`, {
      method: 'POST',
    });
    const data = await res.json();
    return data.success;
  } catch (error) {
    console.error('Failed to delete chat session:', error);
    return false;
  }
}

/**
 * Clear all chat history for a user
 */
export async function clearAllHistory(email) {
  if (!email) return false;
  try {
    const res = await fetch(`${API_URL}/chat/api/clear/?email=${encodeURIComponent(email)}`, {
      method: 'POST',
    });
    const data = await res.json();
    return data.success;
  } catch (error) {
    console.error('Failed to clear chat history:', error);
    return false;
  }
}
