'use client';

import { useEffect, useState, createContext, useContext } from 'react';

const MathJaxReady = createContext(false);
export const useMathJaxReady = () => useContext(MathJaxReady);

declare global {
  interface Window { MathJax?: any; }
}

export default function MathJaxProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (window.MathJax?.typesetPromise) {
      queueMicrotask(() => setReady(true));
      return;
    }

    const existing = document.getElementById('mathjax-script');
    if (existing) { existing.addEventListener('load', () => setReady(true)); return; }

    window.MathJax = {
      tex: {
        inlineMath: [['\\(', '\\)']],
        displayMath: [['\\[', '\\]']],
        packages: { '[+]': ['ams'] },
        macros: {
          sen: '\\operatorname{sen}',
          tg: '\\operatorname{tg}',
          cotg: '\\operatorname{cotg}',
          arcsen: '\\operatorname{arcsen}',
          arctg: '\\operatorname{arctg}',
        },
      },
      startup: { typeset: false },
    };

    const script = document.createElement('script');
    script.id = 'mathjax-script';
    script.src = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js';
    script.async = true;
    script.onload = () => setReady(true);
    script.onerror = () => console.error('Failed to load MathJax');
    document.head.appendChild(script);
  }, []);

  return <MathJaxReady.Provider value={ready}>{children}</MathJaxReady.Provider>;
}
