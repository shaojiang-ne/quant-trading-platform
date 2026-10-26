import type { ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { PanelKey } from '@/types/agent';

interface PanelHeaderProps {
  title: string;
  icon: ReactNode;
  panelKey: PanelKey;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  actions?: ReactNode;
}

export function PanelHeader({
  title,
  icon,
  isCollapsed,
  onToggleCollapse,
  actions,
}: PanelHeaderProps) {
  if (isCollapsed) {
    return (
      <div className="w-full h-full flex flex-col items-center py-3 gap-2">
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
          title={`展开${title}`}
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        <div className="text-primary-600">{icon}</div>
        <span className="text-xs text-gray-500 writing-mode-vertical" style={{ writingMode: 'vertical-rl' }}>
          {title}
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 bg-gray-50 flex-shrink-0">
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleCollapse}
          className="p-1 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
          title={`折叠${title}`}
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-primary-600">{icon}</span>
        <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
      </div>
      {actions && <div className="flex items-center gap-1">{actions}</div>}
    </div>
  );
}
