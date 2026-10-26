import { MarkdownContent } from './MarkdownContent';
import type { ResearchChatMessage } from '@/stores/researchChatStore';

interface ChatBubbleProps {
  message: ResearchChatMessage;
}

export function ChatBubble({ message }: ChatBubbleProps) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end px-4 py-1.5">
        <div className="max-w-[80%] px-3.5 py-2.5 rounded-2xl rounded-tr-md bg-primary-600 text-white text-sm leading-relaxed">
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-2.5 px-4 py-1.5">
      <div className="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0 mt-0.5">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary-600">
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-gray-800 leading-relaxed">
          {message.content ? <MarkdownContent content={message.content} /> : null}
          {message.isStreaming && (
            <span className="inline-block w-1 h-4 bg-primary-400 animate-pulse ml-0.5 rounded-sm" />
          )}
        </div>
      </div>
    </div>
  );
}
