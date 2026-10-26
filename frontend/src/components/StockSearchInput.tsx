import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useStockCacheStore } from '@/stores/stockCacheStore';
import type { StockInfo } from '@/stores/stockCacheStore';

interface StockSearchInputProps {
  value: string;
  onChange: (symbol: string) => void;
  placeholder?: string;
  error?: string;
  focusRingColor?: string;
}

export function StockSearchInput({
  value,
  onChange,
  placeholder = '输入代码、名称或拼音首字母',
  error,
  focusRingColor = 'focus:ring-primary-500',
}: StockSearchInputProps) {
  const [query, setQuery] = useState(value);
  const [stockName, setStockName] = useState('');
  const [results, setResults] = useState<StockInfo[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0, width: 0 });
  const [isUserInput, setIsUserInput] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { loaded, fetchAll, search, lookup } = useStockCacheStore();

  // 启动时加载全量缓存
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // 初始加载股票名称
  useEffect(() => {
    if (value && loaded) {
      const s = lookup(value);
      if (s) setStockName(s.name);
    }
  }, [value, loaded]);

  // 同步外部 value 变化
  useEffect(() => {
    setQuery(value);
  }, [value]);

  // 计算下拉位置
  const updateDropdownPos = useCallback(() => {
    if (inputRef.current) {
      const rect = inputRef.current.getBoundingClientRect();
      setDropdownPos({
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
      });
    }
  }, []);

  // 防抖本地搜索（只在用户主动输入时才展示下拉框）
  useEffect(() => {
    if (!query.trim() || !loaded) {
      setResults([]);
      setShowDropdown(false);
      setHighlightIndex(-1);
      return;
    }
    // 不是用户主动输入（初始值/外部同步），不展示下拉框
    if (!isUserInput) {
      setResults([]);
      setShowDropdown(false);
      return;
    }
    const timer = setTimeout(() => {
      const res = search(query.trim());
      setResults(res);
      if (res.length > 0) {
        updateDropdownPos();
        setShowDropdown(true);
      } else {
        setShowDropdown(false);
      }
      setHighlightIndex(-1);
    }, 150);
    return () => clearTimeout(timer);
  }, [query, loaded, isUserInput, updateDropdownPos]);

  // 点击外部关闭下拉
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && dropdownRef.current.contains(e.target as Node)) return;
      if (inputRef.current && inputRef.current.contains(e.target as Node)) return;
      setShowDropdown(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleSelect = (stock: StockInfo) => {
    setQuery(stock.code);
    setStockName(stock.name);
    setShowDropdown(false);
    setHighlightIndex(-1);
    setIsUserInput(false);
    onChange(stock.code);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    setIsUserInput(true);
    // 输入过程中清空选中状态，不触发 onChange
    setStockName('');
    onChange('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown || results.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIndex((prev) => (prev + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIndex((prev) => (prev - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (highlightIndex >= 0 && highlightIndex < results.length) {
        handleSelect(results[highlightIndex]);
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
      setHighlightIndex(-1);
    }
  };

  // 滚动高亮项到可视区域
  useEffect(() => {
    if (highlightIndex < 0 || !dropdownRef.current) return;
    const items = dropdownRef.current.children;
    if (items[highlightIndex]) {
      items[highlightIndex].scrollIntoView({ block: 'nearest' });
    }
  }, [highlightIndex]);

  const handleFocus = () => {
    // 聚焦时不自动展示下拉框，只在用户主动输入时才展示
  };

  const dropdown = showDropdown && results.length > 0 ? (
    <div
      ref={dropdownRef}
      style={{
        position: 'fixed',
        top: dropdownPos.top,
        left: dropdownPos.left,
        width: dropdownPos.width,
        zIndex: 9999,
      }}
      className="bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto"
    >
      {results.map((s, idx) => (
        <button
          key={s.code}
          onClick={() => handleSelect(s)}
          onMouseEnter={() => setHighlightIndex(idx)}
          className={`w-full px-3 py-2 text-left flex items-center justify-between transition-colors ${
            idx === highlightIndex ? 'bg-primary-50' : 'hover:bg-primary-50'
          }`}
        >
          <span className="font-mono text-gray-900">{s.code}</span>
          <span className="text-gray-600">{s.name}</span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={handleFocus}
        placeholder={placeholder}
        className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 ${focusRingColor} ${error ? 'border-red-300' : 'border-gray-300'}`}
      />
      {stockName && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-primary-600 font-medium">
          {stockName}
        </span>
      )}
      {dropdown && createPortal(dropdown, document.body)}
      {error && <p className="mt-1 text-sm text-red-500">{error}</p>}
    </div>
  );
}