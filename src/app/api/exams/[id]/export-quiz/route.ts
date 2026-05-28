import { NextRequest, NextResponse } from "next/server";
import path from "path";
import fs from "fs";
import archiver from "archiver";

export const runtime = "nodejs";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyObj = Record<string, any>;

type RouteContext = {
  params: { id: string } | Promise<{ id: string }>;
};

type AssetState = {
  usedAssets: Map<string, string>;
  pathRewrite: Map<string, string>;
};

const OUTPUT_DIR = path.join(process.cwd(), "data", "output");
const ASSET_FOLDERS = ["", "visual", "context", "sources", "quiz"];

export async function GET(_request: NextRequest, context: RouteContext) {
  try {
    const { id } = await Promise.resolve(context.params);
    const safeId = sanitizeId(id);

    if (!safeId) {
      return NextResponse.json({ error: "Invalid exam id" }, { status: 400 });
    }

    const outputDir = path.resolve(OUTPUT_DIR);
    const examDir = safeJoin(outputDir, safeId);
    const jsonPath = safeJoin(outputDir, `${safeId}.json`);
    const assetsDir = safeJoin(examDir, "assets");

    if (!fs.existsSync(jsonPath)) {
      return NextResponse.json({ error: "Exam not found" }, { status: 404 });
    }

    const examData = readJson(jsonPath);
    const assetState: AssetState = {
      usedAssets: new Map<string, string>(),
      pathRewrite: new Map<string, string>(),
    };

    collectAllAssets(examData, examDir, assetsDir, assetState);

    const clientData = buildClientData(examData, assetState);
    const zipFilename = makeZipFilename(clientData, safeId);
    const zipBuffer = await createZipBuffer(clientData, assetState.usedAssets);

    return new NextResponse(zipBuffer as unknown as BodyInit, {
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": contentDispositionAttachment(zipFilename),
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    console.error("[quiz-export]", error);
    return NextResponse.json(
      { error: "Could not export quiz" },
      { status: 500 },
    );
  }
}

function sanitizeId(id: string) {
  const value = String(id || "").trim();
  return /^[a-zA-Z0-9_-]+$/.test(value) ? value : null;
}

function safeJoin(baseDir: string, ...segments: string[]) {
  const target = path.resolve(baseDir, ...segments);
  const base = path.resolve(baseDir);

  if (target !== base && !target.startsWith(base + path.sep)) {
    throw new Error(`Unsafe path: ${target}`);
  }

  return target;
}

function readJson(filePath: string) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    throw new Error(`Invalid JSON file: ${filePath}`);
  }
}

function makeZipFilename(clientData: AnyObj, id: string) {
  const subject = slugPart(clientData.metadata?.subject || "Exame");
  const year = slugPart(clientData.metadata?.year || "");
  const phase = String(clientData.metadata?.phase || "").replace(/[^0-9]/g, "");
  const shortId = id.split("_").pop() || id.slice(-8);

  return `Quiz_${subject}${year}${phase ? `Fase${phase}` : ""}_${shortId}.zip`;
}

function slugPart(value: unknown) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]/g, "");
}

function contentDispositionAttachment(filename: string) {
  const ascii = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
  const utf8 = encodeURIComponent(filename);
  return `attachment; filename="${ascii}"; filename*=UTF-8''${utf8}`;
}

