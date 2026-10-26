'use client';

import React from 'react';
import { TeachingContent } from './TeachingContent';

export interface ExplanationImage {
  url: string;
  label?: string;
}

export interface FormattedExplanationProps {
  text: string;
  standardAnswer?: string;
  module?: string;
  images?: ExplanationImage[];
  onZoom?: (imgUrl: string) => void;
  className?: string;
}

interface StepItem {
  label: string;
  title: string;
  content: string;
}

interface OptionItem {
  letter: string;
  status: 'correct' | 'wrong' | 'neutral';
  text: string;
}

// Maps Chinese step labels to suggested subtitle hints for public exam solutions
const STEP_HINTS: Record<string, string> = {
  第一步: '考点定位与审题',
  第二步: '规律推导与分析',
  第三步: '公式代入与计算',
  第四步: '综合判断与核验',
  第五步: '得出结论',
};

function healChineseLinebreaks(text: string): string {
  if (!text) return '';
  const lines = text.split('\n');
  const result: string[] = [];
  let buffer = '';

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    if (!trimmed) {
      if (buffer) {
        result.push(buffer);
        buffer = '';
      }
      result.push('');
      continue;
    }

    const isSpecial = /^(\#{1,6}\s|[-*+]\s|\d+[\.、]\s|第[一二三四五]步|[A-D]\s*(?:项|选项)[：:\s]|【|>|\||\$\$|\\\[|```|~~~|!\[|<img)/.test(trimmed);
    if (isSpecial) {
      if (buffer) {
        result.push(buffer);
        buffer = '';
      }
      buffer = trimmed;
      continue;
    }

    if (buffer) {
      const lastChar = buffer.slice(-1);
      const endsSentence = /[。！？!?]$/.test(buffer);
      const isBufferSpecial = /^(\#{1,6}\s|[-*+]\s|```|\|)/.test(buffer);

      if (!endsSentence && !isBufferSpecial && /[\u4e00-\u9fa5a-zA-Z0-9,，、；;（(《”’]/.test(lastChar)) {
        const firstChar = trimmed[0];
        const isBothCJK = /[\u4e00-\u9fa5]/.test(lastChar) && /[\u4e00-\u9fa5]/.test(firstChar);
        buffer = buffer + (isBothCJK ? '' : ' ') + trimmed;
      } else {
        result.push(buffer);
        buffer = trimmed;
      }
    } else {
      buffer = trimmed;
    }
  }
  if (buffer) result.push(buffer);
  return result.join('\n');
}

export function FormattedExplanation({
  text,
  standardAnswer,
  module,
  images,
  onZoom,
  className,
}: FormattedExplanationProps) {
  if (!text) return null;

  // 0. 解析中"如下图所示"所指的原图：题库题干/选项图，挂在解析顶部供对照
  const figureRefs = /如(?:下|上)图|下图|上图|如图|图中所示/.test(text);
  const showImages = Boolean(images?.length) && (figureRefs || module === '图形推理' || module === '立体图推');

  // 1. Clean noisy page headers and leaked following questions
  let cleaned = text.replace(/第\s*\d+\s*页\s*共\s*\d+\s*页/g, '');

  // Truncate leaked subsequent questions
  const matchNext = cleaned.search(/(?:因此[，,]?\s*选择|故本题选|故正确答案为|综上|答案为)[^。\n]*[。.]\s*(\d{1,3})\s*[\.、]\s*解析/);
  if (matchNext !== -1) {
    const endOfConc = cleaned.indexOf('。', matchNext) + 1;
    cleaned = cleaned.slice(0, endOfConc);
  } else {
    const allMatches = [...cleaned.matchAll(/(?:^|\n|\s{2,})(\d{1,3})\s*[\.、]\s*解析/g)];
    for (const m of allMatches) {
      if (m.index > 50) {
        cleaned = cleaned.slice(0, m.index);
        break;
      }
    }
  }

  // Remove leading redundant question index header like '1.解析\n' or '46.解析\n'
  cleaned = cleaned.replace(/(?:^|\n)\s*\d{1,3}\s*[\.、]\s*解析\s*/, '\n');

  // 2. Extract standard answer from text if not passed
  let ans = standardAnswer || '';
  const ansMatch = cleaned.match(/(?:题库标准答案[：:]|【答案】)\s*([A-D])/);
  if (ansMatch) {
    if (!ans) ans = ansMatch[1];
    cleaned = cleaned.replace(/(?:题库标准答案[：:]|【答案】)\s*[A-D]\s*[。.]?\n?/, '');
  }
  if (!ans) {
    const matchDangxuan = cleaned.match(/(?:对应\s*([A-D])\s*选项[，,]?\s*当选|当选[，,]?\s*对应\s*([A-D])\s*选项)/);
    if (matchDangxuan) {
      ans = matchDangxuan[1] || matchDangxuan[2];
    }
  }

  // 3. Extract metadata badges
  let sourceTag = '';
  const srcMatch = cleaned.match(/【(?:真题出处|出处)】\s*([^\n]+)/);
  if (srcMatch) {
    sourceTag = srcMatch[1].trim();
    cleaned = cleaned.replace(/【(?:真题出处|出处)】\s*[^\n]+\n?/, '');
  }

  let typeTag = '';
  const typeMatch = cleaned.match(/【(?:题型考点|题型分类|题型|考点归类|考点)】\s*([^\n]+)/);
  if (typeMatch) {
    typeTag = typeMatch[1].trim();
    cleaned = cleaned.replace(/【(?:题型考点|题型分类|题型|考点归类|考点)】\s*[^\n]+\n?/, '');
  }

  let difficultyTag = '';
  const diffMatch = cleaned.match(/【(?:难度评价|难度)】\s*([^\n]+)/);
  if (diffMatch) {
    difficultyTag = diffMatch[1].trim();
    cleaned = cleaned.replace(/【(?:难度评价|难度)】\s*[^\n]+\n?/, '');
  }

  // 4. Extract Teacher Notes / Pizhu
  let notesText = '';
  const noteMatch = cleaned.search(/【(?:名师批注|花生批注|批注|秒杀技巧|技巧点拨|速算技巧|坑点提示)】/);
  if (noteMatch !== -1) {
    notesText = cleaned.slice(noteMatch).replace(/^【(?:名师批注|花生批注|批注|秒杀技巧|技巧点拨|速算技巧|坑点提示)】\s*/, '').trim();
    cleaned = cleaned.slice(0, noteMatch).trim();
  }

  // 5. Extract Extension / Tuozhan (can be in notesText or cleaned)
  let extensionText = '';
  if (notesText) {
    const extInNotes = notesText.search(/(?:^|\n)\s*(?:【拓展】|拓展)\s*(?:\n|$)/);
    if (extInNotes !== -1) {
      extensionText = notesText.slice(extInNotes).replace(/^(?:^|\n)\s*(?:【拓展】|拓展)\s*\n?/, '').trim();
      notesText = notesText.slice(0, extInNotes).trim();
    }
  }
  if (!extensionText && cleaned) {
    const extMatch = cleaned.search(/(?:^|\n)\s*(?:【拓展】|拓展)\s*(?:\n|$)/);
    if (extMatch !== -1) {
      extensionText = cleaned.slice(extMatch).replace(/^(?:^|\n)\s*(?:【拓展】|拓展)\s*\n?/, '').trim();
      cleaned = cleaned.slice(0, extMatch).trim();
    }
  }

  // 6. Strip leading generic heading
  cleaned = cleaned.replace(/^【(?:实战解析|详细解析|参考解析|解析)】\s*/, '').trim();

  // 7. Extract conclusion
  let conclusion = '';
  const concRegex = /(因此[，,]?\s*选择\s*[A-D]\s*选项[。.]?|故本题选\s*[A-D][。.]?|综上(?:所述)?[，,]?\s*(?:本题)?选\s*[A-D](?:\s*选项)?[。.]?|故正确答案为\s*[A-D][。.]?|因此[，,]?\s*答案为\s*[A-D](?:\s*选项)?[。.]?|因此[，,]?\s*选\s*[A-D][。.]?|结合选项[，,]?\s*(?:选择|选)\s*[A-D](?:\s*选项)?[。.]?|故本题答案选\s*[A-D][。.]?)/;
  const mConc = cleaned.match(concRegex);
  if (mConc) {
    conclusion = mConc[1].trim();
    if (!ans) {
      const letterM = conclusion.match(/([A-D])/);
      if (letterM) ans = letterM[1];
    }
    cleaned = cleaned.replace(mConc[1], '').trim();
  }

  // 8. Detect Step Structure
  const stepSplits = cleaned.split(/(?:^|\n)\s*(第[一二三四五]步[，,:]?)/);
  let steps: StepItem[] | null = null;
  let stepsPreamble = '';
  if (stepSplits.length >= 5) {
    stepsPreamble = stepSplits[0].trim();
    steps = [];
    for (let i = 1; i < stepSplits.length; i += 2) {
      const label = stepSplits[i].replace(/[，,:]/g, '').trim();
      const body = (stepSplits[i + 1] || '').trim();
      const title = STEP_HINTS[label] || '';
      steps.push({ label, title, content: body });
    }
  }

  // 9. Detect Option Structure (only if not already split by steps)
  let options: OptionItem[] | null = null;
  let optionsPreamble = '';
  if (!steps) {
    const optRegex = /([A-D])\s*(?:项|选项)(?:[：:\s①-⑨\.]|$)/g;
    const matches = [...cleaned.matchAll(optRegex)];
    const uniqueLetters = new Set(matches.map(m => m[1]));
    if (uniqueLetters.size >= 2) {
      const firstIdx = matches[0].index ?? 0;
      optionsPreamble = cleaned.slice(0, firstIdx).trim();
      const optBody = cleaned.slice(firstIdx);
      options = [];
      for (let i = 0; i < matches.length; i++) {
        const letter = matches[i][1];
        const start = (matches[i].index ?? 0) - firstIdx;
        const end = i + 1 < matches.length ? (matches[i + 1].index ?? 0) - firstIdx : optBody.length;
        let chunk = optBody.slice(start, end).trim();
        chunk = chunk.replace(/^[A-D]\s*(?:项|选项)[：:\s①-⑨\.]*/, '').trim();

        let status: 'correct' | 'wrong' | 'neutral' = 'neutral';
        if (/当选|正确|契合|符合|与原文一致|与题干相符/.test(chunk) && !/不正确|不符合|不当选|并非/.test(chunk)) {
          status = 'correct';
        } else if (/排除|错误|不选|不符|不合|并非|未提及|未体现|未突出|偷换概念|无中生有|片面|曲解|相悖|反向|无关|过于绝对|偏离/.test(chunk)) {
          status = 'wrong';
        }
        options.push({ letter, status, text: chunk });
      }
    }
  }

  return (
    <div className={`formatted-explanation ${className || ''}`} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Badges Bar: Standard Answer & Metadata */}
      {(ans || sourceTag || typeTag || difficultyTag || module) && (
        <div className="explanation-header-bar">
          {ans && (
            <span className="explanation-badge answer">
              ✓ 题库标准答案：{ans}
            </span>
          )}
          {sourceTag && (
            <span className="explanation-badge source">
              🏛️ {sourceTag}
            </span>
          )}
          {typeTag && (
            <span className="explanation-badge topic">
              🎯 {typeTag}
            </span>
          )}
          {module && !typeTag && (
            <span className="explanation-badge topic">
              📂 {module}
            </span>
          )}
          {difficultyTag && (
            <span className="explanation-badge difficulty">
              ⭐ 难度：{difficultyTag}
            </span>
          )}
        </div>
      )}

      {/* 解析配图：原题/选项图，对照"如下图所示" */}
      {showImages && (
        <div style={{ padding: '10px 12px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#166534', marginBottom: 8 }}>
            📎 解析配图 · 文中“如下图所示”对照以下原图
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {images!.map((im, i) => (
              <img
                key={i}
                src={im.url}
                alt={im.label || `题图${i + 1}`}
                onClick={() => onZoom?.(im.url)}
                title="点击全屏高清放大"
                style={{ width: '100%', maxHeight: 460, objectFit: 'contain', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'zoom-in' }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Structured Steps Case */}
      {steps ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {stepsPreamble && <TeachingContent text={healChineseLinebreaks(stepsPreamble)} onZoom={onZoom} />}
          <div className="explanation-step-list">
            {steps.map((st, sIdx) => (
              <div key={sIdx} className="explanation-step-card">
                <div className="explanation-step-header">
                  <span className="explanation-step-pill">{st.label}</span>
                  {st.title && <span className="explanation-step-title">· {st.title}</span>}
                </div>
                <div className="explanation-step-body">
                  <TeachingContent text={healChineseLinebreaks(st.content)} onZoom={onZoom} />
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : options ? (
        /* Structured Options Case */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {optionsPreamble && <TeachingContent text={healChineseLinebreaks(optionsPreamble)} onZoom={onZoom} />}
          <div className="explanation-options-box">
            <div className="explanation-options-title">
              <span>🔍 选项逐项剖析：</span>
            </div>
            {options.map((opt, oIdx) => (
              <div key={oIdx} className={`explanation-option-card ${opt.status}`}>
                <div className="explanation-option-letter">{opt.letter}</div>
                <span className={`explanation-option-status ${opt.status}`}>
                  {opt.status === 'correct' ? '✓ 正确' : opt.status === 'wrong' ? '✕ 排除' : '分析'}
                </span>
                <div className="explanation-option-text">
                  <TeachingContent text={healChineseLinebreaks(opt.text)} onZoom={onZoom} />
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        /* Standard Markdown / Flowing Content Case */
        <TeachingContent text={healChineseLinebreaks(cleaned)} onZoom={onZoom} />
      )}

      {/* Conclusion Callout */}
      {conclusion && (
        <div className="explanation-conclusion-card">
          <span>🎯</span>
          <span>{conclusion}</span>
        </div>
      )}

      {/* Teacher Notes Callout */}
      {notesText && (
        <div className="explanation-notes-card">
          <div className="explanation-notes-head">
            <span>💡</span>
            <span>名师解题批注 & 秒杀思路</span>
          </div>
          <div className="explanation-notes-body">
            <TeachingContent text={healChineseLinebreaks(notesText)} onZoom={onZoom} />
          </div>
        </div>
      )}

      {/* Extension Callout */}
      {extensionText && (
        <div className="explanation-extension-card">
          <div className="explanation-extension-head">
            <span>📚</span>
            <span>知识拓展与延伸</span>
          </div>
          <div className="explanation-extension-body">
            <TeachingContent text={healChineseLinebreaks(extensionText)} onZoom={onZoom} />
          </div>
        </div>
      )}
    </div>
  );
}
