import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';
import { getJobs } from '@/lib/storage';
import { buildExamExportName, normalizeExamForExport } from '@/lib/examExport';

export async function GET() {
  const jobs = await getJobs();
  const completedJobs = jobs.filter(j => j.status === 'completed' || j.status === 'completed_with_warnings');

  if (completedJobs.length === 0) {
    return NextResponse.json({ error: 'No completed exams found' }, { status: 404 });
  }

  const outputDir = path.join(process.cwd(), 'data', 'output');
  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    for (const job of completedJobs) {
      const id = job.id;
      const jsonPath = path.join(outputDir, `${id}.json`);
      if (!fs.existsSync(jsonPath)) continue;

      const examData = normalizeExamForExport(JSON.parse(fs.readFileSync(jsonPath, 'utf-8')));
      const usedFiles = collectUsedAssets(examData);
      const folder = buildExamExportName(examData, id);

      archive.append(JSON.stringify(examData, null, 2), { name: `${folder}/exam.json` });

      for (const relPath of usedFiles) {
        const absPath = path.join(outputDir, id, relPath);
        if (fs.existsSync(absPath)) {
          archive.file(absPath, { name: `${folder}/${relPath}` });
        }
      }
    }

    archive.finalize();
  });

  const buffer = Buffer.concat(chunks);
  const timestamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const zipFilename = `AllExams_${timestamp}.zip`;

  return new NextResponse(buffer, {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${zipFilename}"`,
    },
  });
}

function collectUsedAssets(examData: Record<string, unknown>): string[] {
  const paths = new Set<string>();

  const addVisualPath = (rel?: unknown) => {
    if (typeof rel === 'string' && rel.startsWith('assets/')) paths.add(rel);
  };

  const addVisualCrop = (crop?: Record<string, unknown>) => {
    addVisualPath(crop?.relativePath);
  };

  const assets = (examData.assets as Record<string, unknown>[]) || [];
  const findAsset = (id: string) => assets.find((a) => a.id === id);

  const addAssetVisual = (asset?: Record<string, unknown>) => {
    if (!asset) return;
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
