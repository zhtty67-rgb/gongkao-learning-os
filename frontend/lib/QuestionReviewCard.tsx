import { useState } from 'react';
import { Result } from './api';
import { FormattedStem } from './FormattedStem';
import { QuestionNoteBox } from './QuestionNoteBox';

export function QuestionReviewCard({ result, revealAnswer = true }: { result: Result; revealAnswer?: boolean }) {
  const [previewImg, setPreviewImg] = useState<string | null>(null);
  const hasStem = Boolean(result.stem);
  const hasAssets = Boolean(result.stem_assets && result.stem_assets.length > 0);
  const hasOptions = Boolean(result.options && Object.keys(result.options).length > 0);
  const hasPassage = Boolean(result.passage && (result.passage.content || (result.passage.assets && result.passage.assets.length > 0)));

  if (!hasStem && !hasAssets && !hasOptions && !hasPassage) {
    return (
      <div className="panel-stem-review" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', color: 'var(--muted)', minHeight: 280 }}>
        <p>原题题干加载中…</p>
      </div>
    );
  }

  return (
    <div className="panel-stem-review">
      <div className="panel-stem-header">
        <span className="eyebrow" style={{ fontSize: 11, letterSpacing: '1.5px', color: 'var(--accent)', fontWeight: 'bold' }}>
          原题题干
        </span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {hasPassage && <span className="pill" style={{ fontSize: 11, padding: '2px 8px', background: '#e0f2fe', color: '#0369a1' }}>📑 包含材料</span>}
          {result.module && <span className="pill" style={{ fontSize: 11, padding: '2px 8px' }}>{result.module}</span>}
        </div>
      </div>

      {/* 资料分析 / 篇章阅读材料展示，确保语境完整不截断 */}
      {hasPassage && (
        <div style={{ marginBottom: 14, padding: '12px 14px', background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#334155', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span>📑 资料/篇章背景材料</span>
          </div>
          {result.passage!.content && (
            <div style={{ fontSize: 13.5, lineHeight: 1.75, color: '#1e293b', whiteSpace: 'pre-wrap', maxHeight: 280, overflowY: 'auto' }}>
              {result.passage!.content}
            </div>
          )}
          {result.passage!.assets && result.passage!.assets.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
              {result.passage!.assets.map((asset, aIdx) => (
                <img
                  key={aIdx}
                  src={asset}
                  alt={`材料图 ${aIdx + 1}`}
                  onClick={() => setPreviewImg(asset)}
                  title="点击全屏高清放大"
                  style={{ width: '100%', maxHeight: 560, objectFit: 'contain', borderRadius: 6, border: '1px solid #e2e8f0', background: '#fff', cursor: 'zoom-in', boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {hasStem && (
        <div className="panel-stem-text">
          <FormattedStem text={result.stem!} />
        </div>
      )}

      {/* 原题截图 / 配图，支持点击放大 */}
      {hasAssets && (
        <div
          className="stem-assets"
          style={{ margin: '14px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}
        >
          {result.stem_assets!.map((asset, idx) => (
            <div key={idx} style={{ textAlign: 'center', width: '100%' }}>
              <img
                src={asset}
                alt={`原题截图/配图 ${idx + 1}`}
                onClick={() => setPreviewImg(asset)}
                title="点击放大查看原题截图"
                style={{
                  width: '100%',
                  maxHeight: 520,
                  objectFit: 'contain',
                  borderRadius: 6,
                  border: '1px solid #e2e8f0',
                  background: '#fff',
                  padding: 6,
                  cursor: 'zoom-in',
                }}
              />
              <small style={{ display: 'block', color: 'var(--muted)', fontSize: 10, marginTop: 4 }}>
                🔍 点击查看高清原图
              </small>
            </div>
          ))}
        </div>
      )}

      {hasOptions && (
        <div className="options-review" style={{ marginTop: 14, display: 'grid', gap: 8 }}>
          {Object.entries(result.options!).map(([key, value]) => {
            const isSelected = key === result.selected_answer;
            const isCorrect = (revealAnswer && key === result.answer) || (isSelected && result.correct === true);
            let border = '1px solid var(--line)';
            let bg = '#fff';
            let badge = null;

            if (isCorrect && isSelected) {
              border = '1px solid var(--accent)';
              bg = '#edf5ef';
              badge = (
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>
                  ✓ 正确答案 · 你的选择
                </span>
              );
            } else if (isCorrect) {
              border = '1px solid var(--accent)';
              bg = '#edf5ef';
              badge = (
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>
                  ✓ 标准答案
                </span>
              );
            } else if (isSelected) {
              border = '1px solid #f0a996';
              bg = '#fff5f2';
              badge = (
                <span style={{ marginLeft: 'auto', fontSize: 11, color: '#b91c1c', fontWeight: 600 }}>
                  你的选择
                </span>
              );
            }

            return (
              <div
                key={key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '9px 13px',
                  borderRadius: 6,
                  border,
                  background: bg,
                  fontSize: 13,
                  lineHeight: 1.4,
                }}
              >
                <strong style={{ marginRight: 8, minWidth: 20, color: 'var(--ink)' }}>{key}.</strong>
                <span style={{ color: 'var(--ink)' }}>{value === key ? '' : value}</span>
                {badge}
              </div>
            );
          })}
        </div>
      )}

      {/* 个人心得与感悟笔记 */}
      <QuestionNoteBox
        questionId={result.question_id}
        attemptId={result.id}
        module={result.module}
      />

      {/* 原图放大灯箱 Modal */}
      {previewImg && (
        <div
          onClick={() => setPreviewImg(null)}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: '100vw',
            height: '100vh',
            background: 'rgba(0,0,0,0.75)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'zoom-out',
            padding: 24,
          }}
        >
          <img
            src={previewImg}
            alt="高清大图"
            style={{ maxWidth: '90%', maxHeight: '90%', objectFit: 'contain', background: '#fff', borderRadius: 8, padding: 8, boxShadow: '0 8px 32px rgba(0,0,0,0.4)' }}
          />
        </div>
      )}
    </div>
  );
}
