import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="prose prose-sm max-w-none
      prose-headings:text-gray-900
      prose-p:my-1 prose-p:text-gray-700
      prose-ul:my-1 prose-ol:my-1
      prose-li:my-0.5 prose-li:text-gray-700
      prose-pre:my-2 prose-pre:bg-gray-900 prose-pre:border-0
      prose-strong:text-gray-900
      prose-a:text-primary-600 prose-a:no-underline hover:prose-a:underline
      prose-code:text-primary-700
      prose-table:text-xs
    ">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = className?.startsWith('language-');
            if (isBlock) {
              return (
                <code className="text-green-300 font-mono" {...props}>
                  {children}
                </code>
              );
            }
            return (
              <code className="px-1 py-0.5 bg-primary-50 rounded text-[11px] font-mono text-primary-700" {...props}>
                {children}
              </code>
            );
          },
          pre({ children }) {
            return (
              <pre className="p-3 rounded-lg overflow-x-auto max-h-64 leading-relaxed text-xs">
                {children}
              </pre>
            );
          },
          table({ children }) {
            return (
              <div className="overflow-x-auto my-2 -mx-1">
                <table className="min-w-full border border-gray-200 text-[10px]">
                  {children}
                </table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="px-2 py-1 bg-gray-50 border border-gray-200 text-left font-medium text-gray-700">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="px-2 py-1 border border-gray-200 text-gray-600">
                {children}
              </td>
            );
          },
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
