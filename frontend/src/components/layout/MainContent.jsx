import PromptCardsGrid from '../ui/PromptCardsGrid';
import ChatInput from '../ui/ChatInput';
import { useAuth } from '../../context/AuthContext';
import { Menu, Sparkles, LogIn } from 'lucide-react';

export default function MainContent({
  onSend,
  onFileUpload,
  disabled = false,
  onReplaySplash,
  onOpenMobileSidebar,
}) {
  const { user, isAuthenticated, openAuthModal } = useAuth();
  const displayName = user?.name ? user.name.split(' ')[0] : null;

  return (
    <div className="flex-1 flex flex-col justify-between items-center w-full max-w-5xl mx-auto px-4 sm:px-6 py-6 overflow-y-auto">
      {/* Top action bar: Mobile menu button (on mobile) & Replay Intro button */}
      <div className="top-actions w-full flex items-center justify-between">
        <button
          onClick={onOpenMobileSidebar}
          className="md:hidden btn-action-ghost"
          aria-label="Open navigation menu"
        >
          <Menu className="w-4 h-4" />
          <span>Menu</span>
        </button>

        <div className="ml-auto">
          <button
            className="btn-action-ghost"
            id="btnReplaySplash"
            onClick={onReplaySplash}
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
      </div>

      {/* Center Stage Container */}
      <div className="center-stage w-full my-auto py-8">
        <h1 className="greeting-title">
          Hello{isAuthenticated && displayName ? `, ${displayName}` : ''},
        </h1>
        <h2 className="greeting-subtitle">How can I help you today?</h2>

        {/* Guest sign-in badge if unauthenticated */}
        {!isAuthenticated && (
          <button
            onClick={() => openAuthModal('login')}
            className="mb-6 inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.04] hover:bg-white/[0.08] text-gray-300 border border-white/10 text-xs font-medium transition-all hover:scale-[1.02] active:scale-95"
          >
            <Sparkles className="w-3.5 h-3.5 text-white/70" />
            <span>Sign in to access personalized emails & private files</span>
            <LogIn className="w-3.5 h-3.5 opacity-60 ml-0.5" />
          </button>
        )}

        {/* 4 Predefined Cards with dynamic cursor spotlight */}
        <PromptCardsGrid onSelectPrompt={onSend} />
      </div>

      {/* Floating Capsule Input Bar */}
      <ChatInput
        onSend={onSend}
        onFileUpload={onFileUpload}
        disabled={disabled}
      />
    </div>
  );
}
