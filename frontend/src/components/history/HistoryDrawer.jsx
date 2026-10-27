import { X, Plus, MessageSquare, Trash2, Clock, Calendar } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export default function HistoryDrawer({
  isOpen,
  onClose,
  sessions = [],
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
}) {
  const { isAuthenticated, openAuthModal } = useAuth();

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-40 flex">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity animate-fadeIn"
        onClick={onClose}
      />

      {/* Drawer Panel */}
      <div className="relative w-80 md:w-96 h-full border-r border-white/10 bg-[#070c18]/95 backdrop-blur-2xl text-white z-50 flex flex-col shadow-2xl animate-slideRight">
        {/* Top Header */}
        <div className="p-4 border-b border-white/10 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-white/[0.06] border border-white/10 flex items-center justify-center text-gray-200">
              <Clock className="w-4 h-4" />
            </div>
            <h2 className="font-semibold text-sm tracking-wide text-white">Chat History</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
            aria-label="Close history"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3 border-b border-white/5 flex-shrink-0">
          <button
            onClick={() => {
              onNewChat();
              onClose();
            }}
            className="w-full py-2.5 px-3 rounded-xl bg-white/[0.06] hover:bg-white/[0.12] text-white border border-white/15 text-xs font-semibold flex items-center justify-center gap-2 transition-all hover:scale-[1.01] active:scale-95 shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>Start New Conversation</span>
          </button>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {!isAuthenticated ? (
            <div className="text-center py-12 px-4">
              <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/10 flex items-center justify-center mx-auto mb-3 text-gray-400">
                <MessageSquare className="w-6 h-6 opacity-60" />
              </div>
              <p className="text-xs text-gray-400 mb-4 max-w-xs mx-auto leading-relaxed">
                Sign in to save, sync, and review your document discussions across all sessions.
              </p>
              <button
                onClick={() => {
                  onClose();
                  openAuthModal('login');
                }}
                className="py-2 px-5 rounded-xl bg-white hover:bg-gray-100 text-[#070c18] text-xs font-semibold transition-all shadow-md active:scale-95"
              >
                Sign In Now
              </button>
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-center py-12 px-4 text-gray-500">
              <Clock className="w-8 h-8 mx-auto mb-3 opacity-30 text-gray-400" />
              <p className="text-xs text-gray-400">No chat history yet.</p>
              <p className="text-[11px] text-gray-500 mt-1">
                Start chatting to automatically save your sessions!
              </p>
            </div>
          ) : (
            sessions.map((session) => {
              const isSelected = currentSessionId === session.id;
              const formattedDate = new Date(
                session.updated_at || session.created_at
              ).toLocaleDateString([], {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              });

              return (
                <div
                  key={session.id}
                  className={`group relative flex items-start justify-between p-3 rounded-xl border transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-blue-500/15 border-blue-400/35 text-white shadow-[0_0_15px_rgba(59,130,246,0.15)]'
                      : 'bg-white/[0.03] border-white/[0.07] text-gray-300 hover:bg-white/[0.08] hover:border-white/20 hover:text-white'
                  }`}
                  onClick={() => {
                    onSelectSession(session);
                    onClose();
                  }}
                >
                  <div className="flex-1 min-w-0 pr-2">
                    <p className="text-xs font-semibold truncate leading-tight mb-1 text-white">
                      {session.title || 'Conversation'}
                    </p>
                    <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
                      <Calendar className="w-3 h-3 text-gray-500" />
                      <span>{formattedDate}</span>
                      <span>•</span>
                      <span>{session.messages?.length || 0} msgs</span>
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(session.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
                    title="Delete session"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-white/10 text-center flex-shrink-0 bg-white/[0.01]">
          <p className="text-[10px] text-gray-400">
            Conversations are encrypted & synced with your account.
          </p>
        </div>
      </div>
    </div>
  );
}
