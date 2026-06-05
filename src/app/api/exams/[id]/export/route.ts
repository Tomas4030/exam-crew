import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';
import { buildExamExportName, normalizeExamForExport } from '@/lib/examExport';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const debug = request.nextUrl.searchParams.get('debug') === '1';

  const outputDir = path.join(process.cwd(), 'data', 'output');
  const jsonPath = path.join(outputDir, `${id}.json`);
  if (!fs.existsSync(jsonPath)) {
    return NextResponse.json({ error: 'Exam not found' }, { status: 404 });
  }

  const examData = normalizeExamForExport(JSON.parse(fs.readFileSync(jsonPath, 'utf-8')));

  // Build filename: HistoriaA2025Fase1_ID.zip
  const zipFilename = `${buildExamExportName(examData, id)}.zip`;

  // Collect only used asset paths from the JSON
  const usedFiles = collectUsedAssets(examData);

  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    archive.append(JSON.stringify(examData, null, 2), { name: 'exam.json' });

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

/** Collect only visual asset paths referenced by questions. */
function collectUsedAssets(examData: Record<string, unknown>): string[] {
  const paths = new Set<string>();

  const addVisualPath = (rel?: unknown) => {
    if (typeof rel === 'string' && rel.startsWith('assets/')) {
      paths.add(rel);
    }
  };

  const addVisualCrop = (crop?: Record<string, unknown>) => {
    addVisualPath(crop?.relativePath);
  };

  const assets = (examData.assets as Record<string, unknown>[]) || [];
  const findAsset = (id: string) => assets.find((a) => a.id === id);

  const addAssetVisual = (asset?: Record<string, unknown>) => {
    if (!asset) return;
    addVisualPath(asset.relativePath);
    if (typeof asset.url === 'string') {
      const match = asset.url.match(/\/assets\/(.+)$/);
      if (match) addVisualPath(`assets/${match[1]}`);
    }
    const crops = asset.crops as Record<string, unknown> | undefined;
    if (crops?.visual) addVisualCrop(crops.visual as Record<string, unknown>);
    addVisualCrop(asset.crop as Record<string, unknown>);
  };

  for (const q of (examData.questions as Record<string, unknown>[]) || []) {
    const media = q.media as { url?: string; relativePath?: string }[] | undefined;
    if (media) {
      for (const m of media) {
        addVisualPath(m.relativePath);
        if (m.url) {
          const match = m.url.match(/\/assets\/(.+)$/);
          if (match) addVisualPath(`assets/${match[1]}`);
        }
      }
    }

    const allRefs = [
      ...((q.imageRefs as string[]) || []),
      ...((q.assetRefs as string[]) || []),
      ...((q.tableRefs as string[]) || []),
    ];
    for (const refId of allRefs) {
      const asset = findAsset(refId);
      if (asset) addAssetVisual(asset);
    }

    // Option images
    const options = q.options as { imageUrl?: string }[] | undefined;
    if (options) {
      for (const opt of options) {
        if (opt.imageUrl) {
          const match = opt.imageUrl.match(/\/assets\/(.+)$/);
          if (match) addVisualPath(`assets/${match[1]}`);
        }
      }
    }
  }

  // Source document crops (History, Portuguese)
  for (const src of (examData.sources as Record<string, unknown>[]) || []) {
    const crops = src.crops as Record<string, unknown> | undefined;
    if (crops) {
      for (const key of ['best', 'full', 'document', 'visual']) {
        const crop = crops[key] as Record<string, unknown> | undefined;
        if (crop?.relativePath) addVisualPath(crop.relativePath);
      }
    }
    const childCrops = src.childCrops as Record<string, Record<string, unknown>> | undefined;
    if (childCrops) {
      for (const crop of Object.values(childCrops)) {
        addVisualCrop(crop);
      }
    }
  }

  return [...paths];
}
