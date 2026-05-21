import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const debug = request.nextUrl.searchParams.get('debug') === '1';

  const outputDir = path.join(process.cwd(), 'data', 'output');
  const jsonPath = path.join(outputDir, `${id}.json`);
  const assetsDir = path.join(outputDir, id, 'assets');

  if (!fs.existsSync(jsonPath)) {
    return NextResponse.json({ error: 'Exam not found' }, { status: 404 });
  }

  const examData = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));

  // Build filename
  const title = examData.metadata?.title || '';
  const shortId = id.split('_').pop() || id.slice(-8);
  const slug = title
    ? title.toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_|_$/g, '')
    : id;
  const zipFilename = `${slug}-${shortId}.zip`;

  // Collect only used asset paths from the JSON
  const usedFiles = collectUsedAssets(examData);

  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    archive.file(jsonPath, { name: 'exam.json' });

    // Add only used assets
    for (const relPath of usedFiles) {
      const absPath = path.join(outputDir, id, relPath);
      if (fs.existsSync(absPath)) {
        archive.file(absPath, { name: relPath });
      }
    }

    // Diagnostics only in debug mode
    if (debug) {
      const extractionReport = {
        exam_id: id,
        processingStatus: examData.processingStatus,
        totalQuestions: (examData.questions || []).length,
        totalAssets: (examData.assets || []).length,
        totalWarnings: (examData.warnings || []).length,
        warnings: examData.warnings,
      };
      archive.append(JSON.stringify(extractionReport, null, 2), { name: 'diagnostics/extraction_report.json' });
    }

    archive.finalize();
  });

  const buffer = Buffer.concat(chunks);

  return new NextResponse(buffer, {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${zipFilename}"`,
    },
  });
}

/** Collect all asset relative paths actually referenced in the exam JSON. */
function collectUsedAssets(examData: Record<string, unknown>): string[] {
  const paths = new Set<string>();

  const addCrop = (crop?: Record<string, unknown>) => {
    if (crop?.relativePath && typeof crop.relativePath === 'string') {
      paths.add(crop.relativePath);
    }
  };

  const addAssetCrops = (asset?: Record<string, unknown>) => {
    if (!asset) return;
    addCrop(asset.crop as Record<string, unknown>);
    const crops = asset.crops as Record<string, unknown> | undefined;
    if (crops) {
      addCrop(crops.context as Record<string, unknown>);
      addCrop(crops.visual as Record<string, unknown>);
    }
  };

  // From question.media (primary — the resolved final URLs)
  for (const q of (examData.questions as Record<string, unknown>[]) || []) {
    const media = q.media as { url?: string; relativePath?: string }[] | undefined;
    if (media) {
      for (const m of media) {
        // media URLs are like /api/exams/{id}/assets/page4_img0.png
        // Extract the relative path: assets/filename
        if (m.url) {
          const match = m.url.match(/\/assets\/(.+)$/);
          if (match) paths.add(`assets/${match[1]}`);
        }
      }
    }

    // Also from direct assetRefs
    const allRefs = [
      ...((q.imageRefs as string[]) || []),
      ...((q.assetRefs as string[]) || []),
    ];
    for (const refId of allRefs) {
      const asset = ((examData.assets as Record<string, unknown>[]) || []).find(
        (a) => a.id === refId
      );
      if (asset) addAssetCrops(asset);
    }
  }

  // From sources
  for (const src of (examData.sources as Record<string, unknown>[]) || []) {
    const crops = src.crops as Record<string, unknown> | undefined;
    if (crops?.full) addCrop(crops.full as Record<string, unknown>);

    // Source assetRefs
    for (const aId of (src.assetRefs as string[]) || []) {
      const asset = ((examData.assets as Record<string, unknown>[]) || []).find(
        (a) => a.id === aId
      );
      if (asset) addAssetCrops(asset);
    }
  }

  return [...paths];
}
