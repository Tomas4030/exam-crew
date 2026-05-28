import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const outputDir = path.join(process.cwd(), 'data', 'output');
  const jsonPath = path.join(outputDir, `${id}.json`);

  if (!fs.existsSync(jsonPath)) {
    return NextResponse.json({ error: 'Exam not found' }, { status: 404 });
  }

  const examData = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
  const subject = (examData.metadata?.subject || 'Exame')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9]/g, '');
  const year = examData.metadata?.year || '';
  const phase = (examData.metadata?.phase || '').replace(/[^0-9]/g, '');
  const shortId = id.split('_').pop() || id.slice(-8);
  const zipFilename = `Quiz_${subject}${year}${phase ? `Fase${phase}` : ''}_${shortId}.zip`;

  // Collect used asset paths
  const usedAssets = new Map<string, string>(); // relativePath → absPath
  const assetsDir = path.join(outputDir, id, 'assets');

  function addAsset(relPath?: string) {
    if (!relPath) return;
    const clean = relPath.replace(/\\/g, '/');
    const filename = path.basename(clean);
    const absPath = path.join(outputDir, id, clean);
    if (!fs.existsSync(absPath)) {
      // Try flat
      const flat = path.join(assetsDir, filename);
      if (fs.existsSync(flat)) { usedAssets.set(`assets/${filename}`, flat); return; }
      return;
    }
    usedAssets.set(`assets/${filename}`, absPath);
  }

  for (const q of examData.questions || []) {
    for (const m of q.media || []) {
      if (m.url) { const f = m.url.split('/assets/').pop(); if (f) addAsset(`assets/${f}`); }
    }
    for (const ref of [...(q.imageRefs || []), ...(q.assetRefs || []), ...(q.tableRefs || [])]) {
      const asset = (examData.assets || []).find((a: any) => a.id === ref);
      if (!asset) continue;
      addAsset(asset.crops?.best?.relativePath || asset.crop?.relativePath || asset.crops?.visual?.relativePath || asset.crops?.context?.relativePath);
    }
  }
  for (const src of examData.sources || []) {
    addAsset(src.crops?.best?.relativePath || src.crops?.full?.relativePath);
  }

  // Rewrite exam JSON for client: relativePaths → assets/filename
  const clientData = JSON.parse(JSON.stringify(examData));
  delete clientData._pdf_path;

  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    archive.append(JSON.stringify(clientData, null, 2), { name: 'data/exam.json' });
    archive.append(INDEX_HTML(examData), { name: 'index.html' });
    archive.append(STYLES_CSS, { name: 'styles.css' });
    archive.append(APP_JS, { name: 'app.js' });

    for (const [zipPath, absPath] of usedAssets) {
      archive.file(absPath, { name: zipPath });
    }

    archive.finalize();
  });

  return new NextResponse(Buffer.concat(chunks), {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${zipFilename}"`,
    },
  });
}

function INDEX_HTML(exam: any) {
  const title = `${exam.metadata?.subject || 'Quiz'} ${exam.metadata?.year || ''} ${exam.metadata?.phase || ''}`.trim();
  return `<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<link rel="stylesheet" href="./styles.css">
<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']],macros:{sen:'\\\\operatorname{sen}',tg:'\\\\operatorname{tg}'}},startup:{typeset:false}};</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
<script defer src="./app.js"></script>
</head>
<body>
<main class="app">
<header class="topbar"><h1>${title}</h1><div id="progress"></div></header>
<section id="question-card" class="card"></section>
<nav class="nav"><button id="prev-btn">← Anterior</button><button id="next-btn">Seguinte →</button></nav>
</main>
</body>
</html>`;
}

const STYLES_CSS = `*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f8f9fa;color:#1a1a1a}
.app{max-width:860px;margin:0 auto;padding:24px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.topbar h1{font-size:1.25rem;margin:0}
.card{background:#fff;border:1px solid #e2e5e9;border-radius:14px;padding:28px;box-shadow:0 1px 4px rgba(0,0,0,.05);min-height:300px}
.q-header{display:flex;gap:12px;align-items:center;margin-bottom:16px;font-size:.9rem;color:#555}
.q-header strong{color:#1a1a1a;font-size:1rem}
.statement{line-height:1.75;font-size:1.05rem;margin:16px 0;white-space:pre-wrap}
.asset-img{display:block;max-width:100%;max-height:520px;object-fit:contain;margin:0 auto 20px;border:1px solid #e2e5e9;border-radius:10px;background:#fff}
.options{display:flex;flex-direction:column;gap:8px}
.option{display:flex;align-items:flex-start;gap:10px;border:1px solid #e2e5e9;padding:12px 16px;border-radius:10px;cursor:pointer;transition:background .15s}
.option:hover{background:#f0f4ff}
.option input{margin-top:3px}
textarea{width:100%;min-height:140px;border:1px solid #d1d5db;border-radius:10px;padding:14px;font:inherit;resize:vertical}
.blank-table{width:100%;border-collapse:collapse;margin:16px 0;font-size:.95rem}
.blank-table th,.blank-table td{border:1px solid #333;padding:10px;text-align:center}
.blank-table th{background:#f3f4f6}
.blank-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:14px}
.blank-controls label{display:flex;gap:8px;align-items:center;border:1px solid #e2e5e9;border-radius:8px;padding:8px 12px}
.blank-controls select{flex:1;padding:5px;border:1px solid #d1d5db;border-radius:6px;background:#fff}
.nav{display:flex;justify-content:space-between;margin-top:24px}
button{border:0;background:#2563eb;color:#fff;border-radius:8px;padding:10px 20px;font-weight:600;cursor:pointer;font-size:.95rem}
button:hover{background:#1d4ed8}
button:disabled{opacity:.4;cursor:default}`;

