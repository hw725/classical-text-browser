/**
 * Base44 InvokeLLM 브릿지 — 이미지 분석용.
 *
 * stdin: {"prompt": "...", "image_path": "/tmp/xxx.png", "image_mime": "image/png"}
 * stdout: {"text": "...", "provider": "base44_bridge"}
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function findBackend44Root() {
  if (process.env.BACKEND44_PATH) {
    const p = resolve(process.env.BACKEND44_PATH);
    if (existsSync(join(p, 'src', 'client.js'))) return p;
  }
  const candidates = [
    resolve(__dirname, '..', '..', '..', '..', 'backend-44'),
    resolve(__dirname, '..', '..', '..', '..', 'head-repo', 'hw725', 'backend-44'),
  ];
  for (const c of candidates) {
    if (existsSync(join(c, 'src', 'client.js'))) return c;
  }
  return null;
}

async function main() {
  const backend44Root = findBackend44Root();
  if (!backend44Root) {
    throw new Error('backend-44를 찾을 수 없습니다.');
  }

  const clientPath = join(backend44Root, 'src', 'client.js');
  const { getBase44Client, ensureAuth } = await import(clientPath);

  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const { prompt, image_path, image_mime } = input;

  if (!existsSync(image_path)) {
    throw new Error(`이미지 파일 없음: ${image_path}`);
  }

  ensureAuth();
  const base44 = getBase44Client();

  // 이미지 업로드
  const imageBuffer = readFileSync(image_path);
  const fileName = image_path.split(/[\\/]/).pop();

  let fileObj;
  if (typeof globalThis.File === 'function') {
    fileObj = new globalThis.File([imageBuffer], fileName, {
      type: image_mime || 'image/png',
    });
  } else {
    fileObj = new globalThis.Blob([imageBuffer], {
      type: image_mime || 'image/png',
    });
    fileObj.name = fileName;
  }

  const uploadResult = await base44.integrations.Core.UploadFile({ file: fileObj });
  if (!uploadResult?.file_url) {
    throw new Error('파일 업로드 실패: file_url 없음');
  }

  const result = await base44.integrations.Core.InvokeLLM({
    prompt,
    file_urls: [uploadResult.file_url],
  });

  const text = typeof result === 'string'
    ? result
    : (result?.content || JSON.stringify(result));

  process.stdout.write(JSON.stringify({
    text,
    provider: 'base44_bridge',
    file_url: uploadResult.file_url,
    raw: result,
  }));
}

main().catch(e => {
  process.stderr.write(JSON.stringify({ error: e.message || String(e) }));
  process.exit(1);
});
