'use client';

import { MathJaxContext } from 'better-react-mathjax';

const config = {
  loader: { load: ['input/tex', 'output/chtml'] },
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
};

export default function MathJaxProvider({ children }: { children: React.ReactNode }) {
  return (
    <MathJaxContext version={3} config={config}>
      {children}
    </MathJaxContext>
  );
}
