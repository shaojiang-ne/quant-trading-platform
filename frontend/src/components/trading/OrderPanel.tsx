import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';

interface OrderPanelProps {
  symbol: string;  // 空字符串时显示输入框
  onPlaceOrder: (symbol: string, side: string, quantity: number, price: number, orderType: string) => Promise<void>;
}

export function OrderPanel({ symbol: initialSymbol, onPlaceOrder }: OrderPanelProps) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [quantity, setQuantity] = useState(100);
  const [price, setPrice] = useState(0);
  const [orderType, setOrderType] = useState('market');
  const [loading, setLoading] = useState(false);

  // 确认弹窗状态
  const [confirm, setConfirm] = useState<{
    visible: boolean;
    side: string;
    quantity: number;
    price: number;
    orderType: string;
  }>({ visible: false, side: '', quantity: 0, price: 0, orderType: '' });

  const handleSubmit = () => {
    if (quantity <= 0) return;
    if (orderType === 'limit' && price <= 0) return;
    if (!symbol) return;
    // 科创板(688)允许1股，其余A股必须100股整数倍
    const isKcb = symbol.startsWith('688');
    if (!isKcb && quantity % 100 !== 0) return;
    setConfirm({
      visible: true,
      side,
      quantity,
      price: orderType === 'market' ? 0 : price,
      orderType,
    });
  };

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await onPlaceOrder(symbol, confirm.side, confirm.quantity, confirm.price, confirm.orderType);
      setConfirm((c) => ({ ...c, visible: false }));
    } finally {
      setLoading(false);
    }
  };

  const isBuy = confirm.side === 'buy';
  const needSymbolInput = !initialSymbol;

  return (
    <>
      <div className="space-y-3">
        {/* 股票代码输入 */}
        {needSymbolInput && (
          <div>
            <label className="text-xs text-gray-500">股票代码</label>
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="如 600519"
              className="w-full mt-1 px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono"
            />
          </div>
        )}
        {/* 方向 */}
        <div className="flex gap-2">
          <button
            onClick={() => setSide('buy')}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
              side === 'buy'
                ? 'bg-red-500 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            买入
          </button>
          <button
            onClick={() => setSide('sell')}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
              side === 'sell'
                ? 'bg-green-500 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            卖出
          </button>
        </div>

        {/* 委托类型 */}
        <div className="flex gap-2">
          <button
            onClick={() => setOrderType('market')}
            className={`px-3 py-1.5 rounded text-xs transition ${
              orderType === 'market'
                ? 'bg-blue-50 text-blue-600 border border-blue-200'
                : 'bg-gray-50 text-gray-500 border border-gray-200'
            }`}
          >
            市价
          </button>
          <button
            onClick={() => setOrderType('limit')}
            className={`px-3 py-1.5 rounded text-xs transition ${
              orderType === 'limit'
                ? 'bg-blue-50 text-blue-600 border border-blue-200'
                : 'bg-gray-50 text-gray-500 border border-gray-200'
            }`}
          >
            限价
          </button>
        </div>

        {/* 数量 */}
        <div>
          <label className="text-xs text-gray-500">数量</label>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            className="w-full mt-1 px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono"
            min={1}
          />
        </div>

        {/* 限价 */}
        {orderType === 'limit' && (
          <div>
            <label className="text-xs text-gray-500">价格</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(Number(e.target.value))}
              className="w-full mt-1 px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono"
              min={0}
              step={0.01}
            />
          </div>
        )}

        {/* 提交 */}
        <button
          onClick={handleSubmit}
          disabled={loading || !symbol || quantity <= 0 || (orderType === 'limit' && price <= 0)}
          className={`w-full py-2.5 rounded-lg text-sm font-medium text-white transition disabled:opacity-50 ${
            side === 'buy' ? 'bg-red-500 hover:bg-red-600' : 'bg-green-500 hover:bg-green-600'
          }`}
        >
          {loading ? '提交中...' : side === 'buy' ? '确认买入' : '确认卖出'}
        </button>
      </div>

      {/* 确认弹窗 */}
      {confirm.visible && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-80 p-6 space-y-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className={`w-5 h-5 ${isBuy ? 'text-red-500' : 'text-green-500'}`} />
              <h3 className="font-semibold text-gray-900">确认下单</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">股票</span>
                <span className="font-mono">{symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">方向</span>
                <span className={isBuy ? 'text-red-500 font-medium' : 'text-green-500 font-medium'}>
                  {isBuy ? '买入' : '卖出'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">数量</span>
                <span className="font-mono">{confirm.quantity}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">类型</span>
                <span>{confirm.orderType === 'market' ? '市价' : '限价'}</span>
              </div>
              {confirm.orderType === 'limit' && (
                <div className="flex justify-between">
                  <span className="text-gray-500">价格</span>
                  <span className="font-mono">{confirm.price.toFixed(2)}</span>
                </div>
              )}
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirm((c) => ({ ...c, visible: false }))}
                className="flex-1 py-2 rounded-lg bg-gray-100 text-gray-700 text-sm hover:bg-gray-200 transition"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                disabled={loading}
                className={`flex-1 py-2 rounded-lg text-white text-sm transition disabled:opacity-50 ${
                  isBuy ? 'bg-red-500 hover:bg-red-600' : 'bg-green-500 hover:bg-green-600'
                }`}
              >
                {loading ? '提交中...' : '确认'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
