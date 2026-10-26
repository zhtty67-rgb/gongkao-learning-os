export function RecordedTime({ elapsedMs, timingValid }: { elapsedMs: number; timingValid?: boolean | number }) {
  const invalid = timingValid === false || timingValid === 0 || !Number.isFinite(elapsedMs) || elapsedMs < 1000 || elapsedMs > 14400000;
  if (invalid) return <span title="该记录的计时不可信，未计入速度统计；原始值仍保留。">计时无效</span>;
  const seconds = Math.floor(elapsedMs / 1000);
  return <>{Math.floor(seconds / 60).toString().padStart(2, '0')}:{(seconds % 60).toString().padStart(2, '0')}</>;
}
