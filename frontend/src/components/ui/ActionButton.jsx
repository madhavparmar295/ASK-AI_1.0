import { MailSearch, FileText, Receipt, SendHorizontal } from 'lucide-react';

const actionButtons = [
  {
    id: 'emails',
    icon: MailSearch,
    title: 'Summarize Emails',
    description: 'Find important updates regarding deadlines',
  },
  {
    id: 'docs',
    icon: FileText,
    title: 'Analyze Documents',
    description: 'Extract key points from uploaded PDF files',
  },
  {
    id: 'invoices',
    icon: Receipt,
    title: 'Locate Receipts',
    description: 'Check hostel allotment, fee dues, or grades',
  },
  {
    id: 'draft',
    icon: SendHorizontal,
    title: 'Draft Responses',
    description: 'Compose a professional follow-up email',
  },
];

export default function ActionButton({ button, onClick }) {
  const Icon = button.icon;

  return (
    <button
      onClick={() => onClick?.(button)}
      className="group relative w-full rounded-2xl p-3 md:p-4 text-left transition-all duration-200 bg-[#141624]/70 hover:bg-[#1a1d2e] border border-white/5 hover:border-purple-500/30 active:scale-[0.98] shadow-sm flex flex-col justify-between h-full min-h-[95px] md:min-h-[110px]"
    >
      {/* Subtle hover glow behind card */}
      <div className="absolute inset-0 rounded-2xl bg-purple-500/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />

      {/* Content */}
      <div className="relative flex flex-col gap-2.5">
        {/* Icon */}
        <div className="w-8 h-8 rounded-xl bg-purple-500/15 flex items-center justify-center text-purple-300 group-hover:bg-purple-500/25 transition-colors">
          <Icon className="w-4 h-4" />
        </div>

        {/* Text */}
        <div>
          <h3 className="text-xs font-semibold text-white mb-0.5 tracking-wide">{button.title}</h3>
          <p className="text-[11px] text-gray-400 leading-snug line-clamp-2">{button.description}</p>
        </div>
      </div>
    </button>
  );
}

export { actionButtons };
