'use client';

import React, { useMemo } from 'react';

export type GridCell = {
  char: string;
  pIndex?: number;
  cIndex?: number;
  isIndent?: boolean;
  highlightType?: string; // 'target' | 'strength' | null
  targetKey?: string;
  isOverLimit?: boolean;
};

export type GridRow = {
  rowNumber: number; // 1-based
  cells: GridCell[];
  marker?: number | null; // e.g. 100, 200, 300...
  isLimitRow?: boolean;
};

/**
 * 将文本精确换算为 25 列标准申论答题纸方格网格数据
 * 规则：
 * 1. 每行固定 25 列；
 * 2. 换行符另起一行；
 * 3. 段落首行如未手工输入缩进，可智能辅助空 2 格（或忠实呈现用户输入的两空格）；
 * 4. 标点符号独立占 1 格；
 * 5. 每满 100 字（第 4、8、12、16、20...行末）右侧标记字数；
 * 6. 达到篇幅上限时标注警戒线。
 */
export function formatTextToShenlunGrid(
  text: string,
  maxWords: number = 300,
  highlights?: Array<{ quote: string; type: 'target' | 'strength'; key?: string }>
): { rows: GridRow[]; totalChars: number; totalRows: number; isOverLimit: boolean } {
  const cleanText = text || '';
  const paragraphs = cleanText.split('\n');
  const COLS = 25;

  const rows: GridRow[] = [];
  let currentRowCells: GridCell[] = [];
  let totalCharsCount = 0;
  let charGlobalIndex = 0;

  function pushRow(isEnd = false) {
    while (currentRowCells.length < COLS) {
      currentRowCells.push({ char: '', pIndex: -1, cIndex: -1 });
    }
    const rowNum = rows.length + 1;
    const capacity = rowNum * COLS;
    const marker = capacity % 100 === 0 ? capacity : null;
    const isLimitRow = maxWords > 0 && Math.ceil(maxWords / COLS) === rowNum;

    rows.push({
      rowNumber: rowNum,
      cells: currentRowCells,
      marker,
      isLimitRow,
    });
    currentRowCells = [];
  }

  paragraphs.forEach((para, pIdx) => {
    if (para.length === 0 && pIdx > 0) {
      // 空行处理
      if (currentRowCells.length > 0) pushRow();
      return;
    }

    // 判断段首是否已有空格缩进；若为普通正文段落且首字非空格，自动按规范补 2 格缩进
    const trimmed = para.trim();
    if (!trimmed) {
      if (currentRowCells.length > 0) pushRow();
      return;
    }

    // 是否需要补缩进（如果用户输入本身就是空格，则按用户输入的空格占格）
    const needsIndent = !para.startsWith('  ') && !para.startsWith('\u3000\u3000');
    if (needsIndent) {
      currentRowCells.push({ char: '', isIndent: true });
      currentRowCells.push({ char: '', isIndent: true });
      totalCharsCount += 2;
    }

    // 逐字排入格子
    for (let i = 0; i < para.length; i++) {
      const ch = para[i];
      if (ch === '\r') continue;

      totalCharsCount++;
      charGlobalIndex++;
      const isOver = maxWords > 0 && totalCharsCount > maxWords;

      // 检查高亮匹配
      let highlightType: 'target' | 'strength' | undefined;
      let targetKey: string | undefined;

      if (highlights && highlights.length > 0) {
        for (const h of highlights) {
          if (h.quote && h.quote.length >= 2) {
            // 简单判断子串覆盖
            const quoteIdx = para.indexOf(h.quote);
            if (quoteIdx !== -1 && i >= quoteIdx && i < quoteIdx + h.quote.length) {
              highlightType = h.type;
              targetKey = h.key;
              break;
            }
          }
        }
      }

      currentRowCells.push({
        char: ch,
        pIndex: pIdx,
        cIndex: i,
        highlightType,
        targetKey,
        isOverLimit: isOver,
      });

      if (currentRowCells.length === COLS) {
        pushRow();
      }
    }

    // 每段结束强制换行
    if (currentRowCells.length > 0) {
      pushRow(true);
    }
  });

  // 保证答题卡有足够的空白行供书写展示（至少满篇幅要求 + 3 行）
  const minRows = Math.max(
    Math.ceil((maxWords || 300) / COLS) + 3,
    rows.length + 3,
    14
  );

  while (rows.length < minRows) {
    const rowNum = rows.length + 1;
    const capacity = rowNum * COLS;
    const marker = capacity % 100 === 0 ? capacity : null;
    const isLimitRow = maxWords > 0 && Math.ceil(maxWords / COLS) === rowNum;
    const emptyCells: GridCell[] = Array.from({ length: COLS }, () => ({
      char: '',
      pIndex: -1,
      cIndex: -1,
    }));

    rows.push({
      rowNumber: rowNum,
      cells: emptyCells,
      marker,
      isLimitRow,
    });
  }

  return {
    rows,
    totalChars: totalCharsCount,
    totalRows: rows.length,
    isOverLimit: maxWords > 0 && totalCharsCount > maxWords,
  };
}

