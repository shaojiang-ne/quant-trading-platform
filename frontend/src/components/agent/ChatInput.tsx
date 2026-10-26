import { useState } from 'react';
import { Send, Loader2 } from 'lucide-react';
import type { QuickTemplate } from '@/types/agent';

interface ChatInputProps {
  onSend: (content: string) => void;
  loading: boolean;
  placeholder?: string;
  templates?: QuickTemplate[];
  onTemplateClick?: (template: QuickTemplate) => void;
}

export function ChatInput({
  onSend,
  loading,
  placeholder = '输入你的策略描述...',
  templates,
  onTemplateClick,
}: ChatInputProps) {
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim() || loading) return;
    onSend(input.trim());
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-gray-200 bg-white">
      {templates && templates.length > 0 && (
        <div className="px-3 py-1.5 flex flex-wrap gap-1">
          {templates.map((t) => (
            <button
              key={t.label}
              onClick={() => onTemplateClick?.(t)}
              className={`flex items-center gap-1 px-2 py-0.5 text-xs border rounded-full transition hover:shadow-sm ${t.color}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-2 p-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={2}
          className="flex-1 px-3 py-1.5 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || loading}
          className="px-3 py-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition self-end flex items-center gap-1.5"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          发送
        </button>
      </div>
    </div>
  );
}
