import { Bot, User } from 'lucide-react';
import { MarkdownContent } from './MarkdownContent';
import type { AgentChatMessage } from '@/types/agent';

interface ChatMessageProps {
  message: AgentChatMessage;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${
          isUser ? 'bg-primary-100 text-primary-600' : 'bg-gray-100 text-gray-600'
        }`}
      >
        {isUser ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
      </div>
      <div className={`flex-1 min-w-0 ${isUser ? 'text-right' : 'text-left'}`}>
        {isUser ? (
          <div className="inline-block max-w-[85%] px-3 py-2 rounded-lg text-sm bg-primary-600 text-white">
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          </div>
        ) : (
          <div className="max-w-full text-sm text-gray-800 leading-relaxed">
            {message.content ? <MarkdownContent content={message.content} /> : null}
            {message.isStreaming && (
              <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse ml-1" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
