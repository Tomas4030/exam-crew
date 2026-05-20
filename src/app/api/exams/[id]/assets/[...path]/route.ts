import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; path: string[] }> }
) {
  const { id, path: segments } = await params;

  // Supports: /assets/file.png, /assets/context/file.png, /assets/visual/file.png
  const safeParts = segments.map((s) => path.basename(s));
  const filePath = path.join(process.cwd(), 'data', 'output', id, 'assets', ...safeParts);

  if (!fs.existsSync(filePath)) {
    // Fallback: try legacy flat path (just filename)
    const legacyPath = path.join(process.cwd(), 'data', 'output', id, 'assets', safeParts[safeParts.length - 1]);
    if (!fs.existsSync(legacyPath)) {
      return NextResponse.json({ error: 'Asset not found' }, { status: 404 });
    }
    const buffer = fs.readFileSync(legacyPath);
    return new NextResponse(buffer, {
      headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=86400' },
    });
  }

  const buffer = fs.readFileSync(filePath);
  return new NextResponse(buffer, {
    headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=86400' },
  });
}
