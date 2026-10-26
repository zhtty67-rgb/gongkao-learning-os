'use client';

import { useEffect, useRef, useState } from 'react';
import { SearchHit } from './model';

interface FrameworkToolbarProps {
  activeTree: 'knowledge' | 'support';
  onTreeChange: (tree: 'knowledge' | 'support') => void;
  modules: Array<{ name: string; nodeCount: number }>;
  activeModule: string;
  onModuleChange: (m: string) => void;
  search: string;
  onSearchChange: (v: string) => void;
  searchHits: SearchHit[];
  onLocate: (hit: SearchHit) => void;
  onlyWeak: boolean;
  onToggleWeak: () => void;
  weakCount: number;
  viewMode: 'map' | 'list';
  onViewModeChange: (m: 'map' | 'list') => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
}

export default function FrameworkToolbar(props: FrameworkToolbarProps) {
  const {
    modules,
    activeModule,
    onModuleChange,
    search,
    onSearchChange,
    searchHits,
    onLocate,
    onlyWeak,
    onToggleWeak,
    weakCount,
    viewMode,
    onViewModeChange,
    isFullscreen,
    onToggleFullscreen,
  } = props;
  const [dropOpen, setDropOpen] = useState(false);
  const searchWrapRef = useRef<HTMLDivElement>(null);
  const isSearching = search.trim().length > 0;

  useEffect(() => {
    if (!isSearching) setDropOpen(false);
  }, [isSearching]);

  // 点击工具栏外部时收起搜索下拉
  useEffect(() => {
    if (!dropOpen) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) setDropOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [dropOpen]);

  const shownHits = searchHits.slice(0, 8);

  return (
    <section className="fw-toolbar" aria-label="知识框架工具栏">
      <div className="fw-viewswitch" role="group" aria-label="知识树选择" style={{marginBottom: 12}}>
        <button type="button" className={`fw-chip${props.activeTree === 'knowledge' ? ' on' : ''}`} aria-pressed={props.activeTree === 'knowledge'} onClick={() => props.onTreeChange('knowledge')}>知识与题型树</button>
        <button type="button" className={`fw-chip${props.activeTree === 'support' ? ' on' : ''}`} aria-pressed={props.activeTree === 'support'} onClick={() => props.onTreeChange('support')}>技巧·策略·案例树</button>
      </div>
      <div className="fw-modtabs" role="tablist" aria-label="科目模块">
        {modules.map(m => (
          <button
            key={m.name}
            type="button"
            role="tab"
            aria-selected={m.name === activeModule}
            className={`fw-modtab${m.name === activeModule ? ' on' : ''}`}
            onClick={() => onModuleChange(m.name)}
          >
            {m.name}
            <span className="fw-modtab-count">{m.nodeCount}</span>
          </button>
        ))}
      </div>

      <div className="fw-toolbar-row">
        <div className="fw-searchwrap" ref={searchWrapRef}>
          <input
            type="search"
            className="fw-search"
            value={search}
            placeholder="搜索考点名称、别名或说明（回车定位第一个结果）"
            aria-label="搜索考点"
            onChange={e => {
              onSearchChange(e.target.value);
              setDropOpen(true);
            }}
            onFocus={() => isSearching && setDropOpen(true)}
            onKeyDown={e => {
              if (e.key === 'Enter' && shownHits.length > 0) {
                onLocate(shownHits[0]);
                setDropOpen(false);
                (e.target as HTMLInputElement).blur();
              } else if (e.key === 'Escape') {
                if (isSearching) onSearchChange('');
                setDropOpen(false);
              }
            }}
          />
          {isSearching && (
            <button type="button" className="fw-mini fw-search-clear" aria-label="清除搜索" onClick={() => onSearchChange('')}>
              ✕
            </button>
          )}
          {dropOpen && isSearching && (
            <div className="fw-searchdrop" role="listbox" aria-label="搜索结果">
              {searchHits.length === 0 ? (
                <p className="fw-searchdrop-empty">未找到匹配的考点、别名或说明。</p>
              ) : (
                <>
                  {shownHits.map(hit => (
                    <button
                      key={hit.node.id}
                      type="button"
                      role="option"
                      aria-selected={false}
                      className="fw-searchdrop-item"
                      onMouseDown={e => e.preventDefault()}
                      onClick={() => {
                        onLocate(hit);
                        setDropOpen(false);
                      }}
                    >
                      <span className="fw-searchdrop-name">{hit.node.name}</span>
                      <span className="fw-searchdrop-path">{hit.path.slice(0, -1).join(' / ') || hit.node.module}</span>
                      {hit.matchedAlias && <span className="fw-searchdrop-alias">别名：{hit.matchedAlias}</span>}
                    </button>
                  ))}
                  {searchHits.length > shownHits.length && (
                    <p className="fw-searchdrop-more">共 {searchHits.length} 个结果，回车定位第一个。</p>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        <button
          type="button"
          className={`fw-chip${onlyWeak ? ' on' : ''}`}
          aria-pressed={onlyWeak}
          onClick={onToggleWeak}
          title="只看待巩固（已练习且掌握度低于 75%）的考点，并保留其祖先路径"
          disabled={props.activeTree === 'support'}
        >
          只看薄弱点{weakCount > 0 ? ` (${weakCount})` : ''}
        </button>

        <div className="fw-viewswitch" role="group" aria-label="视图切换">
          <button
            type="button"
            aria-pressed={viewMode === 'map'}
            className={`fw-chip${viewMode === 'map' ? ' on' : ''}`}
            onClick={() => onViewModeChange('map')}
          >
            地图
          </button>
          <button
            type="button"
            aria-pressed={viewMode === 'list'}
            className={`fw-chip${viewMode === 'list' ? ' on' : ''}`}
            onClick={() => onViewModeChange('list')}
          >
            列表
          </button>
        </div>

        <button
          type="button"
          className="fw-chip"
          aria-pressed={isFullscreen}
          onClick={onToggleFullscreen}
          title="全屏显示地图区"
        >
          {isFullscreen ? '退出全屏' : '全屏'}
        </button>
      </div>
    </section>
  );
}
