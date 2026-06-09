import { NextResponse } from 'next/server';
import { readFile, writeFile, mkdir } from 'fs/promises';
import path from 'path';
import { runCriteria } from '@/lib/criteriaProcess';

function criteriaPath(id: string) {
  return path.join(process.cwd(), 'data', 'output', `${id}.criteria.json`);
}

/** Read the already-built criteria document, if any. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const data = await readFile(criteriaPath(id), 'utf-8');
    return NextResponse.json(JSON.parse(data));
  } catch {
    return NextResponse.json({ error: 'not_built', status: null }, { status: 404 });
  }
}

/**
 * Run the criteria pipeline for this exam, then return the built document.
 *
 * Accepts two modes:
 *   multipart/form-data  with field "pdf" → user-uploaded PDF, saved locally
 *   application/json     with optional field "url" → remote URL override
 *   (no body)            → pipeline resolves the URL automatically
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let url: string | undefined;
  let pdfPath: string | undefined;

  const contentType = request.headers.get('content-type') || '';

  if (contentType.includes('multipart/form-data')) {
    try {
      const formData = await request.formData();
      const file = formData.get('pdf') as File | null;
      if (file && file.size > 0) {
        const uploadsDir = path.join(process.cwd(), 'data', 'uploads', 'criteria');
        await mkdir(uploadsDir, { recursive: true });
        pdfPath = path.join(uploadsDir, `${id}_criterios.pdf`);
        const bytes = await file.arrayBuffer();
        await writeFile(pdfPath, Buffer.from(bytes));
      }
    } catch {
      // fall through — pipeline will auto-resolve
    }
  } else {
    try {
      const body = await request.json();
      if (body && typeof body.url === 'string' && body.url.trim()) url = body.url.trim();
    } catch {
      // no body / not JSON — fine, pipeline resolves automatically
    }
  }

  const result = await runCriteria(
    id,
    pdfPath ? { pdfPath } : url ? { url } : undefined,
  );

  if (!result.success) {
    return NextResponse.json({ error: result.error || 'criteria_failed' }, { status: 500 });
  }

  try {
    const data = await readFile(criteriaPath(id), 'utf-8');
    return NextResponse.json(JSON.parse(data));
  } catch {
    return NextResponse.json({ error: 'built_but_unreadable' }, { status: 500 });
  }
}
