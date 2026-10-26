import { Loader2, CheckCircle2, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import type { DataStep } from '@/stores/researchChatStore';

interface DataStepCardProps {
  step: DataStep;
}

export function DataStepCard({ step }: DataStepCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`mx-4 my-1.5 rounded-xl border text-sm ${
      step.status === 'loading' ? 'border-blue-200 bg-blue-50/50' :
      step.status === 'done'    ? 'border-green-200 bg-green-50/50' :
                                   'border-red-200 bg-red-50/50'
    }`}>
      <button
        onClick={() => step.status !== 'loading' && setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {step.status === 'loading' && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />}
        {step.status === 'done' && <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />}
        {step.status === 'error' && <AlertCircle className="w-3.5 h-3.5 text-red-500" />}
        <span className="font-medium text-gray-700 text-xs">{step.label}</span>
        <span className={`text-[10px] ${
          step.status === 'loading' ? 'text-blue-500' :
          step.status === 'done'    ? 'text-green-600' :
                                      'text-red-500'
        }`}>
          {step.status === 'loading' ? '正在获取数据…' :
           step.status === 'done'    ? '完成' : '获取失败'}
        </span>
        {step.status !== 'loading' && (
          expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 ml-auto" />
            : <ChevronRight className="w-3.5 h-3.5 text-gray-400 ml-auto" />
        )}
      </button>

      {expanded && step.status !== 'loading' && (
        <div className="px-3 pb-2 border-t border-inherit">
          {step.status === 'done' && step.summary && (
            <pre className="mt-2 text-[10px] text-gray-500 whitespace-pre-wrap break-words font-mono leading-relaxed max-h-32 overflow-y-auto">
              {step.summary}
            </pre>
          )}
          {step.status === 'error' && (
            <p className="mt-2 text-[10px] text-red-500">{step.error || '未知错误'}</p>
          )}
        </div>
      )}
    </div>
  );
}
