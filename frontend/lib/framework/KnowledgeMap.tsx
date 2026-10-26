'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ExpandedMap,
  FrameworkNode,
  MAP_METRICS,
  MapPosition,
  STATUS_LABEL,
  Viewport,
  isNodeExpanded,
  layoutForest,
} from './model';
import { nodeStatus, isAuxiliaryNode } from './model';

const MIN_K = 0.3;
const MAX_K = 2.5;

export interface LocateRequest {
  id: string;
  nonce: number;
}

interface KnowledgeMapProps {
  layout: ReturnType<typeof layoutForest>;
  expanded: ExpandedMap;
  selectedId: string | null;
  weakIds: Set<string> | null;
  highlightId: string | null;
  locateRequest: LocateRequest | null;
  /** 视口键：模块或聚焦目标变化时，用 initialViewport 重置视口 */
  viewportKey: string;
  initialViewport: Viewport | null;
  focusNode: FrameworkNode | null;
  onViewportChange: (vp: Viewport) => void;
  onSelect: (id: string | null) => void;
  onToggle: (id: string, expanded: boolean) => void;
  onClearFocus: () => void;
  onFocusParent: () => void;
}

function clampK(k: number) {
  return Math.min(MAX_K, Math.max(MIN_K, k));
}

export default function KnowledgeMap(props: KnowledgeMapProps) {
  const {
    layout,
    expanded,
    selectedId,
    weakIds,
    highlightId,
    locateRequest,
    viewportKey,
    initialViewport,
    focusNode,
  } = props;
  const canvasRef = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState<Viewport>(initialViewport ?? { x: 40, y: 40, k: 1 });
  const [panning, setPanning] = useState(false);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const suppressClickRef = useRef(false);
  const pointersRef = useRef(new Map<number, { x: number; y: number }>());
  const dragRef = useRef<{ lastX: number; lastY: number; moved: number } | null>(null);
  const pinchRef = useRef<{ dist: number; midX: number; midY: number } | null>(null);
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const vpRef = useRef(vp);
  vpRef.current = vp;

  // 视口键变化（模块切换/进入聚焦）时恢复该键保存的视口；
  // 没有保存视口则标记“待适应屏幕”，等容器尺寸就绪后自动 fit 一次。
  const initVpForKeyRef = useRef('');
  const pendingFitRef = useRef(false);
  useEffect(() => {
    if (initVpForKeyRef.current === viewportKey) return;
    initVpForKeyRef.current = viewportKey;
    if (initialViewport) {
      setVp(initialViewport);
    } else {
      pendingFitRef.current = true;
      setVp({ x: 40, y: 40, k: 1 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewportKey]);

  const setVpReported = useCallback(
    (next: Viewport | ((prev: Viewport) => Viewport)) => {
      setVp(next);
    },
    [],
  );

  // 视口变化统一回报父组件做按模块持久化
  useEffect(() => {
    props.onViewportChange(vp);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vp]);

  // 容器尺寸：适应屏幕与居中定位需要
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => {
      const rect = entries[0].contentRect;
      setSize({ w: rect.width, h: rect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const fit = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const l = layoutRef.current;
    if (!rect.width || !rect.height || !l.visibleCount) return;
    // 可读下限 0.85：全塞进屏幕会把节点文字缩到难以辨认（上轮实测 36%）。
    // 内容超出时允许平移查看，而不是无限缩小；“查看全貌”仍由适应屏幕按钮承担。
    const k = clampK(Math.max(0.85, Math.min((rect.width - 20) / l.width, (rect.height - 20) / l.height, 1.25)));
    setVpReported({
      k,
      x: (rect.width - l.width * k) / 2,
      y: (rect.height - l.height * k) / 2,
    });
  }, [setVpReported]);

  const centerOn = useCallback(
    (pos: MapPosition, k?: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      // 搜索定位与分支聚焦使用适合阅读的缩放（不低于 1.0）
      const nextK = clampK(k ?? Math.max(vpRef.current.k, 1));
      setVpReported({
        k: nextK,
        x: rect.width / 2 - (pos.x + MAP_METRICS.nodeWidth / 2) * nextK,
        y: rect.height / 2 - pos.y * nextK,
      });
    },
    [setVpReported],
  );

  const rootCentered = useCallback(() => {
    const first = layoutRef.current.positions.values().next().value as MapPosition | undefined;
    if (first) centerOn(first, 1);
  }, [centerOn]);

  const zoomAt = useCallback(
    (px: number, py: number, factor: number) => {
      setVp(prev => {
        const k = clampK(prev.k * factor);
        if (k === prev.k) return prev;
        return {
          k,
          x: px - (px - prev.x) * (k / prev.k),
          y: py - (py - prev.y) * (k / prev.k),
        };
      });
    },
    [],
  );

  // 容器尺寸就绪后执行待定的“适应屏幕”（首次加载/模块切换无保存视口/进入聚焦）
  useEffect(() => {
    if (pendingFitRef.current && size && layout.visibleCount) {
      pendingFitRef.current = false;
      fit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size, layout.visibleCount]);

  // 搜索定位：祖先展开由父组件完成，这里把目标节点带到视野中央
  useEffect(() => {
    if (!locateRequest) return;
    const pos = layoutRef.current.positions.get(locateRequest.id);
    if (pos) centerOn(pos);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locateRequest?.nonce]);

  // 滚轮缩放；trackpad 捏合（ctrlKey）同样缩放，shift/横向滚动为平移
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const horizontal = e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY);
      if (horizontal) {
        setVp(prev => ({ ...prev, x: prev.x - (e.deltaX || e.deltaY) }));
      } else {
        zoomAt(px, py, Math.exp(-e.deltaY * 0.0016));
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  const onPointerDown = (e: React.PointerEvent) => {
    // 注意：这里不能 setPointerCapture——捕获会把后续 click 重定向到画布，
    // 导致节点按钮永远收不到点击；捕获推迟到拖动真正开始时。
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    suppressClickRef.current = false;
    if (pointersRef.current.size === 1) {
      dragRef.current = { lastX: e.clientX, lastY: e.clientY, moved: 0 };
      pinchRef.current = null;
    } else if (pointersRef.current.size === 2) {
      dragRef.current = null;
      const [a, b] = [...pointersRef.current.values()];
      pinchRef.current = {
        dist: Math.hypot(a.x - b.x, a.y - b.y),
        midX: (a.x + b.x) / 2,
        midY: (a.y + b.y) / 2,
      };
      // 双指捏合开始：捕获两指，后续事件统一走画布
      const canvas = canvasRef.current;
      if (canvas) {
        for (const id of pointersRef.current.keys()) {
          try {
            canvas.setPointerCapture(id);
          } catch {
            /* 指针可能已释放 */
          }
        }
      }
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointersRef.current.size === 2 && pinchRef.current) {
      const [a, b] = [...pointersRef.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const midX = (a.x + b.x) / 2;
      const midY = (a.y + b.y) / 2;
      const rect = canvasRef.current?.getBoundingClientRect();
      const prevPinch = pinchRef.current;
      if (rect && prevPinch.dist > 0 && dist > 0) {
        pinchRef.current = { dist, midX, midY };
        const factor = dist / prevPinch.dist;
        const px = prevPinch.midX - rect.left;
        const py = prevPinch.midY - rect.top;
        const movedX = midX - prevPinch.midX;
        const movedY = midY - prevPinch.midY;
        setVp(prev => {
          const k = clampK(prev.k * factor);
          return {
            k,
            x: px - (px - prev.x) * (k / prev.k) + movedX,
            y: py - (py - prev.y) * (k / prev.k) + movedY,
          };
        });
        suppressClickRef.current = true;
      }
      return;
    }
    const drag = dragRef.current;
    if (!drag) return;
    const dx = e.clientX - drag.lastX;
    const dy = e.clientY - drag.lastY;
    drag.lastX = e.clientX;
    drag.lastY = e.clientY;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.moved > 4) {
      if (!panning) {
        setPanning(true);
        // 拖动真正开始才捕获指针：快速拖出画布边缘时事件流不断
        try {
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
        } catch {
          /* 指针可能已释放 */
        }
      }
      suppressClickRef.current = true;
      setVp(prev => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
    }
  };

  const endPointer = (e: React.PointerEvent) => {
    pointersRef.current.delete(e.pointerId);
    if (pointersRef.current.size < 2) pinchRef.current = null;
    if (pointersRef.current.size === 0) {
      dragRef.current = null;
      setPanning(false);
    }
  };

  // 空白处单击（非拖动）：取消选中
  const onCanvasClick = (e: React.MouseEvent) => {
    if (suppressClickRef.current) return;
    if (e.target === e.currentTarget) {
      props.onSelect(null);
    }
  };

  const positions = layout.positions;

  // 选中节点 + 祖先路径（连线高亮）
  const selectedPathIds = useMemo(() => {
    const set = new Set<string>();
    let cur = selectedId ? positions.get(selectedId) : undefined;
    while (cur) {
      set.add(cur.id);
      cur = cur.node.parent_id ? positions.get(cur.node.parent_id) : undefined;
    }
    return set;
  }, [selectedId, positions]);

  return (
    <div
      ref={canvasRef}
      className={`fw-canvas${panning ? ' panning' : ''}`}
      role="group"
      aria-label="知识地图画布：拖动平移，滚轮缩放，点击考点名称查看详情，加号按钮展开子考点"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endPointer}
      onPointerCancel={endPointer}
      onClick={onCanvasClick}
    >
      <div className="fw-hint" aria-hidden="true">
        拖动平移 · 滚轮缩放 · 点击名称看详情 · ＋展开子级
      </div>

      {focusNode && (
        <div className="fw-focusbar">
          <span className="fw-focusbar-label">已聚焦分支</span>
          <strong>{focusNode.name}</strong>
          {focusNode.parent && (
            <button type="button" className="fw-mini" onClick={props.onFocusParent}>
              上一层
            </button>
          )}
          <button type="button" className="fw-mini fw-mini-strong" onClick={props.onClearFocus}>
            返回整体地图
          </button>
        </div>
      )}

      <div className="fw-world" style={{ transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.k})` }}>
        <svg className="fw-edges" width={layout.width} height={layout.height} aria-hidden="true">
          {layout.edges.map(edge => {
            const from = positions.get(edge.fromId);
            const to = positions.get(edge.toId);
            if (!from || !to) return null;
            const x1 = from.x + MAP_METRICS.nodeWidth;
            const y1 = from.y;
            const x2 = to.x;
            const y2 = to.y;
            const mx = (x1 + x2) / 2;
            const active = selectedPathIds.has(to.id) && selectedPathIds.has(from.id);
            return (
              <path
                key={`${edge.fromId}->${edge.toId}`}
                d={`M ${x1},${y1} C ${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                className={`fw-edge${active ? ' active' : ''}`}
              />
            );
          })}
        </svg>

        {[...positions.values()].map(pos => {
          const node = pos.node;
          const status = nodeStatus(node);
          const hasChildren = node.children.length > 0;
          const isExpandedHere = hasChildren && isNodeExpanded(node, pos.depth, expanded);
          const isDimmed = !!weakIds && !weakIds.has(node.id);
          const isSelected = selectedId === node.id;
          return (
            <div
              key={node.id}
              className={[
                'fw-node',
                `st-${status}`,
                isSelected ? 'selected' : '',
                highlightId === node.id ? 'highlight' : '',
                isDimmed ? 'dimmed' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={{ left: pos.x, top: pos.y - MAP_METRICS.nodeHeight / 2, width: MAP_METRICS.nodeWidth }}
              data-node-id={node.id}
            >
              {hasChildren ? (
                <button
                  type="button"
                  className="fw-node-toggle"
                  aria-expanded={isExpandedHere}
                  aria-label={`${isExpandedHere ? '折叠' : '展开'} ${node.name} 的 ${node.descendantCount} 个子考点`}
                  title={isExpandedHere ? '折叠子考点' : `展开 ${node.descendantCount} 个子考点`}
                  onClick={e => {
                    e.stopPropagation();
                    if (suppressClickRef.current) return;
                    props.onToggle(node.id, !isExpandedHere);
                  }}
                >
                  {isExpandedHere ? '−' : '+'}
                </button>
              ) : (
                <span className="fw-node-leafdot" aria-hidden="true" />
              )}

              <button
                type="button"
                className="fw-node-name"
                title={`${node.name}（${isAuxiliaryNode(node) ? '辅助学习' : STATUS_LABEL[status]}）`}
                aria-label={`查看考点 ${node.name}，${isAuxiliaryNode(node) ? '辅助学习' : STATUS_LABEL[status]}`}
                onClick={e => {
                  e.stopPropagation();
                  if (suppressClickRef.current) return;
                  props.onSelect(node.id);
                }}
              >
                {node.name}
              </button>

              {hasChildren && (
                <span className="fw-node-count" title={`${node.descendantCount} 个子考点`}>
                  {node.children.length}
                </span>
              )}
              <span className="fw-node-status">
                <i className="fw-dot" aria-hidden="true" />
                <span className="fw-status-text">{isAuxiliaryNode(node) ? '辅助学习' : STATUS_LABEL[status]}</span>
              </span>
            </div>
          );
        })}
      </div>

      <div className="fw-mapctrl" role="group" aria-label="地图视图控制">
        <button
          type="button"
          className="fw-mini"
          title="放大"
          aria-label="放大"
          onClick={() => {
            const rect = canvasRef.current?.getBoundingClientRect();
            if (rect) zoomAt(rect.width / 2, rect.height / 2, 1.25);
          }}
        >
          ＋
        </button>
        <button
          type="button"
          className="fw-mini"
          title="缩小"
          aria-label="缩小"
          onClick={() => {
            const rect = canvasRef.current?.getBoundingClientRect();
            if (rect) zoomAt(rect.width / 2, rect.height / 2, 0.8);
          }}
        >
          －
        </button>
        <button type="button" className="fw-mini" title="适应屏幕" aria-label="适应屏幕" onClick={fit}>
          ⤢
        </button>
        <button type="button" className="fw-mini" title="回到根节点" aria-label="回到根节点" onClick={rootCentered}>
          ⌂
        </button>
        <span className="fw-zoomlabel" aria-hidden="true">
          {Math.round(vp.k * 100)}%
        </span>
      </div>
    </div>
  );
}
