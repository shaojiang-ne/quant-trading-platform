import { useState, useEffect, useRef } from 'react';
import { Eye, EyeOff, ChevronDown, X } from 'lucide-react';
import { useLiveTradingStore } from '@/stores/liveTradingStore';
import type { BrokerInfo } from '@/api/trading';

/** 需要输入账号密码的券商 */
const BROKERS_NEED_CREDENTIALS = ['xtp_cjzq', 'xtp_ztzq', 'xtp_dfzq', 'xtp_ctzq', 'xtp_hxzq', 'xtp_gszq', 'xtp_ykzq', 'ht', 'ths', 'gtja', 'hundsun'];
/** 需要 XTP 额外参数的券商 */
const BROKERS_NEED_XTP = ['xtp_cjzq', 'xtp_ztzq', 'xtp_dfzq', 'xtp_ctzq', 'xtp_hxzq', 'xtp_gszq', 'xtp_ykzq'];
/** 需要交易服务器地址的券商 */
const BROKERS_NEED_TD_ADDRESS = ['gtja', 'hundsun'];

function BrokerConnectForm({
  broker,
  onConnect,
  onCancel,
}: {
  broker: BrokerInfo;
  onConnect: (params: Record<string, string>) => void;
  onCancel: () => void;
}) {
  const [userid, setUserid] = useState('');
  const [password, setPassword] = useState('');
  const [tdAddress, setTdAddress] = useState('');
  const [mdAddress, setMdAddress] = useState('');
  const [brokerId, setBrokerId] = useState('');
  const [appId, setAppId] = useState('');
  const [softwareKey, setSoftwareKey] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const needXtp = BROKERS_NEED_XTP.includes(broker.name);
  const needTdAddress = BROKERS_NEED_TD_ADDRESS.includes(broker.name);

  const handleSubmit = () => {
    if (!userid || !password) return;
    const params: Record<string, string> = { userid, password };
    if (needXtp) {
      if (tdAddress) params.td_address = tdAddress;
      if (mdAddress) params.md_address = mdAddress;
      if (brokerId) params.broker_id = brokerId;
      if (appId) params.app_id = appId;
      if (softwareKey) params.software_key = softwareKey;
    }
    if (needTdAddress && tdAddress) {
      params.td_address = tdAddress;
    }
    onConnect(params);
  };

  return (
    <div className="mt-3 p-3 bg-gray-50 rounded-lg border border-gray-200 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">连接 {broker.display_name}</span>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">
          <X className="w-4 h-4" />
        </button>
      </div>

      <input
        type="text"
        placeholder="资金账号"
        value={userid}
        onChange={(e) => setUserid(e.target.value)}
        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
      <div className="relative">
        <input
          type={showPassword ? 'text' : 'password'}
          placeholder="交易密码"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500 pr-8"
        />
        <button
          type="button"
          onClick={() => setShowPassword(!showPassword)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        >
          {showPassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
        </button>
      </div>

      {needXtp && (
        <>
          <input
            type="text"
            placeholder="交易服务器 (如 tcp://1.2.3.4:8001)"
            value={tdAddress}
            onChange={(e) => setTdAddress(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <input
            type="text"
            placeholder="行情服务器 (如 tcp://1.2.3.4:8002)"
            value={mdAddress}
            onChange={(e) => setMdAddress(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <input
            type="text"
            placeholder="经纪商代码"
            value={brokerId}
            onChange={(e) => setBrokerId(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <input
            type="text"
            placeholder="产品名称/AppID"
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <input
            type="text"
            placeholder="授权编码 SoftwareKey"
            value={softwareKey}
            onChange={(e) => setSoftwareKey(e.target.value)}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </>
      )}

      {needTdAddress && !needXtp && (
        <input
          type="text"
          placeholder="交易服务器地址"
          value={tdAddress}
          onChange={(e) => setTdAddress(e.target.value)}
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      )}

      <button
        onClick={handleSubmit}
        disabled={!userid || !password}
        className="w-full px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-md text-sm font-medium transition-colors"
      >
        连接
      </button>
    </div>
  );
}

export function GatewayPanel() {
  const {
    connected, connecting, accountId, connectError,
    brokerDisplayName, brokers,
    connect, disconnect,
  } = useLiveTradingStore();

  const [showAccountId, setShowAccountId] = useState(false);
  const [showBrokerSelect, setShowBrokerSelect] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState<BrokerInfo | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    useLiveTradingStore.getState().loadBrokers();
  }, []);

  // 点击外部关闭下拉
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowBrokerSelect(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const maskedId = accountId ? accountId.slice(0, 3) + '***' + accountId.slice(-3) : '';

  const handleQuickConnect = (broker: BrokerInfo) => {
    // QMT 不需要额外参数，直接连接
    if (!BROKERS_NEED_CREDENTIALS.includes(broker.name)) {
      connect(broker.name);
      setShowBrokerSelect(false);
      return;
    }
    // 需要凭证的券商，显示表单
    setSelectedBroker(broker);
    setShowBrokerSelect(false);
  };

  const handleCredentialConnect = (xtpParams: Record<string, string>) => {
    if (selectedBroker) {
      connect(selectedBroker.name, xtpParams);
      setSelectedBroker(null);
    }
  };

  // 按分类分组
  const categories = brokers.reduce<Record<string, BrokerInfo[]>>((acc, b) => {
    const cat = (b as any).category || '其他';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(b);
    return acc;
  }, {});

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className={`w-3 h-3 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-gray-300'}`} />
          <div>
            <div className="text-gray-900 font-medium">
              实盘交易
              {brokerDisplayName && (
                <span className="ml-2 text-xs font-normal text-gray-500">({brokerDisplayName})</span>
              )}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {connected
                ? (
                  <span className="inline-flex items-center gap-1">
                    已连接 — 账户
                    <span className="font-mono">{showAccountId ? accountId : maskedId}</span>
                    <button
                      onClick={() => setShowAccountId(!showAccountId)}
                      className="text-gray-400 hover:text-gray-600 transition-colors"
                    >
                      {showAccountId ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    </button>
                  </span>
                )
                : '未连接 — 选择券商并连接'}
            </div>
            {connectError && !connected && (
              <div className="text-xs text-red-500 mt-1">{connectError}</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {!connected ? (
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => { setShowBrokerSelect(!showBrokerSelect); setSelectedBroker(null); }}
                disabled={connecting}
                className="px-4 py-1.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors inline-flex items-center gap-1.5"
              >
                {connecting ? '连接中...' : (
                  <>
                    连接
                    <ChevronDown className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
              {showBrokerSelect && !connecting && (
                <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-10 min-w-[220px] max-h-[360px] overflow-y-auto">
                  {Object.entries(categories).map(([cat, items]) => (
                    <div key={cat}>
                      <div className="px-4 py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wider">
                        {cat}
                      </div>
                      {items.map((b) => (
                        <button
                          key={b.name}
                          onClick={() => handleQuickConnect(b)}
                          className="w-full px-4 py-2 text-left text-sm hover:bg-gray-50 flex items-center justify-between"
                        >
                          <span className="text-gray-900">{b.display_name}</span>
                          {!b.available && (
                            <span className="text-xs text-gray-400">未就绪</span>
                          )}
                        </button>
                      ))}
                    </div>
                  ))}
                  {brokers.length === 0 && (
                    <div className="px-4 py-2.5 text-sm text-gray-400">加载中...</div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={disconnect}
              className="px-4 py-1.5 bg-red-500 hover:bg-red-600 text-white rounded-lg text-sm font-medium transition-colors"
            >
              断开
            </button>
          )}
        </div>
      </div>

      {/* 券商凭证表单 */}
      {selectedBroker && !connected && (
        <BrokerConnectForm
          broker={selectedBroker}
          onConnect={handleCredentialConnect}
          onCancel={() => setSelectedBroker(null)}
        />
      )}
    </div>
  );
}
