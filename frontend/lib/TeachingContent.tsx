'use client';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

// Older teacher messages use OpenAI-style delimiters. Preserve code verbatim.
export function normalizeMath(text: string) {
  return text.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g).map((part, i) => i % 2 ? part : part
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => `\n\n$$\n${math.trim()}\n$$\n\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => `$${math.trim()}$`)).join('');
}

export function TeachingContent({ text, onZoom }: { text: string; onZoom?: (src: string) => void }) {
  return <div className="teaching-content">
    <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { throwOnError: false, trust: false, strict: 'ignore' }]]}
      components={{
        a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
        img: ({ src, alt }) => <img src={src} alt={alt || '解析图'} onClick={() => typeof src === 'string' && onZoom?.(src)} style={{ maxWidth: '100%', cursor: onZoom ? 'zoom-in' : 'default' }} />,
        table: ({ children }) => <div className="teaching-table"><table>{children}</table></div>,
      }} skipHtml>{normalizeMath(text)}</Markdown>
  </div>;
}
