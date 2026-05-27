'use client';

import { useEffect, useRef } from 'react';
import { useMathJaxReady } from './MathJaxProvider';

function normalize(text: string): string {
  if (!text) return '';
  return text
    .replace(/\\\((\d+)\.\\degree\\\)/g, '$1.º')
    .replace(/\\degree/g, 'º')
    .replace(/\\textsuperscript\{a\}/g, 'ª')
    .replace(/\\textsuperscript\{o\}/g, 'º')
    .replace(/\\begin\{center\}/g, '')
    .replace(/\\end\{center\}/g, '')
    .replace(/\\begin\{itemize\}/g, '')
    .replace(/\\end\{itemize\}/g, '')
    .replace(/\\item\s*/g, '• ')
    .replace(/\\begin\{tabular\}[\s\S]*?\\end\{tabular\}/g, '')
    .replace(/\\hline/g, '')
    .trim();
}

export default function MathText({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const ready = useMathJaxReady();

  useEffect(() => {
    if (ready && ref.current && window.MathJax?.typesetPromise) {
      window.MathJax.typesetPromise([ref.current]).catch(() => {});
    }
  }, [ready, text]);

  return <span ref={ref} className={className}>{normalize(text)}</span>;
}
