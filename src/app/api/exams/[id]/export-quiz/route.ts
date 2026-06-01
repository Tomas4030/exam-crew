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
  const directRefs = [
    ...(question.imageRefs || []),
    ...(question.assetRefs || []),
    ...(question.tableRefs || []),
  ];

  // 1) Assets diretos da pergunta. Estes são quase sempre os crops certos.
  for (const assetId of directRefs) {
    addAsset(
      getBestAssetPath(assetsById.get(assetId)),
      examDir,
      assetsDir,
      state,
    );
  }

  // 2) Sources. Se uma source tiver assetRefs, usa os assets/crops concretos.
  // Só usa o crop da source/documento como fallback quando não existem assetRefs.
  for (const ref of question.sourceRefs || []) {
    const source = sourcesById.get(ref.sourceId);
    if (!source) continue;

    // Specific child — use childCrops first, then assetRefs by index
    if (ref.childId) {
      const childCrops = (source as AnyObj).childCrops as AnyObj | undefined;
      const cropsChildren = (source.crops as AnyObj)?.children as AnyObj | undefined;
      const childCrop = childCrops?.[ref.childId] || cropsChildren?.[ref.childId];
      if (childCrop) {
        addAsset(childCrop.relativePath || childCrop.url, examDir, assetsDir, state);
        continue;
      }
      if (source.assetRefs?.length) {
        const letter = String(ref.childId).split('_').pop()?.toLowerCase() || 'a';
        const idx = letter.charCodeAt(0) - 'a'.charCodeAt(0);
        if (idx >= 0 && idx < source.assetRefs.length) {
          addAsset(getBestAssetPath(assetsById.get(source.assetRefs[idx])), examDir, assetsDir, state);
        }
      }
      continue;
    }

    // Full document — always use source crop
    addAsset(getBestSourcePath(source), examDir, assetsDir, state);
  }

  // 3) Media só como fallback de empacotamento.
  // O app.js também só usa media se não houver refs melhores.
  for (const media of question.media || []) {
    addAsset(media.relativePath || media.url, examDir, assetsDir, state);
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
    archive.append(`window.EXAM_DATA = ${safeJsonForScript(clientData)};`, {
      name: "data.js",
    });
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
  <link rel="stylesheet" href="styles.css">
  <script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']],processEscapes:true,macros:{sen:'\\\\operatorname{sen}',tg:'\\\\operatorname{tg}',cotg:'\\\\operatorname{cotg}',arctg:'\\\\operatorname{arctg}'}},startup:{typeset:false}};</script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
  <script defer src="data.js"></script>
  <script defer src="app.js"></script>
</head>
<body>
  <main class="shell">
    <section class="workspace">
      <aside class="sidebar" aria-label="Navegação das perguntas">
        <div class="exam-brand">
          <div class="exam-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path d="M5.5 4.5h5.25c1.1 0 2 .9 2 2v13c0 .28-.22.5-.5.5h-5.7A3.05 3.05 0 0 1 3.5 16.95V6.5c0-1.1.9-2 2-2Z" fill="none" stroke="currentColor" stroke-width="1.8"/>
              <path d="M18.5 4.5h-5.25c-1.1 0-2 .9-2 2v13c0 .28.22.5.5.5h5.7a3.05 3.05 0 0 0 3.05-3.05V6.5c0-1.1-.9-2-2-2Z" fill="none" stroke="currentColor" stroke-width="1.8"/>
            </svg>
          </div>
          <div>
            <p class="eyebrow">Exame</p>
            <h1>${escapeHtml(title || "Quiz")}</h1>
            <p id="subtitle" class="muted"></p>
          </div>
        </div>

        <div class="score-card sidebar-score">
          <span id="progress-label">0 / 0 · 0 respondidas</span>
          <div class="progressbar" aria-hidden="true"><span id="progress-bar"></span></div>
        </div>

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
  --bg:#f4f7fb;
  --panel:#ffffff;
  --text:#111827;
  --muted:#64748b;
  --line:#dbe3ef;
  --line-strong:#cbd7e6;
  --brand:#2457d6;
  --brand-dark:#1d46ad;
  --brand-soft:#eaf1ff;
  --ok:#16a34a;
  --ok-soft:#e8f8ee;
  --shadow:0 18px 45px rgba(15,23,42,.08);
  --radius:22px;
}
*{box-sizing:border-box}
html{height:100%;scroll-behavior:smooth}
body{
  height:100%;
  margin:0;
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:
    radial-gradient(circle at top left,#ffffff 0,#f5f8fd 36%,#edf3fb 100%);
  color:var(--text);
  overflow:hidden;
}
button,input,select,textarea{font:inherit}
button{
  border:0;
  background:var(--brand);
  color:#fff;
  border-radius:999px;
  padding:12px 22px;
  font-weight:900;
  cursor:pointer;
  box-shadow:0 10px 22px rgba(36,87,214,.20);
  transition:transform .15s ease,background .15s ease,opacity .15s ease,box-shadow .15s ease;
}
button:hover{background:var(--brand-dark);transform:translateY(-1px)}
button:disabled{opacity:.45;cursor:not-allowed;transform:none;box-shadow:none}
button.secondary{
  background:#fff;
  color:var(--brand);
  border:1px solid var(--line);
  box-shadow:none;
}
button.secondary:hover{background:#f8fbff;border-color:#bdd0fb}

.shell{
  width:100%;
  height:100vh;
  max-width:none;
  margin:0;
  padding:18px;
  overflow:hidden;
}
.workspace{
  height:100%;
  min-height:0;
  display:grid;
  grid-template-columns:280px minmax(0,1fr);
  gap:26px;
  align-items:stretch;
}

/* Sidebar */
.sidebar{
  height:100%;
  min-height:0;
  display:flex;
  flex-direction:column;
  overflow:hidden;
  background:rgba(255,255,255,.86);
  backdrop-filter:blur(16px);
  border:1px solid rgba(255,255,255,.96);
  border-radius:26px;
  padding:26px 22px;
  box-shadow:0 18px 44px rgba(15,23,42,.08);
}
.exam-brand{
  display:grid;
  grid-template-columns:42px minmax(0,1fr);
  gap:13px;
  align-items:center;
  margin-bottom:16px;
}
.exam-icon{
  width:38px;
  height:38px;
  display:grid;
  place-items:center;
  border-radius:14px;
  color:var(--brand);
  background:var(--brand-soft);
  box-shadow:inset 0 0 0 1px rgba(36,87,214,.08);
}
.eyebrow{
  margin:0 0 6px;
  text-transform:uppercase;
  letter-spacing:.12em;
  font-size:.70rem;
  font-weight:950;
  color:var(--brand);
}
.exam-brand h1{
  margin:0;
  font-size:1.02rem;
  line-height:1.2;
  font-weight:950;
  color:#172033;
  letter-spacing:-.01em;
}
.muted{margin:4px 0 0;color:var(--muted);font-size:.78rem}
.sidebar-title{
  font-size:.76rem;
  text-transform:uppercase;
  letter-spacing:.18em;
  color:var(--muted);
  font-weight:950;
  margin:0 0 14px;
}
.question-nav{
  flex:1 1 auto;
  min-height:0;
  display:grid;
  grid-template-columns:1fr;
  gap:9px;
  align-content:start;
  overflow-y:auto;
  padding-right:4px;
  scrollbar-width:thin;
}
.question-nav::-webkit-scrollbar,.question-card::-webkit-scrollbar{width:8px}
.question-nav::-webkit-scrollbar-thumb,.question-card::-webkit-scrollbar-thumb{background:#cbd7e6;border-radius:999px}
.qnav-btn{
  position:relative;
  border:1px solid var(--line);
  background:#fff;
  color:#21314a;
  border-radius:16px;
  min-height:44px;
  padding:9px 12px 9px 42px;
  font-size:.82rem;
  font-weight:900;
  box-shadow:none;
  text-align:left;
  display:grid;
  grid-template-columns:auto 1fr;
  gap:14px;
  align-items:center;
  line-height:1.15;
}
.qnav-btn::before{
  content:"";
  position:absolute;
  left:16px;
  top:50%;
  width:13px;
  height:13px;
  transform:translateY(-50%);
  border-radius:999px;
  border:2px solid #c6d2e3;
  background:#fff;
}
.qnav-btn:hover{background:#f8fbff;border-color:#bdd0fb;color:var(--brand);transform:none}
.qnav-main{font-size:.82rem;font-weight:950;white-space:nowrap}
.qnav-sub{font-size:.74rem;font-weight:850;color:var(--muted);white-space:nowrap}
.qnav-btn.active{
  background:linear-gradient(180deg,#3165e4 0%,#2457d6 100%);
  border-color:var(--brand);
  color:#fff;
  box-shadow:0 12px 24px rgba(36,87,214,.25);
}
.qnav-btn.active::before{
  border-color:#fff;
  background:#fff;
  box-shadow:inset 0 0 0 3px var(--brand);
}
.qnav-btn.active .qnav-sub{color:rgba(255,255,255,.82)}
.qnav-btn.answered:not(.active){background:var(--ok-soft);border-color:#b7ebc8;color:#166534}
.qnav-btn.answered:not(.active)::before{border-color:#22c55e;background:#22c55e}

/* Main */
.main-panel{
  min-height:0;
  display:grid;
  grid-template-rows:minmax(0,1fr) 58px;
  overflow:hidden;
}
.score-card{
  width:100%;
  background:rgba(255,255,255,.88);
  border:1px solid var(--line);
  border-radius:16px;
  padding:11px 13px 12px;
  color:#172033;
  font-weight:950;
  text-align:left;
  box-shadow:0 10px 24px rgba(15,23,42,.04);
}
.sidebar-score{
  margin:0 0 28px;
}
.progressbar{
  height:7px;
  background:#edf2f8;
  border-radius:999px;
  margin-top:10px;
  overflow:hidden;
}
.progressbar span{
  display:block;
  height:100%;
  width:0%;
  background:linear-gradient(90deg,var(--brand),#4f8df7);
  border-radius:999px;
  transition:width .2s ease;
}
.question-card{
  min-height:0;
  overflow-y:auto;
  background:rgba(255,255,255,.92);
  border:1px solid rgba(255,255,255,.96);
  border-radius:24px;
  padding:24px;
  box-shadow:var(--shadow);
  scrollbar-width:thin;
}
.q-header{
  display:flex;
  gap:10px;
  align-items:center;
  margin-bottom:18px;
  flex-wrap:wrap;
  color:var(--muted);
}
.badge{
  display:inline-flex;
  align-items:center;
  border-radius:999px;
  background:var(--brand-soft);
  color:#1d4ed8;
  padding:7px 13px;
  font-size:.86rem;
  font-weight:950;
}
.pill{
  display:inline-flex;
  align-items:center;
  border-radius:999px;
  background:#edf2f8;
  border:1px solid var(--line);
  padding:7px 12px;
  font-size:.82rem;
  font-weight:900;
  color:#475569;
}
.q-type{
  margin-left:auto;
  color:#3568da;
  background:#eef4ff;
  border-radius:999px;
  padding:7px 13px;
  font-size:.78rem;
  font-weight:900;
}
.asset-list{display:grid;gap:16px;margin:0 0 20px}
.asset-frame{
  border:1px solid var(--line);
  border-radius:20px;
  background:#f8fafc;
  padding:12px;
  overflow:hidden;
  min-height:310px;
  display:flex;
  align-items:center;
  justify-content:center;
}
.asset-img{
  display:block;
  max-width:100%;
  max-height:min(46vh,560px);
  object-fit:contain;
  margin:0 auto;
  border-radius:10px;
  background:white;
}
.statement{
  line-height:1.72;
  font-size:1rem;
  margin:0 0 18px;
  white-space:pre-wrap;
  color:#21314a;
}
.options{
  display:grid;
  gap:10px;
  margin-top:16px;
}
.option{
  display:grid;
  grid-template-columns:18px auto minmax(0,1fr);
  align-items:center;
  gap:12px;
  min-height:52px;
  border:1px solid var(--line);
  background:#fff;
  padding:12px 16px;
  border-radius:16px;
  cursor:pointer;
  transition:background .15s,border-color .15s,box-shadow .15s;
}
.option:hover{background:#f8fbff;border-color:#bdd0fb}
.option.selected{background:var(--brand-soft);border-color:#7ca2f4;box-shadow:0 10px 20px rgba(36,87,214,.08)}
.option input{margin:0;accent-color:var(--brand)}
.option-letter{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:34px;
  height:28px;
  border-radius:999px;
  background:#f5f8ff;
  border:1px solid #dbe7ff;
  color:var(--brand);
  font-weight:950;
  line-height:1;
  white-space:nowrap;
}
.option-text{
  min-width:0;
  color:#172033;
  line-height:1.45;
  white-space:normal;
}
textarea{
  width:100%;
  min-height:190px;
  border:1px solid var(--line-strong);
  border-radius:18px;
  padding:16px;
  resize:vertical;
  background:#fbfdff;
  color:var(--text);
  line-height:1.6;
}
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
.bottom-nav{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
  padding:16px 8px 0;
}
.bottom-nav button{min-width:138px}
.empty{color:var(--muted);font-style:italic;margin:0}

@media (max-width:900px){
  body{overflow:auto}
  .shell{height:auto;min-height:100vh;padding:14px;overflow:visible}
  .workspace{display:grid;grid-template-columns:1fr;min-height:auto;overflow:visible;gap:14px}
  .sidebar{height:auto;max-height:none;padding:18px}
  .exam-brand{margin-bottom:22px}
  .question-nav{grid-template-columns:repeat(2,1fr);overflow:visible;padding-right:0}
  .main-panel{display:flex;flex-direction:column;overflow:visible}
  .question-card{min-height:360px;overflow:visible;padding:20px}
}
@media (max-width:560px){
  .question-nav{grid-template-columns:1fr}
  .score-card{width:100%}
  .blank-controls{display:grid;grid-template-columns:1fr 1fr}
  .bottom-nav button{width:100%}
  .bottom-nav{flex-direction:column-reverse;padding:14px 0 0}
  .q-type{margin-left:0;width:100%;justify-content:center}
  .option{grid-template-columns:20px 32px minmax(0,1fr);padding:12px}
}
@media print{
  body{background:#fff;overflow:visible}
  .shell{padding:0;height:auto}
  .sidebar,.bottom-nav{display:none}
  .workspace{display:block}
  .question-card{box-shadow:none;border:0;padding:0;overflow:visible}
  .asset-img{max-height:none}
}
mjx-container{outline:none;max-width:100%;overflow-x:auto}
mjx-container[display="true"]{display:block;margin:1rem 0}
.statement{overflow-wrap:anywhere}
.option-text{overflow-wrap:anywhere}
`;
const APP_JS = String.raw`const state = {
  exam: null,
  questions: [],
  current: 0,
  answers: {},
  storageKey: 'quiz_answers',
  canUseStorage: true
};

function init() {
  state.exam = window.EXAM_DATA || null;

  var card = document.getElementById('question-card');
  if (!card) return;

  if (!state.exam) {
    fetch('./data/exam.json')
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(data) {
        state.exam = data;
        bootApp();
      })
      .catch(function(err) {
        card.innerHTML =
          '<main style="padding:24px;font-family:sans-serif">' +
          '<h1>Erro ao carregar quiz</h1>' +
          '<p>' + esc(err.message) + '</p>' +
          '<p>Extrai o ZIP primeiro e abre o index.html dentro da pasta extraída.</p>' +
          '</main>';
      });
    return;
  }

  bootApp();
}

function bootApp() {
  state.storageKey = 'quiz_answers_' + safeStorageKey(state.exam.exam_id || document.title || 'local');
  state.answers = loadAnswers();
  state.questions = getVisibleQuestions(state.exam.questions || []);

  var subtitle = document.getElementById('subtitle');
  if (subtitle) {
    subtitle.textContent = [
      state.exam.metadata && state.exam.metadata.year,
      state.exam.metadata && state.exam.metadata.phase,
      state.exam.metadata && state.exam.metadata.processingStatus === 'needs_review' ? 'necessita revisão' : ''
    ].filter(Boolean).join(' · ');
  }

  var prev = document.getElementById('prev-btn');
  var next = document.getElementById('next-btn');

  if (prev) prev.addEventListener('click', function() { move(-1); });
  if (next) next.addEventListener('click', function() { move(1); });

  render();
}

function safeStorageKey(value) {
  return String(value || 'local').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function getVisibleQuestions(questions) {
  return questions.filter(function(q) {
    return q &&
      (q.statement ||
      q.statementPlain ||
      q.statementLatex ||
      (q.options && q.options.length) ||
      (q.blanks && q.blanks.length) ||
      (q.assetRefs && q.assetRefs.length) ||
      (q.imageRefs && q.imageRefs.length) ||
      (q.tableRefs && q.tableRefs.length) ||
      (q.sourceRefs && q.sourceRefs.length) ||
      (q.media && q.media.length));
  });
}

function loadAnswers() {
  try {
    return JSON.parse(window.localStorage.getItem(state.storageKey) || '{}');
  } catch (error) {
    state.canUseStorage = false;
    return {};
  }
}

function saveAnswers() {
  if (!state.canUseStorage) return;

  try {
    window.localStorage.setItem(state.storageKey, JSON.stringify(state.answers));
  } catch (error) {
    state.canUseStorage = false;
  }
}

function move(delta) {
  var next = state.current + delta;
  if (next < 0 || next >= state.questions.length) return;
  state.current = next;
  render();
}

function goTo(index) {
  if (index < 0 || index >= state.questions.length) return;
  state.current = index;
  render();
}

window.goTo = goTo;

function setAnswer(key, value) {
  state.answers[key] = value;
  saveAnswers();
  renderNav();
  updateOptionSelection(key, value);
}

function updateOptionSelection(questionId, value) {
  var selector = '[data-question-id="' + cssEscape(questionId) + '"] .option';
  var labels = document.querySelectorAll(selector);

  labels.forEach(function(label) {
    var input = label.querySelector('input');
    label.classList.toggle('selected', input && input.value === value);
  });
}

function render() {
  var q = state.questions[state.current];
  var card = document.getElementById('question-card');

  renderNav();
  renderProgress();

  var prev = document.getElementById('prev-btn');
  var next = document.getElementById('next-btn');

  if (prev) prev.disabled = state.current === 0;
  if (next) next.disabled = state.current === state.questions.length - 1;

  if (!q) {
    card.innerHTML = '<p class="empty">Sem perguntas.</p>';
    return;
  }

  var children = state.questions.filter(function(child) {
    return child.parentQuestion === q.questionId;
  });

  var isGroup = Boolean(q.isGroup || q.type === 'group' || children.length > 0);

  card.dataset.questionId = q.questionId || '';
  card.innerHTML =
    '<div class="q-header">' +
      '<span class="badge">' + esc(q.displayNumber || ('Q' + (q.number == null ? state.current + 1 : q.number))) + '</span>' +
      (q.points ? '<span class="pill">' + esc(q.points) + ' pts</span>' : '') +
      (q.optional ? '<span class="pill">Opcional</span>' : '') +
      '<span class="q-type">' + esc(labelType(q.type)) + '</span>' +
    '</div>' +
    renderImages(q) +
    '<div class="statement">' + formatText(statement(q)) + '</div>' +
    (isGroup ? renderGroupChildren(children) : renderAnswer(q));

  bindQuestionEvents(card);
  if(window.MathJax&&window.MathJax.typesetPromise){window.MathJax.typesetPromise([card]).catch(function(){});}
}

function bindQuestionEvents(root) {
  root.querySelectorAll('[data-answer-key]').forEach(function(el) {
    var key = el.getAttribute('data-answer-key');
    if (!key) return;

    var eventName = el.tagName === 'TEXTAREA' ? 'input' : 'change';

    el.addEventListener(eventName, function(event) {
      setAnswer(key, event.target.value);
    });
  });

  root.querySelectorAll('[data-go-to]').forEach(function(el) {
    el.addEventListener('click', function() {
      var index = Number(el.getAttribute('data-go-to'));
      if (Number.isInteger(index)) goTo(index);
    });
  });
}

function renderProgress() {
  var total = state.questions.length;
  var done = state.questions.filter(hasAnswer).length;
  var current = total ? state.current + 1 : 0;

  var label = document.getElementById('progress-label');
  var bar = document.getElementById('progress-bar');

  if (label) label.textContent = current + ' / ' + total + ' · ' + done + ' respondidas';
  if (bar) bar.style.width = total ? ((current / total) * 100) + '%' : '0%';
}

function renderNav() {
  var nav = document.getElementById('question-nav');
  if (!nav) return;

  nav.innerHTML = state.questions.map(function(q, index) {
    var classes = [
      'qnav-btn',
      index === state.current ? 'active' : '',
      hasAnswer(q) ? 'answered' : ''
    ].filter(Boolean).join(' ');

    var label = navLabel(q, index);

    return '<button type="button" class="' + classes + '" data-go-to="' + index + '">' +
      '<span class="qnav-main">' + esc(label.main) + '</span>' +
      '<span class="qnav-sub">' + esc(label.sub) + '</span>' +
    '</button>';
  }).join('');

  nav.querySelectorAll('[data-go-to]').forEach(function(button) {
    button.addEventListener('click', function() {
      var index = Number(button.getAttribute('data-go-to'));
      if (Number.isInteger(index)) goTo(index);
    });
  });
}


function navLabel(q, index) {
  var raw = String(q.displayNumber || q.number || index + 1);
  var match = raw.match(/^Grupo\s+(.+?),\s*item\s*(.+)$/i);

  if (match) {
    return {
      main: 'Grupo ' + match[1],
      sub: 'Item ' + match[2]
    };
  }

  return {
    main: raw,
    sub: labelType(q.type)
  };
}

function hasAnswer(q) {
  if (!q) return false;

  if (q.type === 'multi_blank_choice' && q.blanks && q.blanks.length) {
    return q.blanks.some(function(blank) {
      return state.answers[q.questionId + '_' + blank.number];
    });
  }

  return Boolean(state.answers[q.questionId]);
}

function statement(q) {
  var latex = String(q.statementLatex || '');
  var badLatex =
    latex.indexOf('�') >= 0 ||
    latex.indexOf('\\begin{center}') >= 0 ||
    latex.indexOf('\\begin{tabular}') >= 0 ||
    latex.indexOf('\\_\\_') >= 0 ||
    (q.textQuality && q.textQuality.status === 'corrupt');

  var raw = badLatex
    ? (q.statementPlain || q.statement || '')
    : (q.statementLatex || q.statementPlain || q.statement || '');

  return String(raw)
    .replace(/\\begin\{center\}[\s\S]*?\\end\{center\}/g, '')
    .replace(/\\begin\{tabular\}[\s\S]*?\\end\{tabular\}/g, '')
    .replace(/\\begin\{itemize\}/g, '')
    .replace(/\\end\{itemize\}/g, '')
    .replace(/\\item\s*/g, '• ')
    .replace(/\\textsuperscript\{a\}/g, 'ª')
    .replace(/\\textsuperscript\{o\}/g, 'º')
    .replace(/\\degree/g, 'º')
    .trim();
}

function renderImages(q) {
  var html = [];
  var seen = new Set();
  var paths = collectImagePaths(q);

  for (var i = 0; i < paths.length; i++) {
    var clean = cleanPath(paths[i]);
    if (!clean || seen.has(clean)) continue;

    seen.add(clean);

    html.push(
      '<figure class="asset-frame">' +
        '<img class="asset-img" src="' + esc(clean) + '" alt="Documento da pergunta" loading="lazy">' +
      '</figure>'
    );
  }

  return html.length ? '<div class="asset-list">' + html.join('') + '</div>' : '';
}

function collectImagePaths(q) {
  var paths = [];
  var seen = {};
  var hideOptionTables = q.type === 'multi_blank_choice' && q.blanks && q.blanks.length > 0;

  function isOptionTable(id) {
    if (!id) return false;
    return id.toLowerCase().indexOf('tabela') >= 0;
  }

  // 1. SourceRefs first — use document crop
  if (q.sourceRefs && q.sourceRefs.length) {
    for (var r = 0; r < q.sourceRefs.length; r++) {
      var ref = q.sourceRefs[r];
      var source = findSource(ref.sourceId);
      if (!source) continue;

      if (ref.childId && source.assetRefs && source.assetRefs.length) {
        var childPath = getChildAssetPath(source, ref.childId);
        if (childPath) paths.push(childPath);
        continue;
      }

      // Full document — use source crop, not internal assets
      var sp = getSourcePath(source);
      if (sp) paths.push(sp);
    }

    // If has sourceRefs and not multi_blank, don't pull direct assets
    if (paths.some(Boolean) && !hideOptionTables) {
      return paths.filter(Boolean);
    }
  }

  // 2. Direct refs (skip option tables if selects exist)
  var directRefs = []
    .concat(q.assetRefs || [])
    .concat(q.imageRefs || [])
    .concat(q.tableRefs || []);

  for (var i = 0; i < directRefs.length; i++) {
    var rid = directRefs[i];
    if (hideOptionTables && isOptionTable(rid)) continue;
    paths.push(getAssetPath(findAsset(rid)));
  }

  // 3. Media fallback — only when no sourceRefs (avoids stale/duplicated images in História)
  if (!paths.some(Boolean) && !(q.sourceRefs && q.sourceRefs.length) && q.media && q.media.length) {
    for (var m = 0; m < q.media.length; m++) {
      paths.push(q.media[m].relativePath || q.media[m].url);
    }
  }

  return paths.filter(Boolean);
}

function getChildAssetPath(source, childId) {
  if (!source || !childId) return '';

  if (source.childCrops && source.childCrops[childId]) {
    var p1 = getPath(source.childCrops[childId]);
    if (p1) return p1;
  }

  if (source.crops && source.crops.children && source.crops.children[childId]) {
    var p2 = getPath(source.crops.children[childId]);
    if (p2) return p2;
  }

  if (!source.assetRefs || !source.assetRefs.length) return '';

  var last = String(childId).split('_').pop().toLowerCase();

  if (/^[a-z]$/.test(last)) {
    var index = last.charCodeAt(0) - 'a'.charCodeAt(0);
    return getAssetPath(findAsset(source.assetRefs[index]));
  }

  if (/^\d+$/.test(last)) {
    return getAssetPath(findAsset(source.assetRefs[Number(last) - 1]));
  }

  return '';
}

function findAsset(id) {
  return (state.exam.assets || []).find(function(asset) {
    return asset.id === id;
  });
}

function findSource(id) {
  return (state.exam.sources || []).find(function(source) {
    return source.sourceId === id;
  });
}

function getAssetPath(asset) {
  if (!asset) return '';

  return (
    getPath(asset.crops && asset.crops.best) ||
    getPath(asset.crop) ||
    getPath(asset.crops && asset.crops.visual) ||
    getPath(asset.crops && asset.crops.context) ||
    getPath(asset.crops && asset.crops.full) ||
    asset.relativePath ||
    asset.url ||
    ''
  );
}

function getSourcePath(source) {
  if (!source) return '';

  return (
    getPath(source.crops && source.crops.best) ||
    getPath(source.crops && source.crops.document) ||
    getPath(source.crops && source.crops.visual) ||
    getPath(source.crops && source.crops.context) ||
    getPath(source.crops && source.crops.full) ||
    source.relativePath ||
    source.url ||
    ''
  );
}

function getPath(obj) {
  if (!obj) return '';
  return obj.relativePath || obj.url || '';
}

function renderAnswer(q) {
  if (q.type === 'multiple_choice' && q.options && q.options.length) {
    return renderOptions(q);
  }

  if (q.type === 'multi_blank_choice' && q.blanks && q.blanks.length) {
    return renderBlanks(q);
  }

  var value = state.answers[q.questionId] || '';

  return '<textarea placeholder="Escreva a sua resposta..." data-answer-key="' +
    esc(q.questionId) +
    '">' +
    esc(value) +
  '</textarea>';
}

function renderOptions(q) {
  return '<div class="options" data-question-id="' + esc(q.questionId) + '">' +
    q.options.map(function(option) {
      var isSelected = state.answers[q.questionId] === option.letter;
      var text = cleanOptionText(option.latex || option.text || '');

      return '<label class="option ' + (isSelected ? 'selected' : '') + '">' +
        '<input type="radio" name="' + esc(q.questionId) + '" value="' + esc(option.letter) + '" ' +
        (isSelected ? 'checked' : '') +
        ' data-answer-key="' + esc(q.questionId) + '">' +
        '<span class="option-letter">(' + esc(option.letter) + ')</span>' +
        '<span class="option-text">' + formatInlineText(text) + '</span>' +
      '</label>';
    }).join('') +
  '</div>';
}

function renderBlanks(q) {
  var maxRows = Math.max.apply(null, q.blanks.map(function(blank) {
    return blank.options.length;
  }));

  var table =
    '<div class="blank-table-wrap">' +
      '<table class="blank-table">' +
        '<thead><tr>' +
          q.blanks.map(function(blank) {
            return '<th>' + esc(blank.number) + '</th>';
          }).join('') +
        '</tr></thead>' +
        '<tbody>';

  for (var i = 0; i < maxRows; i++) {
    table += '<tr>' +
      q.blanks.map(function(blank) {
        var option = blank.options[i];
        return '<td>' +
          (option ? '<strong>' + esc(option.letter) + ')</strong> ' + formatText(option.text || option.latex || '') : '') +
        '</td>';
      }).join('') +
    '</tr>';
  }

  table += '</tbody></table></div>';

  var controls =
    '<div class="blank-controls">' +
      q.blanks.map(function(blank) {
        var key = q.questionId + '_' + blank.number;
        var current = state.answers[key] || '';

        return '<label><strong>' + esc(blank.number) + '</strong>' +
          '<select data-answer-key="' + esc(key) + '">' +
            '<option value="">—</option>' +
            blank.options.map(function(option) {
              return '<option value="' + esc(option.letter) + '"' +
                (current === option.letter ? ' selected' : '') +
                '>' + esc(option.letter) + ')</option>';
            }).join('') +
          '</select>' +
        '</label>';
      }).join('') +
    '</div>';

  return table + controls;
}

function renderGroupChildren(children) {
  if (!children.length) {
    return '<div class="group-box"><p class="empty">Este grupo não tem subquestões extraídas.</p></div>';
  }

  return '<div class="group-box"><h3>Subquestões</h3>' +
    children
      .sort(function(a, b) {
        return String(a.number).localeCompare(String(b.number), undefined, { numeric: true });
      })
      .map(function(child) {
        var index = state.questions.findIndex(function(q) {
          return q.questionId === child.questionId;
        });

        return '<button type="button" class="child-link" data-go-to="' + index + '">' +
          '<strong>' + esc(child.displayNumber || child.number) + '</strong> · ' +
          esc(labelType(child.type)) +
        '</button>';
      }).join('') +
    '</div>';
}

function labelType(type) {
  var labels = {
    multiple_choice: 'Escolha múltipla',
    multi_blank_choice: 'Associação / espaços',
    open_answer: 'Resposta aberta',
    group: 'Grupo'
  };

  return labels[type] || type || '';
}

function cleanPath(value) {
  if (!value) return '';

  var clean = String(value)
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .replace(/^\/+/, '');

  if (clean.indexOf('assets/') === 0) return clean;
  if (clean.indexOf('data/') === 0) return clean;

  var marker = '/assets/';
  if (clean.indexOf(marker) >= 0) {
    return 'assets/' + clean.split(marker).pop();
  }

  return clean;
}

function formatText(value) {
  var text=String(value==null?'':value).replace(/\\\\textsuperscript\{a\}/g,'ª').replace(/\\\\textsuperscript\{o\}/g,'º').replace(/\\\\degree/g,'º').replace(/\\\\begin\{itemize\}/g,'').replace(/\\\\end\{itemize\}/g,'').replace(/\\\\item\s*/g,'• ');
  var parts=text.split(/(\\\\\([^]*?\\\\\)|\\\\\[[^]*?\\\\\])/g);
  return parts.map(function(p){if(p.startsWith('\\\\(')||p.startsWith('\\\\['))return p;return esc(p).replace(/\n/g,'<br>');}).join('');
}

function cleanOptionText(value) {
  return String(value == null ? '' : value)
    .replace(/\r/g, '')
    .replace(/\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function formatInlineText(value) {
  return esc(value);
}

function esc(value) {
  return String(value == null ? '' : value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function cssEscape(value) {
  if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
  return String(value == null ? '' : value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
`;
