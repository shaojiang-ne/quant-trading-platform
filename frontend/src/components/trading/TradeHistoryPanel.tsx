import { useState } from 'react';
import { useLiveTradingStore } from '@/stores/liveTradingStore';

/** 格式化时间字符串：支持 "2025-05-13T09:30:00"、"20250513093000"、时间戳等 */
function formatTime(raw: string | number): string {
  if (!raw) return '--';
  const s = String(raw);
  // ISO 格式: 2025-05-13T09:30:00 或 2025-05-13 09:30:00
  const isoMatch = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/);
  if (isoMatch) return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]} ${isoMatch[4]}:${isoMatch[5]}:${isoMatch[6]}`;
  // 紧凑格式: 20250513093000
  const compactMatch = s.match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/);
  if (compactMatch) return `${compactMatch[1]}-${compactMatch[2]}-${compactMatch[3]} ${compactMatch[4]}:${compactMatch[5]}:${compactMatch[6]}`;
  // 纯数字时间戳（毫秒或秒）
  const num = Number(s);
  if (!isNaN(num) && num > 1e9) {
    const ms = num > 1e12 ? num : num * 1000;
    const d = new Date(ms);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
  }
  return s;
}

export function TradeHistoryPanel() {
  const { orders, trades, cancelOrder, fetchOrders } = useLiveTradingStore();
  const [tab, setTab] = useState<'orders' | 'trades'>('orders');

  const handleCancel = async (orderId: string) => {
    await cancelOrder(orderId);
    fetchOrders();
  };

  const statusLabel = (status: string) => {
    switch (status) {
      case 'filled': return '已成交';
      case 'pending': case 'submitted': return '待成交';
      case 'partial': return '部分成交';
      case 'cancelled': return '已撤单';
      case 'rejected': return '已拒绝';
      default: return status;
    }
  };

  const statusCls = (status: string) => {
    switch (status) {
      case 'filled': return 'bg-green-50 text-green-600';
      case 'pending': case 'submitted': return 'bg-amber-50 text-amber-600';
      case 'partial': return 'bg-blue-50 text-blue-600';
      case 'cancelled': return 'bg-gray-100 text-gray-500';
      case 'rejected': return 'bg-red-50 text-red-500';
      default: return 'bg-gray-100 text-gray-500';
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setTab('orders')}
          className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
            tab === 'orders' ? 'text-primary-600 border-b-2 border-primary-600 bg-primary-50/50' : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          委托记录
          {orders.length > 0 && <span className="ml-1.5 px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{orders.length}</span>}
        </button>
        <button
          onClick={() => setTab('trades')}
          className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
            tab === 'trades' ? 'text-primary-600 border-b-2 border-primary-600 bg-primary-50/50' : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          成交记录
          {trades.length > 0 && <span className="ml-1.5 px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{trades.length}</span>}
        </button>
      </div>

      {tab === 'orders' && (
        <div className="p-4">
          {orders.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-200">
                    <th className="text-left py-2 px-2">时间</th>
                    <th className="text-left py-2 px-2">标的</th>
                    <th className="text-center py-2 px-2">方向</th>
                    <th className="text-right py-2 px-2">委托价</th>
                    <th className="text-right py-2 px-2">成交价</th>
                    <th className="text-right py-2 px-2">委托/成交</th>
                    <th className="text-center py-2 px-2">状态</th>
                    <th className="text-center py-2 px-2">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {orders.map((order) => (
                    <tr key={order.order_id}>
                      <td className="py-2 px-2 text-gray-500 font-mono whitespace-nowrap">{formatTime(order.create_time)}</td>
                      <td className="py-2 px-2 text-gray-900">
                        {order.symbol}
                        {order.name && <span className="text-gray-400 ml-1">{order.name}</span>}
                      </td>
                      <td className={`py-2 px-2 text-center font-medium ${order.side === 'buy' ? 'text-red-500' : 'text-green-500'}`}>
                        {order.side === 'buy' ? '买入' : '卖出'}
                      </td>
                      <td className="py-2 px-2 text-right text-gray-900 font-mono">
                        {order.price != null ? order.price.toFixed(2) : '-'}
                      </td>
                      <td className="py-2 px-2 text-right text-gray-900 font-mono">
                        {order.filled_quantity > 0 && order.filled_price > 0 ? order.filled_price.toFixed(2) : '-'}
                      </td>
                      <td className="py-2 px-2 text-right text-gray-700 font-mono">
                        {order.filled_quantity}/{order.quantity}
                      </td>
                      <td className="py-2 px-2 text-center">
                        <span className={`px-1.5 py-0.5 rounded text-xs ${statusCls(order.status)}`}>
                          {statusLabel(order.status)}
                        </span>
                      </td>
                      <td className="py-2 px-2 text-center">
                        {(order.status === 'pending' || order.status === 'submitted') && (
                          <button onClick={() => handleCancel(order.order_id)} className="text-red-500 hover:text-red-600 font-medium">撤单</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-gray-400 text-xs text-center py-8">暂无委托记录</div>
          )}
        </div>
      )}

      {tab === 'trades' && (
        <div className="p-4">
          {trades.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-200">
                    <th className="text-left py-2 px-2">时间</th>
                    <th className="text-left py-2 px-2">标的</th>
                    <th className="text-center py-2 px-2">方向</th>
                    <th className="text-right py-2 px-2">成交价</th>
                    <th className="text-right py-2 px-2">成交量</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {trades.map((trade, i) => (
                    <tr key={trade.trade_id || i}>
                      <td className="py-2 px-2 text-gray-500 font-mono whitespace-nowrap">{formatTime(trade.time)}</td>
                      <td className="py-2 px-2 text-gray-900">
                        {trade.symbol}
                        {trade.name && <span className="text-gray-400 ml-1">{trade.name}</span>}
                      </td>
                      <td className={`py-2 px-2 text-center font-medium ${trade.side === 'buy' ? 'text-red-500' : 'text-green-500'}`}>
                        {trade.side === 'buy' ? '买入' : '卖出'}
                      </td>
                      <td className="py-2 px-2 text-right text-gray-900 font-mono">{trade.price.toFixed(2)}</td>
                      <td className="py-2 px-2 text-right text-gray-700 font-mono">{trade.quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-gray-400 text-xs text-center py-8">暂无成交记录</div>
          )}
        </div>
      )}
    </div>
  );
}