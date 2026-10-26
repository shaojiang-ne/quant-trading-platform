import { useCallback, useEffect, useRef } from 'react';

interface ResizeHandleProps {
  /** 'horizontal' = 左右拖动（竖条，用于列宽）；'vertical' = 上下拖动（横条，用于行高） */
  orientation?: 'horizontal' | 'vertical';
  onResize: (clientCoord: number) => void;
  onResizeEnd?: () => void;
}

export function ResizeHandle({ orientation = 'horizontal', onResize, onResizeEnd }: ResizeHandleProps) {
  const isDragging = useRef(false);
  // 始终指向最新的 onResize，避免拖拽期间闭包捕获到旧的尺寸
  const onResizeRef = useRef(onResize);
  useEffect(() => {
    onResizeRef.current = onResize;
  }, [onResize]);

  const isVertical = orientation === 'vertical';

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDragging.current) return;
      onResizeRef.current(isVertical ? moveEvent.clientY : moveEvent.clientX);
    };

    const handleMouseUp = () => {
      isDragging.current = false;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      onResizeEnd?.();
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [isVertical, onResizeEnd]);

  return (
    <div
      onMouseDown={handleMouseDown}
      className={
        isVertical
          ? 'h-1.5 cursor-row-resize bg-gray-200 hover:bg-primary-400 active:bg-primary-500 transition-colors flex-shrink-0 w-full'
          : 'w-1.5 cursor-col-resize bg-gray-200 hover:bg-primary-400 active:bg-primary-500 transition-colors flex-shrink-0'
      }
      style={{ userSelect: 'none' }}
    />
  );
}
