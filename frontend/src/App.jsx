import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import SplashScreen from './components/splash/SplashScreen';
import GeometricBackground from './components/background/GeometricBackground';
import Sidebar from './components/layout/Sidebar';
import MainContent from './components/layout/MainContent';
import ChatInput from './components/ui/ChatInput';
import AuthModal from './components/auth/AuthModal';
import HistoryDrawer from './components/history/HistoryDrawer';
import { AuthProvider, useAuth } from './context/AuthContext';
import { API_CONFIG, sendMessage, uploadFile } from './services/api';
import { getDemoResponse } from './services/demoService';
import {
  fetchChatHistory,
  saveChatSession,
  deleteChatSession,
} from './services/chatHistoryService';
import { Sparkles, MessageSquare, Menu, Plus } from 'lucide-react';
import { GrievanceApp } from './grievance';
import { ReportProblemButton } from './integration/ReportProblemButton';
import './grievanceHost.css';

/**
 * The student's own words that produced an answer. "Report this as a problem" sends these
 * to the grievance form, not the assistant's reply.
 */
function questionBefore(messages, index) {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'user') return messages[i].content;
  }
  return '';
}

const isGrievancePath = () =>
  typeof window !== 'undefined' && window.location.pathname.startsWith('/grievance');

function ChatApp() {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [replayCount, setReplayCount] = useState(0);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const messagesEndRef = useRef(null);

  // Chat History & Session State
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);

  const { user, isAuthenticated } = useAuth();

  // Auto-scroll to bottom of messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Load chat history when user logs in, or clear when user logs out
  useEffect(() => {
    if (!isAuthenticated || !user?.email) {
      setMessages([]);
      setSessions([]);
      setCurrentSessionId(null);
      setIsHistoryDrawerOpen(false);
      return;
    }

    let isCancelled = false;
    async function loadUserHistory() {
      try {
        const userSessions = await fetchChatHistory(user.email);
        if (!isCancelled) {
          setSessions(userSessions);
          if (userSessions.length > 0) {
            const latest = userSessions[0];
            setCurrentSessionId(latest.id);
            setMessages(latest.messages || []);
          }
        }
      } catch (err) {
        console.error('Error loading history:', err);
      }
    }

    loadUserHistory();
    return () => {
      isCancelled = true;
    };
  }, [isAuthenticated, user?.email]);

  // Start a fresh conversation
  const handleNewChat = () => {
    setMessages([]);
    setCurrentSessionId(null);
  };

  // Select an existing conversation from history
  const handleSelectSession = (session) => {
    setCurrentSessionId(session.id);
    setMessages(session.messages || []);
  };

  // Delete a session
  const handleDeleteSession = async (sessionId) => {
    if (!user?.email) return;
    await deleteChatSession(user.email, sessionId);
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    if (currentSessionId === sessionId) {
      handleNewChat();
    }
  };

  // Trigger splash replay
  const handleReplaySplash = () => {
    setReplayCount((prev) => prev + 1);
  };

  // Handle sending messages
  const handleSendMessage = async (messageText) => {
    if (!messageText.trim() || isLoading) return;

    const userMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      timestamp: new Date().toISOString(),
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setIsLoading(true);

    try {
      let response;
      if (API_CONFIG.DEMO_MODE) {
        response = await getDemoResponse(messageText);
      } else {
        const activeEmail = user?.email || API_CONFIG.DEFAULT_USER_EMAIL;
        const recentChatHistory = messages.slice(-6).map((m) => ({
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content,
        }));
        response = await sendMessage(messageText, {
          userEmail: activeEmail,
          chatHistory: recentChatHistory,
        });
      }

      if (response && response.success) {
        const assistantMessage = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: response.data.message,
          sources: response.data.sources || [],
          timestamp: response.data.timestamp || new Date().toISOString(),
        };
        const finalMessages = [...newMessages, assistantMessage];
        setMessages(finalMessages);

        // Auto-save session if authenticated
        if (isAuthenticated && user?.email) {
          try {
            const syncRes = await saveChatSession(
              user.email,
              currentSessionId,
              finalMessages
            );
            if (syncRes && syncRes.session_id) {
              setCurrentSessionId(syncRes.session_id);
              fetchChatHistory(user.email).then(setSessions);
            }
          } catch (syncErr) {
            console.error('Session sync error:', syncErr);
          }
        }
      }
    } catch (error) {
      console.error('Error sending message:', error);
      const isConnectionError =
        error.name === 'TypeError' ||
        error.message?.includes('Failed to fetch') ||
        error.message?.includes('NetworkError') ||
        error.message?.includes('Load failed') ||
        error.message?.includes('timed out') ||
        error.message?.includes('Network request failed');

      const errorText = isConnectionError
        ? 'Server is currently not available. Please ensure the backend server is running.'
        : `⚠️ Error: ${error.message || 'Unable to process your request.'}`;

      const errorMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        isError: true,
        content: errorText,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle document file upload
  const handleFileUpload = async (file) => {
    const uploadNotice = {
      id: Date.now().toString(),
      role: 'user',
      content: `📎 Uploading document: **${file.name}**...`,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, uploadNotice]);
    setIsLoading(true);

    try {
      let res;
      if (API_CONFIG.DEMO_MODE) {
        res = await demoUploadFile(file);
      } else {
        const activeEmail = user?.email || API_CONFIG.DEFAULT_USER_EMAIL;
        res = await uploadFile(file, activeEmail);
      }

      const successNotice = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `✅ Successfully uploaded & indexed **${res.filename || file.name}**! You can now ask questions about its content.`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, successNotice]);
    } catch (error) {
      console.error('Error uploading file:', error);
      const isConnectionError =
        error.name === 'TypeError' ||
        error.message?.includes('Failed to fetch') ||
        error.message?.includes('NetworkError') ||
        error.message?.includes('Load failed') ||
        error.message?.includes('timed out');

      const errorText = isConnectionError
        ? 'Server is currently not available. Please ensure the backend server is running.'
        : `❌ Document upload failed: ${error.message}`;

      const errorNotice = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        isError: true,
        content: errorText,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorNotice]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative w-screen h-screen overflow-hidden flex">
      {/* 1. Gemini-Style Animated Splash Screen */}
      <SplashScreen forceReplay={replayCount} />

      {/* 2. Geometric Background Grid & Ambient Glow */}
      <GeometricBackground />

      {/* 3. Auth Modal */}
      <AuthModal />

      {/* 4. History Drawer */}
      <HistoryDrawer
        isOpen={isHistoryDrawerOpen}
        onClose={() => setIsHistoryDrawerOpen(false)}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
      />

      {/* 5. Static Sidebar Navigation */}
      <Sidebar
        onOpenHistory={() => setIsHistoryDrawerOpen(true)}
        onNewChat={handleNewChat}
        mobileOpen={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
      />

      {/* 6. Main Content Area */}
      <main className="main-content">
        {messages.length === 0 ? (
          // Welcome View: Center Stage with 4 Prompt Cards
          <MainContent
            onSend={handleSendMessage}
            onFileUpload={handleFileUpload}
            disabled={isLoading}
            onReplaySplash={handleReplaySplash}
            onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
          />
        ) : (
          // Active Conversation View
          <div className="w-full h-full flex flex-col justify-between max-w-5xl mx-auto overflow-hidden">
            {/* Top Bar with Replay Intro & New Chat triggers */}
            <div className="top-actions w-full flex items-center justify-between pb-3 flex-shrink-0">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setIsMobileSidebarOpen(true)}
                  className="md:hidden btn-action-ghost"
                  aria-label="Open menu"
                >
                  <Menu className="w-4 h-4" />
                </button>
                <button
                  onClick={handleNewChat}
                  className="btn-action-ghost"
                  title="Start a new conversation"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>New Chat</span>
                </button>
              </div>

              <button
                className="btn-action-ghost"
                id="btnReplaySplash"
                onClick={handleReplaySplash}
                title="Replay Gemini splash entrance animation"
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <polyline points="1 4 1 10 7 10" />
                  <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
                </svg>
                Replay Intro
              </button>
            </div>

            {/* Messages Scroll Area */}
            <div className="flex-1 overflow-y-auto pr-1 py-4 space-y-5">
              {messages.map((msg, index) => (
                <div
                  key={msg.id}
                  className={`flex gap-3 w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'
                    }`}
                >
                  {/* Assistant Avatar */}
                  {msg.role === 'assistant' && (
                    <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-blue-600/15 border border-blue-400/20 flex items-center justify-center text-blue-300 shadow-sm mt-0.5">
                      <svg
                        width="15"
                        height="15"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <polygon points="12 2 2 7 12 12 22 7 12 2" />
                        <polyline points="2 17 12 22 22 17" />
                        <polyline points="2 12 12 17 22 12" />
                      </svg>
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] md:max-w-[78%] rounded-2xl px-5 py-3.5 shadow-lg backdrop-blur-md ${msg.role === 'user'
                        ? 'bg-[#15213b]/90 border border-blue-400/25 text-slate-100 rounded-tr-sm'
                        : msg.isError
                          ? 'bg-red-500/10 border border-red-500/30 text-red-200 rounded-tl-sm'
                          : 'bg-[#0b1224]/85 border border-white/10 text-slate-100 rounded-tl-sm'
                      }`}
                  >
                    {/* Header info */}
                    <div className="flex items-center justify-between gap-4 mb-1.5 text-[11px] font-medium text-slate-400">
                      <span>{msg.role === 'user' ? 'You' : 'Ask AI'}</span>
                      <span className="text-[10px] text-slate-500 font-normal">
                        {new Date(msg.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                    </div>

                    {/* Message Body */}
                    <div className="prose-chat text-sm md:text-base leading-relaxed break-words text-slate-100">
                      {msg.isError ? (
                        <span className="text-red-400">{msg.content}</span>
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                      )}
                    </div>

                    {/* A broken AC or a leaking tap needs somebody to act, not another answer. */}
                    {msg.role === 'assistant' && !msg.isError && (
                      <div className="mt-3 border-t border-white/10 pt-3">
                        <ReportProblemButton text={questionBefore(messages, index)} />
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {/* Reasoning / Thinking Indicator */}
              {isLoading && (
                <div className="flex gap-3 justify-start w-full">
                  <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-blue-600/15 border border-blue-400/20 flex items-center justify-center text-blue-300 shadow-sm mt-0.5">
                    <Sparkles className="w-4 h-4 animate-spin text-blue-400" />
                  </div>
                  <div className="bg-[#0b1224]/85 border border-white/10 rounded-2xl rounded-tl-sm px-5 py-3.5 text-sm text-slate-400 flex items-center gap-2 shadow-lg backdrop-blur-md">
                    <span>Ask AI is reasoning across your documents...</span>
                    <span className="typing-caret" />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Bottom Capsule Input */}
            <div className="pt-2 flex-shrink-0">
              <ChatInput
                onSend={handleSendMessage}
                onFileUpload={handleFileUpload}
                disabled={isLoading}
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function App() {
  // The grievance screens are a full page with their own frame and router, so the chat
  // shell steps aside for them instead of nesting two navigation bars.
  const grievanceMode = isGrievancePath();

  useEffect(() => {
    document.body.classList.toggle('grievance-mode', grievanceMode);
    return () => document.body.classList.remove('grievance-mode');
  }, [grievanceMode]);

  if (grievanceMode) return <GrievanceApp />;

  return (
    <AuthProvider>
      <ChatApp />
    </AuthProvider>
  );
}
