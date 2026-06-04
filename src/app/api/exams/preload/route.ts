import { NextResponse } from "next/server";
import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { createJob } from "@/lib/storage";
import { ExamJob } from "@/lib/types";
import { enqueuePipeline } from "@/lib/pipelineQueue";

export const runtime = "nodejs";

type PreloadRequest = { urls?: string[]; text?: string };

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as PreloadRequest;
    const urls = normalizeUrls(body);

    if (!urls.length) {
      return NextResponse.json({ error: "Nenhum URL válido recebido." }, { status: 400 });
    }

    const batchId = `batch_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const uploadsDir = path.join(process.cwd(), "data", "uploads");
    await mkdir(uploadsDir, { recursive: true });

    const created: { exam_id: string; url: string; status: string }[] = [];

    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];
      const examId = `exam_${Date.now()}_${i}_${Math.random().toString(36).slice(2, 8)}`;
      const filePath = path.join(uploadsDir, `${examId}.pdf`);

      const pdfBuffer = await fetchPdf(url);
      await writeFile(filePath, pdfBuffer);

      const job: ExamJob = {
        id: examId,
        filename: makeFilenameFromUrl(url, examId),
        status: "queued",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        sourceUrl: url,
        batchId,
        batchIndex: i + 1,
      };
      await createJob(job);
      enqueuePipeline({ examId, pdfPath: filePath, sourceUrl: url });
      created.push({ exam_id: examId, url, status: "queued" });
    }

    return NextResponse.json({ batch_id: batchId, total: created.length, jobs: created });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Erro no preload." },
      { status: 500 }
    );
  }
}

function normalizeUrls(body: PreloadRequest): string[] {
  const raw = [
    ...(body.urls || []),
    ...(body.text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean),
  ];
  const seen = new Set<string>();
  const urls: string[] = [];
  for (const item of raw) {
    try {
      const url = new URL(item);
      if (!["http:", "https:"].includes(url.protocol)) continue;
      const clean = url.toString();
      if (!seen.has(clean)) { seen.add(clean); urls.push(clean); }
    } catch { continue; }
  }
  return urls;
}

async function fetchPdf(url: string): Promise<Buffer> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45_000);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
      headers: { "User-Agent": "ExamCrew/1.0 PDF preload", Accept: "application/pdf,*/*" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status} ao descarregar ${url}`);
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > 80 * 1024 * 1024) throw new Error(`PDF demasiado grande (máx 80MB): ${url}`);
    const ct = response.headers.get("content-type") || "";
    if (!looksLikePdf(buffer, ct, url)) throw new Error(`Não parece ser um PDF: ${url}`);
    return buffer;
  } finally {
    clearTimeout(timeout);
  }
}

function looksLikePdf(buf: Buffer, ct: string, url: string): boolean {
  return buf.subarray(0, 5).toString() === "%PDF-"
    || ct.includes("application/pdf")
    || url.toLowerCase().split("?")[0].endsWith(".pdf");
}

function makeFilenameFromUrl(url: string, examId: string): string {
  try {
    const base = path.basename(new URL(url).pathname) || `${examId}.pdf`;
    return base.toLowerCase().endsWith(".pdf") ? base : `${base}.pdf`;
  } catch { return `${examId}.pdf`; }
}
