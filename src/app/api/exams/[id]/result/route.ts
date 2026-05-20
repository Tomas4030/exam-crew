import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const outputPath = path.join(process.cwd(), 'data', 'output', `${id}.json`);
  try {
    const data = await readFile(outputPath, 'utf-8');
    return NextResponse.json(JSON.parse(data));
  } catch {
    return NextResponse.json({ error: 'Result not found' }, { status: 404 });
  }
}
