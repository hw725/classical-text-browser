/**
 * Base44 InvokeLLM 브릿지 — 이미지 분석용.
 *
 * stdin: {"prompt": "...", "image_path": "/tmp/xxx.png", "image_mime": "image/png"}
 * stdout: {"text": "...", "provider": "base44_bridge"}
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// client.js 내부의 console.log/info가 stdout에 섞이면 JSON 파싱 실패하므로
// 모든 console 출력을 stderr로 리다이렉트한다.
console.log = (...args) => process.stderr.write(args.join(' ') + '\n');
console.info = (...args) => process.stderr.write(args.join(' ') + '\n');

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

  // Windows에서 ESM import()는 file:// URL만 허용하므로 pathToFileURL로 변환
  const clientPath = pathToFileURL(join(backend44Root, 'src', 'client.js')).href;
  const { getBase44Client, ensureAuth } = await import(clientPath);

  // 입력 읽기: BRIDGE_INPUT_FILE 환경변수 우선, 없으면 stdin 폴백
  let input;
  if (process.env.BRIDGE_INPUT_FILE) {
    input = JSON.parse(readFileSync(process.env.BRIDGE_INPUT_FILE, 'utf8'));
  } else {
    const chunks = [];
    for await (const chunk of process.stdin) {
      chunks.push(chunk);
    }
    input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  }
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

main().then(() => {
  process.exit(0);
}).catch(e => {
  process.stderr.write(JSON.stringify({ error: e.message || String(e) }));
  process.exit(1);
});
