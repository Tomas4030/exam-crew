import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';

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

  // Parse exam JSON to generate diagnostics
  const examData = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));

  // Build filename from exam title: e.g. "exame_nacional_matematica_a_2025-lnjmpu.zip"
  const title = examData.metadata?.title || '';
  const shortId = id.split('_').pop() || id.slice(-8);
  const slug = title
    ? title.toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_|_$/g, '')
    : id;
  const zipFilename = `${slug}-${shortId}.zip`;

  const mathWarnings = (examData.questions || [])
    .filter((q: Record<string, unknown>) => {
      const tq = q.textQuality as Record<string, unknown> | undefined;
      return tq && tq.status === 'needs_review';
    })
    .map((q: Record<string, unknown>) => ({
      questionId: q.questionId,
      number: q.number,
      textQuality: q.textQuality,
    }));

  const cropDiagnostics = (examData.assets || [])
    .filter((a: Record<string, unknown>) => a.crops)
    .map((a: Record<string, unknown>) => ({ id: a.id, page: a.page, crops: a.crops }));

  const extractionReport = {
    exam_id: id,
    processingStatus: examData.processingStatus,
    totalQuestions: (examData.questions || []).length,
    totalAssets: (examData.assets || []).length,
    totalWarnings: (examData.warnings || []).length,
    mathNormalized: (examData.questions || []).filter(
      (q: Record<string, unknown>) => {
        const tq = q.textQuality as Record<string, unknown> | undefined;
        return tq && tq.source === 'vision_latex_normalized';
      }
    ).length,
    warnings: examData.warnings,
  };

  // Create ZIP
  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    archive.file(jsonPath, { name: 'exam.json' });

    if (fs.existsSync(assetsDir)) {
      archive.directory(assetsDir, 'assets');
    }

    // Diagnostics
    archive.append(JSON.stringify(extractionReport, null, 2), { name: 'diagnostics/extraction_report.json' });
    archive.append(JSON.stringify(mathWarnings, null, 2), { name: 'diagnostics/math_warnings.json' });
    archive.append(JSON.stringify(cropDiagnostics, null, 2), { name: 'diagnostics/crop_diagnostics.json' });

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
