import { useRef } from 'react';

const promptCardsData = [
  {
    id: 'emails',
    title: 'Summarize Emails',
    desc: 'Find important updates regarding deadlines',
    prompt: 'Find important updates regarding upcoming deadlines across my inbox.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
        <polyline points="22,6 12,13 2,6" />
      </svg>
    ),
  },
  {
    id: 'docs',
    title: 'Analyze Documents',
    desc: 'Extract key points from uploaded PDF files',
    prompt: 'Extract the core executive takeaways and analysis from the latest uploaded PDF documents.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    ),
  },
  {
    id: 'receipts',
    title: 'Locate Receipts',
    desc: 'Check hostel allotment, fee dues, or grades',
    prompt: 'Search for hostel fee receipts, room allotment invoices, and semester grade statements.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <rect x="2" y="4" width="20" height="16" rx="2" />
        <line x1="12" y1="8" x2="12" y2="16" />
        <line x1="8" y1="12" x2="16" y2="12" />
      </svg>
    ),
  },
  {
    id: 'draft',
    title: 'Draft Responses',
    desc: 'Compose a professional follow-up email',
    prompt: 'Draft a crisp, respectful, and professional follow-up email regarding the pending inquiry.',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
      </svg>
    ),
  },
];

function PromptCard({ card, onSelect }) {
  const cardRef = useRef(null);

  const handleMouseMove = (e) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    cardRef.current.style.setProperty('--mouse-x', `${x}px`);
    cardRef.current.style.setProperty('--mouse-y', `${y}px`);
  };

  return (
    <div
      ref={cardRef}
      className="prompt-card"
      onMouseMove={handleMouseMove}
      onClick={() => onSelect(card.prompt)}
      data-prompt={card.prompt}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          onSelect(card.prompt);
        }
      }}
    >
      <div className="card-icon-pill">{card.icon}</div>
      <div className="card-title">{card.title}</div>
      <div className="card-desc">{card.desc}</div>
    </div>
  );
}

export default function PromptCardsGrid({ onSelectPrompt }) {
  return (
    <div className="cards-row" id="cardsGrid">
      {promptCardsData.map((card) => (
        <PromptCard key={card.id} card={card} onSelect={onSelectPrompt} />
      ))}
    </div>
  );
}

export { promptCardsData };
