import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  Clock,
  Search,
  Lightbulb,
  Puzzle,
  Settings,
  Plus,
  LogOut,
  LogIn,
  CheckCircle,
  ShieldAlert,
  X,
} from 'lucide-react';

export default function Sidebar({
  onOpenHistory,
  onNewChat,
  mobileOpen = false,
  onCloseMobile,
}) {
  const [activeItem, setActiveItem] = useState('new-chat');
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const { user, isAuthenticated, openAuthModal, logout } = useAuth();

  const handleNavClick = (id, e) => {
    e?.preventDefault();
    setActiveItem(id);
    if (id === 'history') {
      onOpenHistory?.();
    } else if (id === 'new-chat') {
      onNewChat?.();
    }
    if (onCloseMobile) {
      onCloseMobile();
    }
  };

  const handleAccountClick = () => {
    if (!isAuthenticated) {
      openAuthModal('login');
    } else {
      setIsProfileMenuOpen(!isProfileMenuOpen);
    }
  };

  // Determine avatar letter and info
  const avatarLetter = (
    user?.name?.[0] ||
    user?.email?.[0] ||
    'P'
  ).toUpperCase();
  const accountName = user?.name || (isAuthenticated ? 'Parth' : 'Account');
  const accountSub =
    user?.email || 'parthsuryawanshi0207@gmail.com';

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-30 md:hidden"
          onClick={onCloseMobile}
        />
      )}

      <aside
        className={`sidebar ${
          mobileOpen ? 'mobile-open' : ''
        }`}
      >
        {/* Mobile close button */}
        <div className="md:hidden flex justify-end mb-2">
          <button
            onClick={onCloseMobile}
            className="p-1 rounded text-gray-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* STATIC LOGO (NO ANIMATION LOOPS) */}
        <div className="brand-slot">
          <svg
            className="static-logo-svg"
            viewBox="0 0 600 360"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <marker
                id="micro-arrow-static"
                viewBox="0 0 16 16"
                refX="11.2"
                refY="8"
                markerWidth="5.6"
                markerHeight="5.6"
                orient="auto"
              >
                <path d="M 2.5,3.2 L 13.5,8 L 2.5,12.8 L 4.2,8 Z" fill="#ffffff" />
              </marker>
            </defs>

            {/* Static continuous ribbon track */}
            <path
              d="M 374,80 C 440,32 535,62 535,138 C 535,218 438,226 300,140 C 162,54 65,62 65,142 C 65,222 155,232 232,168"
              fill="none"
              stroke="#ffffff"
              strokeWidth="13"
              strokeLinecap="round"
              strokeLinejoin="round"
              markerEnd="url(#micro-arrow-static)"
            />

            {/* Static bead dot */}
            <circle cx="374" cy="80" r="11" fill="#ffffff" />

            {/* Static Typography */}
            <text
              x="300"
              y="325"
              fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Arial Black', sans-serif"
              fontWeight="900"
              fontSize="52"
              letterSpacing="8"
              fill="#ffffff"
              textAnchor="middle"
            >
              ASK AI
            </text>
          </svg>
        </div>

        {/* New Chat Trigger */}
        <button
          className="btn-new-chat"
          id="btnNewChat"
          onClick={(e) => handleNavClick('new-chat', e)}
        >
          <Plus className="w-4 h-4 stroke-[2.2]" />
          New Chat
        </button>

        {/* Nav Items */}
        <nav className="nav-links">
          {/* A real page, not a panel: a full navigation, so the grievance router takes over. */}
          <a
            href="/grievance"
            className="nav-item"
            onClick={() => onCloseMobile?.()}
          >
            <ShieldAlert className="w-4 h-4" />
            Grievance
          </a>
          <a
            href="#history"
            className={`nav-item ${activeItem === 'history' ? 'active' : ''}`}
            onClick={(e) => handleNavClick('history', e)}
          >
            <Clock className="w-4 h-4" />
            History
          </a>
          <a
            href="#search"
            className={`nav-item ${activeItem === 'search' ? 'active' : ''}`}
            onClick={(e) => handleNavClick('search', e)}
          >
            <Search className="w-4 h-4" />
            Search
          </a>
          <a
            href="#ideas"
            className={`nav-item ${activeItem === 'ideas' ? 'active' : ''}`}
            onClick={(e) => handleNavClick('ideas', e)}
          >
            <Lightbulb className="w-4 h-4" />
            Ideas
          </a>
          <a
            href="#plugins"
            className={`nav-item ${activeItem === 'plugins' ? 'active' : ''}`}
            onClick={(e) => handleNavClick('plugins', e)}
          >
            <Puzzle className="w-4 h-4" />
            Plugins
          </a>
          <a
            href="#settings"
            className={`nav-item ${activeItem === 'settings' ? 'active' : ''}`}
            onClick={(e) => handleNavClick('settings', e)}
          >
            <Settings className="w-4 h-4" />
            Settings
          </a>
        </nav>

        {/* User Account Badge */}
        <div className="relative">
          {/* Profile Dropdown */}
          {isProfileMenuOpen && (
            <div
              className="absolute bottom-16 left-0 right-0 p-3 rounded-xl border border-white/10 shadow-2xl bg-[#0a1122]/95 text-gray-200 z-50 text-xs backdrop-blur-2xl"
            >
              <div className="mb-2 pb-2 border-b border-white/10">
                <p className="font-semibold text-white truncate">{accountName}</p>
                <p className="text-gray-400 truncate text-[11px]">{accountSub}</p>
                {isAuthenticated && (
                  <div className="mt-1 flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
                    <CheckCircle className="w-3 h-3" />
                    <span>Verified Session</span>
                  </div>
                )}
              </div>
              {isAuthenticated ? (
                <button
                  onClick={() => {
                    logout();
                    setIsProfileMenuOpen(false);
                  }}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors font-medium text-left"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Log Out</span>
                </button>
              ) : (
                <button
                  onClick={() => {
                    openAuthModal('login');
                    setIsProfileMenuOpen(false);
                  }}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-white hover:bg-white/10 transition-colors font-medium text-left"
                >
                  <LogIn className="w-3.5 h-3.5" />
                  <span>Sign In</span>
                </button>
              )}
            </div>
          )}

          <div
            className="account-badge cursor-pointer hover:border-white/20 transition-colors"
            onClick={handleAccountClick}
            role="button"
            tabIndex={0}
            title={isAuthenticated ? 'Account Profile' : 'Click to Log In'}
          >
            <div className="account-avatar">{avatarLetter}</div>
            <div className="account-info">
              <div className="account-name">{accountName}</div>
              <div className="account-sub" title={accountSub}>
                {accountSub}
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
