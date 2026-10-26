import { Trash2, LogOut } from 'lucide-react';

interface HeaderProps {
  onClear: () => void;
  onLogout: () => void;
  hasMessages: boolean;
}

export function Header({ onClear, onLogout, hasMessages }: HeaderProps) {
  return (
    <header className="flex items-center justify-between px-4 py-3 bg-white border-b border-gray-100 sticky top-0 z-10">
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <h1 className="text-base font-bold text-gray-900">AI股票研究助手</h1>
      </div>
      <div className="flex items-center gap-1.5">
        {hasMessages && (
          <button
            onClick={onClear}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-500 bg-gray-100 rounded-lg active:bg-gray-200 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            清空
          </button>
        )}
        <button
          onClick={onLogout}
          className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-500 bg-gray-100 rounded-lg active:bg-gray-200 transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          退出
        </button>
      </div>
    </header>
  );
}