function normalizeAssetPath(input?: string): string | null {
  if (!input) return null;

  let clean = String(input).trim().replace(/\\/g, "/");

  try {
    if (/^https?:\/\//i.test(clean)) {
      const url = new URL(clean);
      clean = url.pathname;
    }
  } catch {
    return null;
  }

  const marker = "/assets/";
  if (clean.includes(marker)) {
    clean = `assets/${clean.split(marker).pop()}`;
  }

  clean = decodeURIComponent(clean).replace(/^\.\//, "").replace(/^\/+/, "");

  if (!clean) return null;
  if (clean.includes("\0")) return null;
  if (clean.split("/").includes("..")) return null;

  if (!clean.startsWith("assets/")) {
    clean = `assets/${clean}`;
  }

  return clean;
}

function addAsset(
  relPath: string | undefined,
  examDir: string,
  assetsDir: string,
  state: AssetState,
) {
  const clean = normalizeAssetPath(relPath);
  if (!clean) return null;

  const exactPath = safeJoin(examDir, clean);

  if (fs.existsSync(exactPath)) {
    state.usedAssets.set(clean, exactPath);
    state.pathRewrite.set(clean, clean);
    return clean;
  }

  const filename = path.basename(clean);

  for (const folder of ASSET_FOLDERS) {
    const candidate = safeJoin(assetsDir, folder, filename);

    if (fs.existsSync(candidate)) {
      const zipPath = path.relative(examDir, candidate).replace(/\\/g, "/");
      state.usedAssets.set(zipPath, candidate);
      state.pathRewrite.set(clean, zipPath);
      return zipPath;
    }
  }

  return null;
}

function getBestAssetPath(asset?: AnyObj): string | undefined {
  if (!asset) return undefined;

  return (
    asset.crops?.best?.relativePath ||
    asset.crop?.relativePath ||
    asset.crops?.visual?.relativePath ||
    asset.crops?.context?.relativePath ||
    asset.crops?.full?.relativePath ||
    asset.relativePath ||
    asset.url
  );
}

function getBestSourcePath(source?: AnyObj): string | undefined {
  if (!source) return undefined;

  return (
    source.crops?.best?.relativePath ||
    source.crops?.document?.relativePath ||
    source.crops?.full?.relativePath ||
    source.crops?.visual?.relativePath ||
    source.crops?.context?.relativePath ||
    source.relativePath ||
    source.url
  );
}

function collectAllAssets(
  examData: AnyObj,
  examDir: string,
  assetsDir: string,
  state: AssetState,
) {
  const assetsById = new Map<string, AnyObj>(
    (examData.assets || []).map((asset: AnyObj) => [asset.id, asset]),
  );
  const sourcesById = new Map<string, AnyObj>(
    (examData.sources || []).map((source: AnyObj) => [source.sourceId, source]),
  );

  for (const question of examData.questions || []) {
    collectAssetsFromQuestion(
      question,
      assetsById,
      sourcesById,
      examDir,
      assetsDir,
      state,
    );
  }
}

function collectAssetsFromQuestion(
  question: AnyObj,
  assetsById: Map<string, AnyObj>,
  sourcesById: Map<string, AnyObj>,
  examDir: string,
  assetsDir: string,
  state: AssetState,
) {
  for (const media of question.media || []) {
    addAsset(media.relativePath || media.url, examDir, assetsDir, state);
  }

  for (const ref of question.sourceRefs || []) {
    const source = sourcesById.get(ref.sourceId);
    if (!source) continue;

    if (source.kind === "image_set" && source.assetRefs?.length) {
      for (const assetId of source.assetRefs) {
        addAsset(
          getBestAssetPath(assetsById.get(assetId)),
          examDir,
          assetsDir,
          state,
        );
      }
    } else {
      addAsset(getBestSourcePath(source), examDir, assetsDir, state);
    }
  }

  const directRefs = [
    ...(question.imageRefs || []),
    ...(question.assetRefs || []),
    ...(question.tableRefs || []),
  ];

  for (const assetId of directRefs) {
    addAsset(
      getBestAssetPath(assetsById.get(assetId)),
      examDir,
      assetsDir,
      state,
    );
  }
}

function buildClientData(examData: AnyObj, state: AssetState) {
  const clientData = structuredCloneSafe(examData);

  delete clientData._pdf_path;
  delete clientData.rawVision;
  delete clientData.debug;

  for (const source of clientData.sources || []) {
    if (source.crops?.full && !source.crops.best) {
      source.crops.best = source.crops.full;
    }
  }

  rewritePathsDeep(clientData, state.pathRewrite);

  for (const question of clientData.questions || []) {
    delete question.sourceTextRaw;
    delete question.rawVision;
    delete question.debug;
  }

  return clientData;
}

function structuredCloneSafe<T>(value: T): T {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function rewritePathsDeep(value: unknown, pathRewrite: Map<string, string>) {
  if (!value || typeof value !== "object") return;

  if (Array.isArray(value)) {
    for (const item of value) rewritePathsDeep(item, pathRewrite);
    return;
  }

  const obj = value as AnyObj;

  for (const key of ["relativePath", "url"]) {
    if (typeof obj[key] !== "string") continue;

    const clean = normalizeAssetPath(obj[key]);
    if (!clean) continue;

    const rewritten = pathRewrite.get(clean) || clean;
    obj[key] = rewritten;
  }

  for (const child of Object.values(obj)) {
    rewritePathsDeep(child, pathRewrite);
  }
}

async function createZipBuffer(
  clientData: AnyObj,
  usedAssets: Map<string, string>,
) {
  const archive = archiver("zip", { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  return new Promise<Buffer>((resolve, reject) => {
    archive.on("data", (chunk: Buffer) => chunks.push(chunk));
    archive.on("warning", reject);
    archive.on("error", reject);
    archive.on("end", () => resolve(Buffer.concat(chunks)));

    archive.append(indexHtml(clientData), { name: "index.html" });
    archive.append(STYLES_CSS, { name: "styles.css" });
    archive.append(APP_JS, { name: "app.js" });
    archive.append(JSON.stringify(clientData, null, 2), {
      name: "data/exam.json",
    });

    for (const [zipPath, absPath] of usedAssets) {
      archive.file(absPath, { name: zipPath });
    }

    archive.finalize();
  });
}

function safeJsonForScript(data: unknown) {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function escapeHtml(input: unknown) {
  return String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function indexHtml(clientData: AnyObj) {
  const title = [
    clientData.metadata?.subject || "Quiz",
    clientData.metadata?.year,
    clientData.metadata?.phase,
  ]
    .filter(Boolean)
    .join(" ");

  return `<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>${escapeHtml(title)}</title>
  <link rel="stylesheet" href="./styles.css">
  <script>
    window.MathJax = {
      tex: {
        inlineMath: [['\\\\(','\\\\)']],
        displayMath: [['\\\\[','\\\\]']],
        macros: {
          sen: '\\\\operatorname{sen}',
          tg: '\\\\operatorname{tg}',
          cotg: '\\\\operatorname{cotg}'
        }
      },
      startup: { typeset: false }
    };
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
  <script>window.EXAM_DATA = ${safeJsonForScript(clientData)};</script>
  <script defer src="./app.js"></script>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">Quiz de exame</p>
        <h1>${escapeHtml(title || "Quiz")}</h1>
        <p id="subtitle" class="muted"></p>
      </div>
      <div class="score-card">
        <span id="progress-label">0 / 0</span>
        <div class="progressbar" aria-hidden="true"><span id="progress-bar"></span></div>
      </div>
    </header>

    <section class="workspace">
      <aside class="sidebar" aria-label="Navegação das perguntas">
        <div class="sidebar-title">Perguntas</div>
        <div id="question-nav" class="question-nav"></div>
      </aside>

      <section class="main-panel">
        <article id="question-card" class="question-card"></article>
        <nav class="bottom-nav">
          <button id="prev-btn" type="button" class="secondary">← Anterior</button>
          <button id="next-btn" type="button">Seguinte →</button>
        </nav>
      </section>
    </section>
  </main>
</body>
</html>`;
}

const STYLES_CSS = `:root{
  --bg:#eef3fb;
  --panel:#ffffff;
  --text:#111827;
  --muted:#64748b;
  --line:#dbe3ef;
  --line-strong:#c7d2e4;
  --brand:#2457d6;
  --brand-dark:#1d46ad;
  --brand-soft:#e8efff;
  --ok:#16a34a;
  --ok-soft:#e8f8ee;
  --shadow:0 18px 45px rgba(15,23,42,.10);
  --radius:22px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at top left,#ffffff 0,#eef3fb 38%,#e7edf7 100%);color:var(--text)}
button,input,select,textarea{font:inherit}
button{border:0;background:var(--brand);color:#fff;border-radius:999px;padding:11px 18px;font-weight:800;cursor:pointer;box-shadow:0 8px 18px rgba(36,87,214,.18);transition:transform .15s ease,background .15s ease,opacity .15s ease}
button:hover{background:var(--brand-dark);transform:translateY(-1px)}
button:disabled{opacity:.45;cursor:not-allowed;transform:none}
button.secondary{background:#fff;color:#243047;border:1px solid var(--line);box-shadow:none}
button.secondary:hover{background:#f8fafc}
.shell{max-width:1240px;margin:0 auto;padding:28px}
.hero{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:22px;padding:26px;border:1px solid rgba(255,255,255,.85);border-radius:var(--radius);background:rgba(255,255,255,.72);backdrop-filter:blur(14px);box-shadow:var(--shadow)}
.eyebrow{margin:0 0 8px;text-transform:uppercase;letter-spacing:.12em;font-size:.72rem;font-weight:900;color:var(--brand)}
.hero h1{margin:0;font-size:clamp(1.55rem,2.8vw,2.35rem);line-height:1.08}
.muted{margin:9px 0 0;color:var(--muted)}
.score-card{min-width:190px;background:#fff;border:1px solid var(--line);border-radius:18px;padding:14px 16px;color:#334155;font-weight:900;text-align:right}
.progressbar{height:8px;background:#eef2f7;border-radius:999px;margin-top:10px;overflow:hidden}
.progressbar span{display:block;height:100%;width:0%;background:linear-gradient(90deg,var(--brand),#4f8df7);border-radius:999px;transition:width .2s ease}
.workspace{display:grid;grid-template-columns:245px minmax(0,1fr);gap:22px;align-items:start}
.sidebar{position:sticky;top:22px;background:rgba(255,255,255,.78);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.9);border-radius:var(--radius);padding:16px;box-shadow:0 10px 28px rgba(15,23,42,.07)}
.sidebar-title{font-size:.78rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:900;margin:0 0 12px}
.question-nav{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}
.qnav-btn{border:1px solid var(--line);background:#fff;color:#334155;border-radius:14px;aspect-ratio:1/1;padding:0;font-size:.82rem;font-weight:900;box-shadow:none}
.qnav-btn:hover{background:var(--brand-soft);border-color:#b9caf8;color:var(--brand);transform:none}
.qnav-btn.active{background:var(--brand);border-color:var(--brand);color:#fff;box-shadow:0 10px 22px rgba(36,87,214,.22)}
.qnav-btn.answered:not(.active){background:var(--ok-soft);border-color:#b7ebc8;color:#166534}
.question-card{background:#fff;border:1px solid rgba(255,255,255,.95);border-radius:var(--radius);padding:30px;box-shadow:var(--shadow);min-height:520px}
.q-header{display:flex;gap:10px;align-items:center;margin-bottom:18px;flex-wrap:wrap;color:var(--muted)}
.badge{display:inline-flex;align-items:center;border-radius:999px;background:var(--brand-soft);color:#1e3a8a;padding:6px 12px;font-size:.86rem;font-weight:900}
.pill{display:inline-flex;align-items:center;border-radius:999px;background:#f8fafc;border:1px solid var(--line);padding:6px 10px;font-size:.82rem;font-weight:800;color:#475569}
.q-type{margin-left:auto;color:#94a3b8;font-size:.82rem;font-weight:800}
.asset-list{display:grid;gap:16px;margin:2px 0 22px}
.asset-frame{border:1px solid var(--line);border-radius:18px;background:#f8fafc;padding:10px;overflow:hidden}
.asset-img{display:block;max-width:100%;max-height:620px;object-fit:contain;margin:0 auto;border-radius:12px;background:white}
.statement{line-height:1.78;font-size:1.07rem;margin:0 0 22px;white-space:pre-wrap;color:#172033}
.options{display:grid;gap:11px;margin-top:18px}
.option{display:flex;gap:13px;align-items:flex-start;border:1px solid var(--line);background:#fff;padding:15px 16px;border-radius:16px;cursor:pointer;transition:background .15s,border-color .15s,box-shadow .15s}
.option:hover{background:#f8fbff;border-color:#bdd0fb}
.option.selected{background:var(--brand-soft);border-color:#7ca2f4;box-shadow:0 10px 20px rgba(36,87,214,.08)}
.option input{margin-top:5px;accent-color:var(--brand)}
.option-letter{font-weight:950;color:#334155;margin-right:4px}
textarea{width:100%;min-height:190px;border:1px solid var(--line-strong);border-radius:18px;padding:16px;resize:vertical;background:#fbfdff;color:var(--text);line-height:1.6}
textarea:focus,select:focus{outline:3px solid rgba(36,87,214,.16);border-color:#7ca2f4}
.blank-table-wrap{overflow-x:auto;margin:20px 0;border-radius:18px;border:1px solid var(--line);background:#fff}
.blank-table{width:100%;border-collapse:collapse;font-size:.95rem}
.blank-table th,.blank-table td{border:1px solid var(--line);padding:12px;vertical-align:top}
.blank-table th{background:#f4f7fb;text-align:center;font-weight:950;color:#334155}
.blank-controls{display:flex;gap:12px;flex-wrap:wrap;margin-top:14px;background:#f8fafc;border:1px solid var(--line);border-radius:18px;padding:14px}
.blank-controls label{display:flex;gap:8px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:14px;padding:9px 11px;min-width:118px}
.blank-controls select{padding:7px 9px;border:1px solid var(--line-strong);border-radius:10px;background:#fff}
.group-box{border:1px solid var(--line);background:#f8fafc;border-radius:18px;padding:16px;margin-top:18px}
.group-box h3{margin:0 0 10px;font-size:1rem}
.child-link{display:block;width:100%;border:1px solid var(--line);background:#fff;color:#334155;text-align:left;border-radius:14px;padding:12px 14px;margin-top:9px;box-shadow:none}
.child-link:hover{background:var(--brand-soft);border-color:#bdd0fb;color:var(--brand);transform:none}
.bottom-nav{display:flex;justify-content:space-between;margin-top:18px;gap:12px}
.empty{color:var(--muted);font-style:italic;margin:0}
@media (max-width:900px){.shell{padding:16px}.hero{flex-direction:column}.score-card{width:100%;text-align:left}.workspace{grid-template-columns:1fr}.sidebar{position:static}.question-nav{grid-template-columns:repeat(8,1fr)}.question-card{padding:22px;min-height:360px}}
@media (max-width:560px){.question-nav{grid-template-columns:repeat(5,1fr)}.blank-controls{display:grid;grid-template-columns:1fr 1fr}.bottom-nav button{width:100%}.bottom-nav{flex-direction:column-reverse}.q-type{margin-left:0;width:100%}}
@media print{body{background:#fff}.shell{padding:0}.hero,.sidebar,.bottom-nav{display:none}.workspace{display:block}.question-card{box-shadow:none;border:0;padding:0}.asset-img{max-height:none}}
`;

const APP_JS = `const state = {
  exam: null,
  questions: [],
  current: 0,
  answers: {},
  storageKey: 'quiz_answers',
};

function init() {
  state.exam = window.EXAM_DATA;

  const card = document.getElementById('question-card');
  if (!state.exam) {
    card.innerHTML = '<p class="empty">Não foi possível carregar os dados do exame.</p>';
    return;
  }

  state.storageKey = 'quiz_answers_' + (state.exam.exam_id || document.title || 'local');
  state.answers = loadAnswers();
  state.questions = getVisibleQuestions(state.exam.questions || []);

  document.getElementById('subtitle').textContent = [
    state.exam.metadata?.year,
    state.exam.metadata?.phase,
    state.exam.metadata?.processingStatus === 'needs_review' ? 'necessita revisão' : '',
  ].filter(Boolean).join(' · ');

  document.getElementById('prev-btn').addEventListener('click', () => move(-1));
  document.getElementById('next-btn').addEventListener('click', () => move(1));

  render();
}

function getVisibleQuestions(questions) {
  return questions.filter(q =>
    q.statement ||
    q.statementPlain ||
    q.statementLatex ||
    q.options?.length ||
    q.blanks?.length ||
    q.assetRefs?.length ||
    q.imageRefs?.length ||
    q.tableRefs?.length ||
    q.sourceRefs?.length ||
    q.media?.length
  );
}

function loadAnswers() {
  try {
    return JSON.parse(localStorage.getItem(state.storageKey) || '{}');
  } catch {
    return {};
  }
}

function saveAnswers() {
  localStorage.setItem(state.storageKey, JSON.stringify(state.answers));
}

function move(delta) {
  const next = state.current + delta;
  if (next < 0 || next >= state.questions.length) return;
  state.current = next;
  render();
}

function goTo(index) {
  state.current = index;
  render();
}

window.goTo = goTo;
window.setAnswer = setAnswer;

function setAnswer(key, value) {
  state.answers[key] = value;
  saveAnswers();
  renderNav();
  updateOptionSelection(key, value);
}

function updateOptionSelection(questionId, value) {
  const labels = document.querySelectorAll('[data-question-id="' + cssEscape(questionId) + '"] .option');
  labels.forEach(label => {
    const input = label.querySelector('input');
    label.classList.toggle('selected', input?.value === value);
  });
}

function render() {
  const q = state.questions[state.current];
  const card = document.getElementById('question-card');

  renderNav();
  renderProgress();

  document.getElementById('prev-btn').disabled = state.current === 0;
  document.getElementById('next-btn').disabled = state.current === state.questions.length - 1;

  if (!q) {
    card.innerHTML = '<p class="empty">Sem perguntas.</p>';
    return;
  }

  const children = state.questions.filter(child => child.parentQuestion === q.questionId);
  const isGroup = Boolean(q.isGroup || q.type === 'group' || children.length > 0);

  card.dataset.questionId = q.questionId || '';
  card.innerHTML =
    '<div class="q-header">' +
      '<span class="badge">' + esc(q.displayNumber || ('Q' + (q.number ?? state.current + 1))) + '</span>' +
      (q.points ? '<span class="pill">' + esc(q.points) + ' pts</span>' : '') +
      (q.optional ? '<span class="pill">Opcional</span>' : '') +
      '<span class="q-type">' + esc(labelType(q.type)) + '</span>' +
    '</div>' +
    renderImages(q) +
    '<div class="statement">' + formatText(statement(q)) + '</div>' +
    (isGroup ? renderGroupChildren(children) : renderAnswer(q));

  if (window.MathJax?.typesetPromise) {
    window.MathJax.typesetPromise([card]).catch(() => {});
  }
}

function renderProgress() {
  const total = state.questions.length;
  const done = state.questions.filter(hasAnswer).length;
  const current = total ? state.current + 1 : 0;

  document.getElementById('progress-label').textContent = current + ' / ' + total + ' · ' + done + ' respondidas';
  document.getElementById('progress-bar').style.width = total ? ((current / total) * 100) + '%' : '0%';
}

function renderNav() {
  const nav = document.getElementById('question-nav');

  nav.innerHTML = state.questions.map((q, index) => {
    const classes = [
      'qnav-btn',
      index === state.current ? 'active' : '',
      hasAnswer(q) ? 'answered' : '',
    ].filter(Boolean).join(' ');

    return '<button type="button" class="' + classes + '" onclick="goTo(' + index + ')">' +
      esc(q.displayNumber || q.number || index + 1) +
    '</button>';
  }).join('');
}

function hasAnswer(q) {
  if (!q) return false;

  if (q.type === 'multi_blank_choice' && q.blanks?.length) {
    return q.blanks.some(blank => state.answers[q.questionId + '_' + blank.number]);
  }

  return Boolean(state.answers[q.questionId]);
}

function statement(q) {
  const latex = String(q.statementLatex || '');
  const badLatex =
    latex.includes('�') ||
    latex.includes('\\\\begin{center}') ||
    latex.includes('\\\\begin{tabular}') ||
    latex.includes('\\\\_\\\\_') ||
    q.textQuality?.status === 'corrupt';

  const raw = badLatex
    ? (q.statementPlain || q.statement || '')
    : (q.statementLatex || q.statementPlain || q.statement || '');

  return String(raw)
    .replace(/\\\\begin\{center\}[\s\S]*?\\\\end\{center\}/g, '')
    .replace(/\\\\begin\{tabular\}[\s\S]*?\\\\end\{tabular\}/g, '')
    .replace(/\\\\begin\{itemize\}/g, '')
    .replace(/\\\\end\{itemize\}/g, '')
    .replace(/\\\\item\s*/g, '• ')
    .replace(/\\\\textsuperscript\{a\}/g, 'ª')
    .replace(/\\\\textsuperscript\{o\}/g, 'º')
    .replace(/\\\\degree/g, 'º')
    .trim();
}

function renderImages(q) {
  const html = [];
  const seen = new Set();

  for (const path of collectImagePaths(q)) {
    const clean = cleanPath(path);
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    html.push('<figure class="asset-frame"><img class="asset-img" src="./' + esc(clean) + '" alt="Documento da pergunta" loading="lazy"></figure>');
  }

  return html.length ? '<div class="asset-list">' + html.join('') + '</div>' : '';
}

function collectImagePaths(q) {
  const paths = [];

  if (q.sourceRefs?.length) {
    for (const ref of q.sourceRefs) {
      const source = (state.exam.sources || []).find(s => s.sourceId === ref.sourceId);
      if (!source) continue;

      if (source.kind === 'image_set' && source.assetRefs?.length) {
        for (const assetId of source.assetRefs) {
          paths.push(getAssetPath(findAsset(assetId)));
        }
      } else {
        paths.push(getSourcePath(source));
      }
    }

    if (paths.some(Boolean)) return paths;
  }

  for (const assetId of [...(q.assetRefs || []), ...(q.imageRefs || []), ...(q.tableRefs || [])]) {
    paths.push(getAssetPath(findAsset(assetId)));
  }

  if (!paths.some(Boolean) && q.media?.length) {
    for (const media of q.media) paths.push(media.relativePath || media.url);
  }

  return paths;
}

function findAsset(id) {
  return (state.exam.assets || []).find(asset => asset.id === id);
}

function getAssetPath(asset) {
  if (!asset) return '';
  return asset.crops?.best?.relativePath || asset.crop?.relativePath || asset.crops?.visual?.relativePath || asset.crops?.context?.relativePath || asset.crops?.full?.relativePath || asset.relativePath || asset.url || '';
}

function getSourcePath(source) {
  if (!source) return '';
  return source.crops?.best?.relativePath || source.crops?.document?.relativePath || source.crops?.full?.relativePath || source.crops?.visual?.relativePath || source.crops?.context?.relativePath || source.relativePath || source.url || '';
}

function renderAnswer(q) {
  if (q.type === 'multiple_choice' && q.options?.length) {
    return renderOptions(q);
  }

  if (q.type === 'multi_blank_choice' && q.blanks?.length) {
    return renderBlanks(q);
  }

  const value = state.answers[q.questionId] || '';

  return '<textarea placeholder="Escreva a sua resposta..." oninput="setAnswer(\'' + escJs(q.questionId) + '\', this.value)">' + esc(value) + '</textarea>';
}

function renderOptions(q) {
  return '<div class="options">' + q.options.map(option => {
    const isSelected = state.answers[q.questionId] === option.letter;

    return '<label class="option ' + (isSelected ? 'selected' : '') + '">' +
      '<input type="radio" name="' + esc(q.questionId) + '" value="' + esc(option.letter) + '" ' + (isSelected ? 'checked' : '') +
      ' onchange="setAnswer(\'' + escJs(q.questionId) + '\', this.value)">' +
      '<span><span class="option-letter">(' + esc(option.letter) + ')</span> ' + formatText(option.latex || option.text || '') + '</span>' +
    '</label>';
  }).join('') + '</div>';
}

function renderBlanks(q) {
  const maxRows = Math.max(...q.blanks.map(blank => blank.options.length));
  let table = '<div class="blank-table-wrap"><table class="blank-table"><thead><tr>' +
    q.blanks.map(blank => '<th>' + esc(blank.number) + '</th>').join('') +
    '</tr></thead><tbody>';

  for (let i = 0; i < maxRows; i++) {
    table += '<tr>' + q.blanks.map(blank => {
      const option = blank.options[i];
      return '<td>' + (option ? '<strong>' + esc(option.letter) + ')</strong> ' + formatText(option.text || option.latex || '') : '') + '</td>';
    }).join('') + '</tr>';
  }

  table += '</tbody></table></div>';

  const controls = '<div class="blank-controls">' + q.blanks.map(blank => {
    const key = q.questionId + '_' + blank.number;
    const current = state.answers[key] || '';

    return '<label><strong>' + esc(blank.number) + '</strong>' +
      '<select onchange="setAnswer(\'' + escJs(key) + '\', this.value)">' +
        '<option value="">—</option>' +
        blank.options.map(option => '<option value="' + esc(option.letter) + '"' + (current === option.letter ? ' selected' : '') + '>' + esc(option.letter) + ')</option>').join('') +
      '</select></label>';
  }).join('') + '</div>';

  return table + controls;
}

function renderGroupChildren(children) {
  if (!children.length) {
    return '<div class="group-box"><p class="empty">Este grupo não tem subquestões extraídas.</p></div>';
  }

  return '<div class="group-box"><h3>Subquestões</h3>' +
    children
      .sort((a, b) => String(a.number).localeCompare(String(b.number), undefined, { numeric: true }))
      .map(child => {
        const index = state.questions.findIndex(q => q.questionId === child.questionId);
        return '<button type="button" class="child-link" onclick="goTo(' + index + ')"><strong>' + esc(child.displayNumber || child.number) + '</strong> · ' + esc(labelType(child.type)) + '</button>';
      }).join('') +
    '</div>';
}

function labelType(type) {
  const labels = {
    multiple_choice: 'Escolha múltipla',
    multi_blank_choice: 'Associação / espaços',
    open_answer: 'Resposta aberta',
    group: 'Grupo',
  };
  return labels[type] || type || '';
}

function cleanPath(value) {
  if (!value) return '';
  return String(value).replace(/\\\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '');
}

function formatText(value) {
  return esc(value).replace(/\n/g, '<br>');
}

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function escJs(value) {
  return String(value ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
}

init();
`;
 