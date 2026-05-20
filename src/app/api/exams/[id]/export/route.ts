import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import { createReadStream } from 'fs';
import archiver from 'archiver';
import { Readable } from 'stream';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const outputDir = path.join(process.cwd(), 'data', 'output');
  const jsonPath = path.join(outputDir, `${id}.json`);
  const assetsDir = path.join(outputDir, id, 'assets');

  if (!fs.existsSync(jsonPath)) {
    return NextResponse.json({ error: 'Exam not found' }, { status: 404 });
  }

  // Create ZIP in memory using archiver
  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    // Add exam.json
    archive.file(jsonPath, { name: 'exam.json' });

    // Add all asset PNGs
    if (fs.existsSync(assetsDir)) {
      archive.directory(assetsDir, 'assets');
    }

    archive.finalize();
  });

  const buffer = Buffer.concat(chunks);

  return new NextResponse(buffer, {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${id}.zip"`,
    },
  });
}
