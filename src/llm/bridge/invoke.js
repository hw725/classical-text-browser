/**
 * Base44 InvokeLLM 브릿지 — 텍스트 전용.
 *
 * Python에서 subprocess로 실행. stdin JSON → stdout JSON.
 * 사용: echo '{"prompt":"..."}' | node invoke.js
 *
 * 전제:
 *   - 환경변수 BACKEND44_PATH에 backend-44 경로 설정
 *   - 또는 이 파일 기준 상대 경로로 backend-44 탐색
 *   - base44 login 완료 (~/.base44/auth/auth.json 존재)
 */

import { existsSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// client.js 내부의 console.log/info가 stdout에 섞이면 JSON 파싱 실패하므로
// 모든 console 출력을 stderr로 리다이렉트한다.
const origLog = console.log;
const origInfo = console.info;
console.log = (...args) => process.stderr.write(args.join(' ') + '\n');
console.info = (...args) => process.stderr.write(args.join(' ') + '\n');

// backend-44 경로 탐색
function findBackend44Root() {
  // 1. 환경변수
  if (process.env.BACKEND44_PATH) {
    const p = resolve(process.env.BACKEND44_PATH);
    if (existsSync(join(p, 'src', 'client.js'))) return p;
  }
  // 2. 프로젝트 루트 기준 상대 경로 탐색 (여러 후보)
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
    throw new Error(
      'backend-44를 찾을 수 없습니다.\n' +
      'BACKEND44_PATH 환경변수를 설정하세요.'
    );
  }

  // 동적 import (경로가 런타임에 결정되므로)
  // Windows에서 ESM import()는 file:// URL만 허용하므로 pathToFileURL로 변환
  const clientPath = pathToFileURL(join(backend44Root, 'src', 'client.js')).href;
  const { getBase44Client, ensureAuth } = await import(clientPath);

  // 입력 읽기: BRIDGE_INPUT_FILE 환경변수 우선, 없으면 stdin 폴백
  let input;
  if (process.env.BRIDGE_INPUT_FILE) {
    const { readFileSync } = await import('fs');
    input = JSON.parse(readFileSync(process.env.BRIDGE_INPUT_FILE, 'utf8'));
  } else {
    const chunks = [];
    for await (const chunk of process.stdin) {
      chunks.push(chunk);
    }
    input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  }
  const { prompt, system, response_type } = input;

  ensureAuth();
  const base44 = getBase44Client();

  const fullPrompt = system
    ? `[시스템 지시]\n${system}\n\n[요청]\n${prompt}`
    : prompt;

  const result = await base44.integrations.Core.InvokeLLM({
    prompt: fullPrompt,
    response_type: response_type || 'text',
  });

  const text = typeof result === 'string'
    ? result
    : (result?.content || JSON.stringify(result));

  process.stdout.write(JSON.stringify({ text, provider: 'base44_bridge', raw: result }));
}

main().then(() => {
  // Base44 SDK가 내부 HTTP 커넥션을 유지하여 프로세스가 종료되지 않으므로
  // 결과 출력 후 명시적으로 종료한다.
  process.exit(0);
}).catch(e => {
  process.stderr.write(JSON.stringify({ error: e.message || String(e) }));
  process.exit(1);
});
