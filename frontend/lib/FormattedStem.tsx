import React from 'react';

interface FormattedStemProps {
  text: string;
}

export function FormattedStem({ text }: FormattedStemProps) {
  if (!text) return null;

  // Split on underline placeholder (______ or 4+ underscores) or <u> tags
  const parts = text.split(/(<u>.*?<\/u>|_{4,})/g);

  return (
    <>
      {parts.map((part, index) => {
        if (/^_{4,}$/.test(part)) {
          return (
            <span
              key={index}
              className="stem-blank"
              title="横线填空处"
              aria-label="横线填空处"
            >
              &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
            </span>
          );
        }
        if (part.startsWith('<u>') && part.endsWith('</u>')) {
          const content = part.slice(3, -4);
          return (
            <u key={index} className="stem-underline">
              {content}
            </u>
          );
        }
        return <React.Fragment key={index}>{part}</React.Fragment>;
      })}
    </>
  );
}
