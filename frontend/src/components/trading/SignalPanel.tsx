import { useEffect, useRef } from 'react';
import { useLiveTradingStore } from '@/stores/liveTradingStore';
import type { SignalInfo } from '@/api/trading';

/** 用 Web Audio API 播放提示音 */
function playAlertSound() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    osc.type = 'sine';
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch {
    // 浏览器不支持 Web Audio API，静默忽略
  }
}

export function SignalPanel() {
  const { signals, fetchSignals, confirmSignal, rejectSignal } = useLiveTradingStore();
  const prevSignalIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    fetchSignals();
    const timer = setInterval(fetchSignals, 5000);
    return () => clearInterval(timer);
  }, [fetchSignals]);

  // 新信号出现时播放提示音
  useEffect(() => {
    const currentIds = new Set(signals.map((s: SignalInfo) => s.id));
    const hasNew = [...currentIds].some((id) => !prevSignalIds.current.has(id));
    if (hasNew && prevSignalIds.current.size > 0) {
      playAlertSound();
    }
    prevSignalIds.current = currentIds;
  }, [signals]);

  if (signals.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <h3 className="text-sm font-medium text-gray-700 mb-3">待确认信号</h3>
        <div className="text-xs text-gray-400 text-center py-4">暂无待确认信号</div>
      </div>
    );
  }

  const sideLabel = (side: string) => side === 'buy' ? '买入' : '卖出';
  const sideColor = (side: string) => side === 'buy' ? 'text-red-600' : 'text-green-600';

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      <h3 className="text-sm font-medium text-gray-700 mb-3">
        待确认信号
        <span className="ml-1.5 px-1.5 py-0.5 bg-yellow-50 text-yellow-700 rounded text-[10px] font-medium">{signals.length}</span>
      </h3>

      <div className="space-y-2">
        {signals.map((sig: SignalInfo) => (
          <div key={sig.id} className="px-3 py-2.5 bg-gray-50 rounded-lg text-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900">{sig.symbol}</span>
                <span className={`font-bold ${sideColor(sig.side)}`}>{sideLabel(sig.side)}</span>
                <span className="text-gray-500">{sig.name}</span>
              </div>
              <div className="text-gray-400 text-[10px]">
                {new Date(sig.created_at).toLocaleString()}
              </div>
            </div>
            <div className="flex items-center justify-between mt-1.5">
              <div className="text-gray-500">
                价格 <span className="text-gray-900 font-medium">{sig.price.toFixed(2)}</span>
                {' · '}
                数量 <span className="text-gray-900 font-medium">{sig.quantity}</span>
                {' · '}
                金额 <span className="text-gray-900 font-medium">{(sig.price * sig.quantity).toLocaleString()}</span>
              </div>
              <div className="flex gap-1.5">
                <button onClick={() => confirmSignal(sig.id)}
                  className="px-2.5 py-1 bg-primary-600 hover:bg-primary-700 text-white rounded text-[10px] font-medium transition-colors">
                  确认下单
                </button>
                <button onClick={() => rejectSignal(sig.id)}
                  className="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded text-[10px] font-medium transition-colors">
                  拒绝
                </button>
              </div>
            </div>
            {sig.reason && (
              <div className="mt-2 p-2 bg-white rounded text-[10px] font-mono text-gray-600 space-y-1">
                {sig.reason.split('|').map((part, i) => {
                  const trimmed = part.trim();
                  if (!trimmed) return null;
                  const isIndicator = /^(MA|EMA|RSI|DIF|DEA|HIST|中轨|上轨|下轨|K=|D=|J=|CCI|ATR|动量|量MA|价格MA|入场|出场|网格|上界|下界)/.test(trimmed);
                  return (
                    <div key={i} className={isIndicator ? 'text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded' : ''}>
                      {trimmed}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
