// 三档作答信心：纯蒙题 / 半猜 / 有信心。
// 存储沿用 attempts.confidence 数值列；三档映射 0.2 / 0.5 / 0.9，
// 历史五档记录（0.2/0.4/0.6/0.8/1.0）原值保留，按阈值归入对应档位展示：
// ≤0.4 归纯蒙题（FSRS Hard 同一口径）、0.5~0.6 归半猜、≥0.8 归有信心（高信心错误同口径）。
export const CONFIDENCE_TIERS = [
  { value: 0.2, label: '纯蒙题' },
  { value: 0.5, label: '半猜' },
  { value: 0.9, label: '有信心' },
] as const;

export const CONFIDENCE_DRAFT_VALUES = [null, 0.2, 0.4, 0.5, 0.6, 0.8, 0.9, 1];

export function confidenceLabel(value: number | null | undefined): string {
  if (value === null || value === undefined) return '未记录';
  if (value <= 0.4) return '纯蒙题';
  if (value <= 0.6) return '半猜';
  return '有信心';
}