const APP_JS = `let exam,questions,current=0;
async function init(){
const r=await fetch('./data/exam.json');exam=await r.json();
questions=exam.questions.filter(q=>q.statement||q.options?.length||q.blanks?.length);
document.getElementById('prev-btn').onclick=()=>{if(current>0){current--;render()}};
document.getElementById('next-btn').onclick=()=>{if(current<questions.length-1){current++;render()}};
render()}
function render(){
const q=questions[current],card=document.getElementById('question-card');
document.getElementById('progress').textContent=(current+1)+' / '+questions.length;
document.getElementById('prev-btn').disabled=current===0;
document.getElementById('next-btn').disabled=current===questions.length-1;
card.innerHTML=\`<div class="q-header"><strong>\${q.displayNumber||'Q'+q.number}</strong>\${q.points?'<span>'+q.points+' pts</span>':''}<small>\${q.type}</small></div>\${imgs(q)}<div class="statement">\${fmt(stmt(q))}</div>\${ans(q)}\`;
if(window.MathJax?.typesetPromise)window.MathJax.typesetPromise([card])}
function stmt(q){const t=q.statementLatex||q.statementPlain||q.statement||'';return t.replace(/\\\\begin\\{tabular\\}[\\s\\S]*?\\\\end\\{tabular\\}/g,'').replace(/\\\\begin\\{center\\}[\\s\\S]*?\\\\end\\{center\\}/g,'').replace(/\\\\begin\\{itemize\\}/g,'').replace(/\\\\end\\{itemize\\}/g,'').replace(/\\\\item\\s*/g,'• ').replace(/\\\\textsuperscript\\{a\\}/g,'ª').replace(/\\\\degree/g,'º').trim()}
function fmt(t){return t.replace(/\\n/g,'<br>')}
function imgs(q){
const refs=[...(q.assetRefs||[]),...(q.imageRefs||[]),...(q.tableRefs||[])];
const seen=new Set();let html='';
for(const id of refs){if(seen.has(id))continue;seen.add(id);
const a=exam.assets.find(x=>x.id===id);if(!a)continue;
const p=a.crops?.best?.relativePath||a.crop?.relativePath||a.crops?.visual?.relativePath||a.crops?.context?.relativePath;
if(p)html+='<img class="asset-img" src="./'+p.replace(/\\\\\\\\/g,'/')+'">'}
if(!html&&q.sourceRefs?.length){for(const ref of q.sourceRefs){
const s=(exam.sources||[]).find(x=>x.sourceId===ref.sourceId);if(!s)continue;
const p=s.crops?.best?.relativePath||s.crops?.full?.relativePath;
if(p)html+='<img class="asset-img" src="./'+p.replace(/\\\\\\\\/g,'/')+'">'}}
return html}
function ans(q){
if(q.type==='multiple_choice'&&q.options?.length)return'<div class="options">'+q.options.map(o=>'<label class="option"><input type="radio" name="'+q.questionId+'" value="'+o.letter+'"><span>('+o.letter+') '+(o.latex||o.text)+'</span></label>').join('')+'</div>';
if(q.type==='multi_blank_choice'&&q.blanks?.length)return renderBlanks(q);
return'<textarea placeholder="Escreva a sua resposta..."></textarea>'}
function renderBlanks(q){
const mx=Math.max(...q.blanks.map(b=>b.options.length));
let t='<table class="blank-table"><thead><tr>'+q.blanks.map(b=>'<th>'+b.number+'</th>').join('')+'</tr></thead><tbody>';
for(let i=0;i<mx;i++){t+='<tr>'+q.blanks.map(b=>{const o=b.options[i];return'<td>'+(o?o.letter+') '+o.text:'')+'</td>'}).join('')+'</tr>'}
t+='</tbody></table>';
t+='<div class="blank-controls">'+q.blanks.map(b=>'<label><strong>'+b.number+'</strong><select><option value="">—</option>'+b.options.map(o=>'<option value="'+o.letter+'">'+o.letter+')</option>').join('')+'</select></label>').join('')+'</div>';
return t}
init();`;
