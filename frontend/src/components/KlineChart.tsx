import { useEffect, useRef } from 'react';
import {
  createChart,
  createSeriesMarkers,
  IChartApi,
  CandlestickSeries,
  HistogramSeries,
  CandlestickData,
  Time,
  UTCTimestamp,
  LineStyle,
  ColorType,
} from 'lightweight-charts';

function parseTime(dateStr: string): Time {
  if (dateStr.length <= 10) {
    return dateStr as Time;
  }
  // Replace space with T for ISO 8601 compliance (e.g. "2026-03-04 09:35" → "2026-03-04T09:35")
  const iso = dateStr.includes(' ') ? dateStr.replace(' ', 'T') : dateStr;
  return (Math.floor(new Date(iso).getTime() / 1000)) as UTCTimestamp;
}

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  date: string;
  side: 'buy' | 'sell';
  price: number;
  quantity: number;
  pnl?: number;
}

interface KlineChartProps {
  data: KlineBar[];
  trades: TradeMarker[];
  height?: number;
  onDoubleClick?: (date: string) => void;
}

export default function KlineChart({ data, trades, height = 420, onDoubleClick }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#d1d5db',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#6366f1', style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#4f46e5' },
        horzLine: { color: '#6366f1', style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#4f46e5' },
      },
      rightPriceScale: {
        borderColor: '#2a2a4a',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: '#2a2a4a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        barSpacing: 8,
        minBarSpacing: 2,
      },
    });

    chartRef.current = chart;

    // K线
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    });

    // 成交量
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    });

    // 填入K线数据 - 去重并确保时间严格递序
    if (data.length > 0) {
      const seen = new Set<string>();
      const uniqueData = data.filter((bar) => {
        if (seen.has(bar.date)) return false;
        seen.add(bar.date);
        return true;
      });

      const candleData: CandlestickData<Time>[] = uniqueData.map((bar) => ({
        time: parseTime(bar.date),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }));
      candleSeries.setData(candleData);

      const volumeData = uniqueData.map((bar) => ({
        time: parseTime(bar.date),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(239,68,68,0.7)' : 'rgba(34,197,94,0.7)',
      }));
      volumeSeries.setData(volumeData);
    }

    // 买卖标记：日K线按日合并(B/S/T)，日内K线按精确时间逐笔显示
    if (trades.length > 0) {
      // 根据 bar 数据判断是否为日内K线（而不是 trades，因为日K线图的 trades 也可能带时分）
      const isIntraday = data.some((b) => b.date.length > 10);

      // 日K线图：trades 只取日期部分，与 bar 的 time 类型一致
      // 日内K线图：trades 保留完整时间
      const normalizeTradeTime = (date: string) => isIntraday ? parseTime(date) : (date.slice(0, 10) as Time);

      if (isIntraday) {
        // 日内K线：按精确时间分组
        const timeMap = new Map<string, { buy: TradeMarker[]; sell: TradeMarker[] }>();
        for (const t of trades) {
          if (!timeMap.has(t.date)) timeMap.set(t.date, { buy: [], sell: [] });
          if (t.side === 'buy') timeMap.get(t.date)!.buy.push(t);
          else timeMap.get(t.date)!.sell.push(t);
        }

        const markers: Array<{
          time: Time;
          position: 'aboveBar' | 'belowBar';
          color: string;
          shape: 'arrowUp' | 'arrowDown' | 'circle';
          text: string;
        }> = [];

        const sortedTimes = [...timeMap.keys()].sort();
        for (const tm of sortedTimes) {
          const { buy, sell } = timeMap.get(tm)!;
          const hasBuy = buy.length > 0;
          const hasSell = sell.length > 0;

          if (hasBuy && hasSell) {
            markers.push({
              time: normalizeTradeTime(tm),
              position: 'aboveBar',
              color: '#f59e0b',
              shape: 'circle',
              text: 'T',
            });
          } else if (hasBuy) {
            markers.push({
              time: normalizeTradeTime(tm),
              position: 'belowBar',
              color: '#ef4444',
              shape: 'arrowUp',
              text: 'B',
            });
          } else {
            markers.push({
              time: normalizeTradeTime(tm),
              position: 'aboveBar',
              color: '#22c55e',
              shape: 'arrowDown',
              text: 'S',
            });
          }
        }
        createSeriesMarkers(candleSeries, markers);
      } else {
        // 日K线：按日合并
        const dayMap = new Map<string, { buy: TradeMarker[]; sell: TradeMarker[] }>();
        for (const t of trades) {
          const day = t.date.slice(0, 10);
          if (!dayMap.has(day)) dayMap.set(day, { buy: [], sell: [] });
          if (t.side === 'buy') dayMap.get(day)!.buy.push(t);
          else dayMap.get(day)!.sell.push(t);
        }

        const markers: Array<{
          time: Time;
          position: 'aboveBar' | 'belowBar';
          color: string;
          shape: 'arrowUp' | 'arrowDown' | 'circle';
          text: string;
        }> = [];

        const sortedDays = [...dayMap.keys()].sort();
        for (const day of sortedDays) {
          const { buy, sell } = dayMap.get(day)!;
          const hasBuy = buy.length > 0;
          const hasSell = sell.length > 0;

          if (hasBuy && hasSell) {
            markers.push({
              time: normalizeTradeTime(day),
              position: 'aboveBar',
              color: '#f59e0b',
              shape: 'circle',
              text: 'T',
            });
          } else if (hasBuy) {
            markers.push({
              time: normalizeTradeTime(day),
              position: 'belowBar',
              color: '#ef4444',
              shape: 'arrowUp',
              text: 'B',
            });
          } else {
            markers.push({
              time: normalizeTradeTime(day),
              position: 'aboveBar',
              color: '#22c55e',
              shape: 'arrowDown',
              text: 'S',
            });
          }
        }
        createSeriesMarkers(candleSeries, markers);
      }
    }

    chart.timeScale().fitContent();

    // 双击事件：使用 lightweight-charts v5 原生 subscribeDblClick
    if (onDoubleClick) {
      const dblClickHandler = (param: any) => {
        if (!param.time) return;
        let dateStr: string;
        if (typeof param.time === 'string') {
          dateStr = param.time.slice(0, 10);
        } else if (typeof param.time === 'object' && param.time.year) {
          const y = param.time.year;
          const m = String(param.time.month).padStart(2, '0');
          const d = String(param.time.day).padStart(2, '0');
          dateStr = `${y}-${m}-${d}`;
        } else {
          dateStr = new Date((param.time as number) * 1000).toISOString().slice(0, 10);
        }
        onDoubleClick(dateStr);
      };
      chart.subscribeDblClick(dblClickHandler);
    }

    const observer = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, trades, height, onDoubleClick]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg overflow-hidden border border-gray-800"
      style={{ minHeight: height }}
    />
  );
}