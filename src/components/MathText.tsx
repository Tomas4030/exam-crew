'use client';

import { MathJax } from 'better-react-mathjax';

function normalize(text: string): string {
  if (!text) return '';
  return text
    // Fix Portuguese ordinals wrongly converted to LaTeX
    .replace(/\\\((\d+)\.\\degree\\\)/g, '$1.º')
    .replace(/\\\((\d+)\\\.º\\\)/g, '$1.º')
    .replace(/\\degree/g, 'º')
    .replace(/\\textsuperscript\{a\}/g, 'ª')
    .replace(/\\textsuperscript\{o\}/g, 'º')
    // Strip tabular/center environments (rendered as assets instead)
    .replace(/\\begin\{center\}[\s\S]*?\\end\{center\}/g, '')
    .replace(/\\begin\{tabular\}[\s\S]*?\\end\{tabular\}/g, '')
    .replace(/\\hline/g, '')
    .trim();
}

export default function MathText({ text, className }: { text: string; className?: string }) {
  return (
    <MathJax dynamic hideUntilTypeset="first" inline className={className}>
      {normalize(text)}
    </MathJax>
  );
}
