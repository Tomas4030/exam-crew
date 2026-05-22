'use client';

import { useMemo } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

/** Renders text with inline LaTeX (\( ... \)) and display LaTeX (\[ ... \]) */
export default function MathText({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => renderMath(text), [text]);
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}

function renderMath(text: string): string {
  // Split on \( ... \) and \[ ... \]
  const parts = text.split(/(\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])/g);
  return parts.map(part => {
    if (part.startsWith('\\(') && part.endsWith('\\)')) {
      const latex = part.slice(2, -2);
      try { return katex.renderToString(latex, { throwOnError: false }); }
      catch { return part; }
    }
    if (part.startsWith('\\[') && part.endsWith('\\]')) {
      const latex = part.slice(2, -2);
      try { return katex.renderToString(latex, { throwOnError: false, displayMode: true }); }
      catch { return part; }
    }
    // Escape HTML in plain text
    return part.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br/>');
  }).join('');
}