/**
 * 申论标准 25 列红格作答纸渲染组件
 */
export function ShenlunStandardGridPaper({
  text,
  maxWords = 300,
  questionStem,
  highlights = [],
  title = '公务员录用考试 · 申论专用答题卡',
  subtitle = '第 1 题 作答区域',
  onCellClick,
  readOnly = true,
}: {
  text: string;
  maxWords?: number;
  questionStem?: string;
  highlights?: Array<{ quote: string; type: 'target' | 'strength'; key?: string }>;
  title?: string;
  subtitle?: string;
  onCellClick?: (key?: string) => void;
  readOnly?: boolean;
}) {
  const { rows, totalChars, isOverLimit } = useMemo(() => {
    return formatTextToShenlunGrid(text, maxWords, highlights);
  }, [text, maxWords, highlights]);

  return (
    <div className="shenlun-grid-paper-container" aria-label="申论标准25列红色答题方格纸">
      {/* 答题卡权威抬头 */}
      <div className="exam-card-header">
        <div className="exam-card-seal-top">
          <span className="exam-card-title-main">{title}</span>
          <span className="exam-card-badge">标准 25 格 / 行</span>
        </div>

        <div className="exam-card-meta-bar">
          <div className="exam-card-question-tag">
            <strong>{subtitle}</strong>
            {maxWords > 0 && (
              <span className="word-quota-tag">
                篇幅限制：不超过 <strong>{maxWords}</strong> 字
              </span>
            )}
          </div>
          <div className="exam-card-stats-tag">
            <span>当前已占格：</span>
            <strong style={{ color: isOverLimit ? '#b91c1c' : '#a04825', fontSize: 15 }}>
              {totalChars}
            </strong>
            <span> / {maxWords} 格</span>
            {isOverLimit && <span className="overlimit-warning">⚠ 已超出字数上限</span>}
          </div>
        </div>

        <div className="exam-card-rule-prompt">
          <span>● 作答规则：每行 25 格 · 标点占一格 · 段首空两格 · 超格部分阅卷不予扫描评分</span>
        </div>
      </div>

      {/* 25 列红色方格卷面矩阵 */}
      <div className="exam-grid-matrix-wrapper">
        <div className="exam-grid-matrix">
          {rows.map(row => {
            return (
              <div
                key={row.rowNumber}
                className={`exam-grid-row ${row.isLimitRow ? 'is-limit-row' : ''}`}
              >
                {/* 25 个红格单元 */}
                <div className="exam-grid-cells-row">
                  {row.cells.map((cell, cIdx) => {
                    const isFilled = Boolean(cell.char);
                    const isIndent = cell.isIndent;
                    let cellClass = 'exam-cell';
                    if (isIndent) cellClass += ' cell-indent';
                    if (cell.highlightType === 'target') cellClass += ' cell-highlight-target';
                    if (cell.highlightType === 'strength') cellClass += ' cell-highlight-strength';
                    if (cell.isOverLimit && isFilled) cellClass += ' cell-overlimit';

                    return (
                      <div
                        key={cIdx}
                        className={cellClass}
                        onClick={() => cell.targetKey && onCellClick?.(cell.targetKey)}
                        title={
                          cell.isOverLimit
                            ? '已超出篇幅限制'
                            : cell.targetKey
                            ? '点击查看名师对应批注'
                            : undefined
                        }
                      >
                        {cell.char || (isIndent ? ' ' : '')}
                      </div>
                    );
                  })}
                </div>

                {/* 右侧每百字刻度与上限标注 */}
                <div className="exam-grid-row-marker">
                  {row.marker && <span className="marker-number">{row.marker}</span>}
                  {row.isLimitRow && <span className="marker-limit-tag">上限{maxWords}字</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 答题卡底部密封与注意事项 */}
      <div className="exam-card-footer">
        <span className="exam-footer-notice">
          ※ 考场规范：严禁在答题卡边缘涂写标记，保持卷面整洁无折痕。
        </span>
        <span className="exam-footer-brand">Gongkao Learning OS · 申论全真阅卷引擎</span>
      </div>
    </div>
  );
}
