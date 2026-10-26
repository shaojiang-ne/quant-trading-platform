import { Send, Loader2 } from 'lucide-react';

interface ChatInputProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled: boolean;
  placeholder?: string;
  scenarioLabel?: string | null;
}

export function ChatInput({ value, onChange, onSend, disabled, placeholder, scenarioLabel }: ChatInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="border-t border-gray-100 bg-white px-3 py-2 safe-area-bottom">
      {scenarioLabel && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="text-[10px] text-primary-700 font-medium bg-primary-50 px-2 py-0.5 rounded-full">
            {scenarioLabel}
          </span>
          <span className="text-[10px] text-gray-400">— 发送时自动获取数据</span>
        </div>
      )}
      <div className="flex gap-2 items-end">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || '输入问题，如「帮我估一下 688017」…'}
          rows={1}
          className="flex-1 px-3 py-2 bg-gray-100 border-0 rounded-xl text-sm text-gray-900 placeholder:text-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-primary-500/30 transition-shadow"
          disabled={disabled}
          style={{ minHeight: 40, maxHeight: 100 }}
        />
        <button
          onClick={onSend}
          disabled={!value.trim() || disabled}
          className="w-10 h-10 flex items-center justify-center rounded-xl bg-primary-600 text-white disabled:opacity-30 disabled:cursor-not-allowed active:bg-primary-700 transition-colors"
        >
          {disabled ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}
