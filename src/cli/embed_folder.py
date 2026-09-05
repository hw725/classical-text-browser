"""논문 폴더를 훑어 스캔본만 골라 텍스트 레이어를 입히는 배치.

왜 CLI인가:
    브라우저 UI는 논문 한 편씩 다루기에 알맞다. 그러나 수백 편이 모인
    폴더를 한 번에 처리하려면 «드롭 → 프로필 전환 → OCR → 내려받기 →
    파일 옮기기»를 편수만큼 반복해야 한다. 그건 사람이 할 일이 아니다.

무엇을 하는가 (파일 하나당):
    1. 텍스트 레이어를 진단한다. 이미 있으면 **건드리지 않고 건너뛴다.**
    2. 작업 서고에 문헌으로 등록한다 (이력이 남는다).
    3. 페이지 전면 블록을 만들고 쪽마다 OCR을 돌린다.
    4. 텍스트 레이어를 입힌 PDF를 만든다.
    5. 원본을 아카이브로 **옮기고**, 텍스트 레이어를 입힌 것을 원래 자리에 **원래 이름으로** 놓는다.

왜 원래 이름을 지키는가:
    이 폴더는 `저자_연도_제목.pdf` 규약으로 정리돼 있고 서지 관리 도구가
    그 이름에서 정보를 읽는다. 이름이 바뀌면 그 도구의 흐름이 끊긴다.

사본을 늘리지 않는다:
    OCR을 하려면 파이프라인이 서고 구조(L1_source/L2/L3)를 요구하므로
    작업 서고에 복사본이 생긴다. 처리가 끝나면 최종 상태는 세 벌이다.

        논문/<주제>/저자_연도_제목.pdf        ← 텍스트 레이어를 입힌 것 (서지 도구가 가져감)
        논문/_scan_originals/<주제>/…        ← 원본 스캔본
        <작업서고>/documents/embed_NNNN/      ← OCR 결과 (L2/L3) — 검수용

    세 번째를 **남기는 것이 기본이다**. 결과가 이상해 보이면 GUI를 켜서
    이 서고를 열고 쪽별 검수를 하면 된다(D-057). 지워 버리면 볼 것이 없어
    OCR을 처음부터 다시 돌려야 하고 **비용을 두 번 낸다.**
    디스크를 아껴야 하면 --drop-workspace 로 지울 수 있다.

안전 장치:
    - **기본은 dry-run이다.** 무엇을 할지 보여 주기만 하고 아무것도 바꾸지 않는다.
    - 원본은 지우지 않고 아카이브 폴더로 **옮긴다**. 되돌릴 수 있다.
    - 처리 기록을 JSONL로 남겨, 중단해도 다음 실행이 이어서 한다.
    - 한 편이 실패해도 나머지는 계속한다.
    - 쪽 사이·편 사이에 쉬어 갈 수 있다(--sleep). LLM 사용량 한도를 위한 것이다.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# 이 폴더들은 작업 대상이 아니다 (파이프라인 작업 공간).
DEFAULT_SKIP_DIRS = {
    "_ingested",
    "_global_inbox",
    "scripts",
    "logs",
    "interim_reports",
    "_scan_originals",  # 우리가 만드는 아카이브 — 다시 처리하면 안 된다
}

ARCHIVE_DIRNAME = "_scan_originals"
LOG_FILENAME = "embed_folder_log.jsonl"


@dataclass
class PaperTask:
    """처리 대상 논문 하나."""

    path: Path
    topic: str  # 주제 폴더 이름 (아카이브 구조를 미러링하는 데 쓴다)
    verdict: str
    pages: int


@dataclass
class BatchReport:
    """배치 실행 결과 요약."""

    scanned_files: int = 0
    already_text: int = 0
    targets: int = 0
    processed: int = 0
    skipped_done: int = 0
    failed: int = 0
    total_pages: int = 0
    elapsed_sec: float = 0.0
    failures: list[dict] = field(default_factory=list)


def survey_folder(root: Path, skip_dirs: set[str] | None = None) -> tuple[list[PaperTask], int]:
    """폴더를 훑어 OCR이 필요한 PDF만 골라낸다.

    입력: root — 논문 폴더. skip_dirs — 건너뛸 하위 폴더 이름들.
    출력: (대상 목록, 이미 텍스트가 있어 건너뛴 개수)

    왜 진단을 먼저 하는가: 대부분의 논문 PDF는 이미 텍스트 레이어를 갖고
    있다. 그걸 다시 OCR하면 시간과 LLM 호출을 버리고 품질도 나빠진다.
    """
    from text_import.pdf_extractor import PdfTextExtractor

    skip = DEFAULT_SKIP_DIRS if skip_dirs is None else skip_dirs
    tasks: list[PaperTask] = []
    already = 0

    for topic_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if topic_dir.name in skip:
            continue
        for pdf in sorted(topic_dir.rglob("*.pdf")):
            try:
                probe = PdfTextExtractor(pdf).probe_text_layer()
            except Exception:  # noqa: BLE001 — 열리지 않는 파일은 대상에서 뺀다
                continue
            if probe["verdict"] == "born_digital":
                already += 1
                continue
            tasks.append(
                PaperTask(
                    path=pdf,
                    topic=topic_dir.name,
                    verdict=probe["verdict"],
                    pages=probe["total_pages"],
                )
            )
    return tasks, already


def _force_rmtree(path: Path) -> tuple[bool, str]:
    """디렉터리를 지운다. Git 저장소도 확실히 지워지게 한다.

    입력: path — 지울 디렉터리.
    출력: (성공 여부, 실패 사유)

    왜 그냥 rmtree가 아닌가:
        Windows에서 `.git/objects/` 아래 파일들은 **읽기 전용 속성**이 붙는다.
        `shutil.rmtree`는 그런 파일에서 PermissionError를 내고 멈춘다.
        `ignore_errors=True`로 넘기면 오류는 사라지지만 **파일도 그대로 남는다** —
        실제로 그 일이 있었다. 정리했다고 보고하면서 사본이 계속 쌓였다.

        그래서 실패한 파일의 읽기 전용 속성을 벗기고 다시 시도한다.
        그러고도 남으면 사실대로 실패를 돌려준다.
    """
    import gc
    import os
    import stat

    # GitPython의 Repo는 `.git/objects/pack/*` 에 파일 핸들을 열어 두고,
    # 이 저장소는 대부분 `git.Repo(path)`를 with 없이 쓴다(core/document.py).
    # Windows는 열린 파일을 지우지 못하므로 «정리했다»가 조용히 실패한다.
    # 참조가 끊긴 Repo를 지금 회수해 __del__이 핸들을 닫게 한다.
    #
    # 왜 여기서 하는가: 호출부마다 Repo를 들고 있지 않아 close()를 부를 수
    # 없다. 지우기 직전이 남은 핸들을 정리할 수 있는 유일한 지점이다.
    gc.collect()

    def _on_error(func, target, exc_info):
        # 읽기 전용이라 지우지 못한 것이면 속성을 벗기고 다시 시도한다.
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except Exception:  # noqa: BLE001 — 여기서 실패하면 아래에서 확인된다
            pass

    try:
        shutil.rmtree(path, onexc=_on_error)
    except TypeError:
        # Python 3.11 이전은 onexc 대신 onerror를 받는다.
        shutil.rmtree(path, onerror=lambda f, t, e: _on_error(f, t, e))
    except Exception as e:  # noqa: BLE001
        return False, str(e)

    if path.exists():
        remaining = sum(1 for _ in path.rglob("*") if _.is_file())
        return False, f"{remaining}개 파일이 남았습니다"
    return True, ""


def _load_done(log_path: Path) -> set[str]:
    """이미 끝낸 파일 목록을 기록에서 읽는다 (중단 후 재개용)."""
    done: set[str] = set()
    if not log_path.exists():
        return done
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "ok" and rec.get("source"):
            done.add(rec["source"])
    return done


def _append_log(log_path: Path, record: dict) -> None:
    """처리 기록을 한 줄 덧붙인다."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_pipeline(library_path: Path):
    """OCR 파이프라인을 만든다. LLM Vision 엔진에는 라우터를 주입한다.

    입력: library_path — 서고 경로 (파이프라인이 L1~L3을 찾는 기준).
    출력: (OcrPipeline, OcrEngineRegistry)

    왜 라우터를 따로 주입하는가:
        `auto_register()`는 LlmOcrEngine을 등록하지만 LLM 라우터는 넣지 않는다.
        라우터가 없으면 `is_available()`이 False라 «엔진을 사용할 수 없다»는
        오류가 난다. 서버는 `_state._get_ocr_pipeline()`에서 이 주입을 하는데,
        CLI는 그 경로를 타지 않으므로 여기서 같은 일을 해 줘야 한다.
        (이 주입이 없어 CLI로 llm_vision을 쓰면 모든 편이 실패했다.)
    """
    from llm.router import LlmRouter
    from ocr.pipeline import OcrPipeline
    from ocr.registry import OcrEngineRegistry

    registry = OcrEngineRegistry()
    registry.auto_register()

    llm_engine = registry._engines.get("llm_vision")
    if llm_engine is not None:
        llm_engine.set_router(LlmRouter())

    return OcrPipeline(registry, library_root=str(library_path)), registry


def describe_llm_target(force_provider: str | None = None, force_model: str | None = None) -> str:
    """어느 LLM이 이 실행을 맡을지 한 줄로.

    입력: force_provider·force_model — `--model provider:model`로 지정한 것. 없으면 폴백 순서
          (Ollama → ChatGPT 계정 → Gemini → OpenAI → Anthropic)에서 처음 되는 비전 프로바이더.
    출력: 사람이 읽을 한 줄. 지정한 프로바이더가 없거나 지금 안 되면 ValueError.

    왜: 폴백은 조용하다. «무료 로컬로 돈다»고 믿었는데 유료 API가 처리하고 있던 사고가
    있었다(D-056). 실행 전에 이름을 찍어 두면 그 사고가 없다.
    """
    import asyncio

    from llm.router import LlmRouter

    router = LlmRouter()

    def _default_model(p) -> str:
        # Ollama는 «기본 모델»이 설치된 것 가운데서 정해진다 — 그 이름을 실제로 고른다.
        if p.provider_id == "ollama" and hasattr(p, "_pick_vision_model"):
            try:
                return asyncio.run(p._pick_vision_model())
            except Exception:  # noqa: BLE001 — 이름을 못 골라도 실행은 막지 않는다
                pass
        return getattr(p, "DEFAULT_MODEL", "기본 모델")

    if force_provider:
        p = router._get_provider(force_provider)
        if p is None:
            names = ", ".join(x.provider_id for x in router.providers)
            raise ValueError(f"프로바이더 '{force_provider}'가 없습니다. 있는 것: {names}")
        if not p.supports_image:
            raise ValueError(f"'{force_provider}'는 이미지를 읽지 못합니다.")
        if not asyncio.run(p.is_available()):
            raise ValueError(
                f"'{force_provider}'를 지금 쓸 수 없습니다 — 키·프록시·Ollama를 확인하세요."
            )
        return f"{p.display_name} — {force_model or _default_model(p)} (지정)"
    for p in router.providers:
        if p.supports_image and asyncio.run(p.is_available()):
            return (
                f"{p.display_name} — {_default_model(p)} "
                "(폴백 순서에서 처음 되는 것. 도중에 실패하면 다음으로 넘어갑니다 — "
                "고정하려면 --model)"
            )
    return "쓸 수 있는 LLM이 없습니다 — 키·프록시·Ollama를 확인하세요"


def _safe_doc_id(index: int) -> str:
    """작업 서고에서 쓸 문헌 ID를 만든다.

    파일명이 한글·한자라 그대로 쓸 수 없으므로(ID 규칙은 ASCII 소문자다)
    일련번호를 쓴다. 원본 이름은 문헌 제목과 part label에 남는다.
    """
    return f"embed_{index:04d}"


def _process_one(
    task: PaperTask,
    library_path: Path,
    doc_id: str,
    engine_id: str | None,
    archive_root: Path,
    replace_original: bool,
    pipeline,
    keep_workspace: bool = True,
    page_sleep: float = 0.0,
    use_line_detection: bool = True,
    force_provider: str | None = None,
    force_model: str | None = None,
) -> dict:
    """논문 한 편을 등록 → OCR → 입히기 → 자리바꿈까지 처리한다.

    출력: 로그에 남길 기록 dict.
    예외를 던지지 않는다 — 실패도 기록으로 돌려주고 호출부가 계속 진행한다.
    """
    from core.document import add_document
    from export.text_layer_pdf import embed_text_layer
    from ocr.full_page_block import ensure_full_page_block
    from ocr.layout_staleness import has_ocr_result

    started = time.time()
    record = {
        "source": str(task.path),
        "topic": task.topic,
        "doc_id": doc_id,
        "pages": task.pages,
        "verdict": task.verdict,
    }

    try:
        # 1) 작업 서고에 등록 — 원본은 복사되고 이 시점부터 이력이 남는다.
        #
        # 이미 있으면 다시 만들지 않는다. 앞선 실행이 이 편의 중간에서
        # 멈춘 경우다(성공한 편은 서고에서 지워지므로 남아 있지 않다).
        # 다시 만들면 그때까지 돌린 OCR이 통째로 버려진다 — 60쪽짜리
        # 논문이면 LLM 호출 수십 회가 그대로 낭비된다.
        doc_path = library_path / "documents" / doc_id
        resumed = (doc_path / "manifest.json").exists()
        if not resumed:
            add_document(
                library_path=library_path,
                doc_id=doc_id,
                title=task.path.stem,
                files=[task.path],
            )

        # 2) 쪽마다 전면 블록 + OCR
        import fitz

        with fitz.open(str(task.path)) as src:
            page_count = src.page_count

        ok_pages = 0
        resumed_pages = 0
        for page_num in range(1, page_count + 1):
            # 이미 결과가 있는 쪽은 건너뛴다. L2 자체가 체크포인트다.
            if resumed and has_ocr_result(doc_path, "vol1", page_num):
                ok_pages += 1
                resumed_pages += 1
                continue

            ensure_full_page_block(doc_path, "vol1", page_num)
            # --model로 고른 프로바이더·모델은 llm_vision 엔진만 본다(다른 엔진은 무시한다).
            result = pipeline.run_page(
                doc_id=doc_id,
                part_id="vol1",
                page_number=page_num,
                engine_id=engine_id,
                **({"force_provider": force_provider} if force_provider else {}),
                **({"force_model": force_model} if force_model else {}),
            )
            if result.ocr_results:
                ok_pages += 1
            # LLM 사용량 한도를 위해 쪽 사이에 쉬어 간다.
            if page_sleep and page_num < page_count:
                time.sleep(page_sleep)

        if resumed_pages:
            record["resumed_pages"] = resumed_pages

        # 3) 텍스트 레이어를 입힌다
        embedded = embed_text_layer(doc_path, "vol1", use_line_detection=use_line_detection)
        record.update(
            {
                "ocr_pages": ok_pages,
                "embedded_pages": embedded.embedded_pages,
                "positioned_lines": embedded.positioned_lines,
                "approximated_lines": embedded.approximated_lines,
                "detected_lines": embedded.detected_lines,
                "embedded_path": embedded.output_path,
            }
        )

        if embedded.embedded_pages == 0:
            record.update({"status": "failed", "error": "텍스트를 얹은 쪽이 없습니다 (OCR 실패)"})
            return record

        # 4) 원본을 아카이브로 옮기고, 텍스트 레이어를 입힌 것을 원래 자리·원래 이름으로 놓는다.
        if replace_original:
            archive_dir = archive_root / task.topic
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived = archive_dir / task.path.name
            if archived.exists():
                # 같은 이름이 이미 있으면 덮어쓰지 않는다.
                stem, suffix = archived.stem, archived.suffix
                n = 2
                while (archive_dir / f"{stem}_{n}{suffix}").exists():
                    n += 1
                archived = archive_dir / f"{stem}_{n}{suffix}"

            shutil.move(str(task.path), str(archived))
            shutil.copy2(embedded.output_path, str(task.path))
            record["archived_to"] = str(archived)
            record["replaced"] = True
        else:
            record["replaced"] = False

        record["status"] = "ok"

        # 5) 작업 서고의 복사본을 지운다.
        #
        # 왜 기본으로 지우지 않는가: 여기에 OCR 결과(L2/L3)가 들어 있다.
        # 지우면 나중에 GUI로 쪽별 검수를 할 수 없고, 결과가 이상해 보여도
        # OCR을 처음부터 다시 돌려야 한다 — 쪽마다 LLM 호출이 다시 나간다.
        # «CLI로 빠르게 돌리고, 이상하면 GUI로 검수한다»는 흐름이 성립하려면
        # 결과가 남아 있어야 한다. --drop-workspace 를 준 경우에만 지운다.
        if not keep_workspace and record.get("replaced"):
            ok, why = _force_rmtree(doc_path)
            # 문헌을 만들 때 기본 해석 저장소가 함께 생긴다(D-054).
            # 추출 작업은 L5-L7을 쓰지 않으므로 그것은 빈 채로 남는다.
            # 문헌만 지우고 두면 서고에 빈 해석 저장소가 편수만큼 쌓인다.
            interp_dir = library_path / "interpretations"
            if interp_dir.exists():
                for interp in interp_dir.iterdir():
                    if interp.is_dir() and interp.name.startswith(doc_id):
                        interp_ok, interp_why = _force_rmtree(interp)
                        if not interp_ok:
                            ok, why = False, f"해석 저장소: {interp_why}"
            record["workspace_cleaned"] = ok
            if not ok:
                # 실패를 조용히 넘기지 않는다. 편수만큼 사본이 쌓이기 때문이다.
                record["cleanup_warning"] = why
    except Exception as e:  # noqa: BLE001 — 한 편의 실패가 배치를 멈추면 안 된다
        record["status"] = "failed"
        record["error"] = f"{type(e).__name__}: {e}"

    record["elapsed_sec"] = round(time.time() - started, 1)
    return record


def embed_folder(
    root: Path,
    library_path: Path,
    *,
    engine_id: str | None = None,
    dry_run: bool = True,
    limit: int | None = None,
    max_pages: int | None = None,
    only: str | None = None,
    replace_original: bool = True,
    archive_root: Path | None = None,
    log_path: Path | None = None,
    keep_workspace: bool = True,
    page_sleep: float = 0.0,
    paper_sleep: float = 0.0,
    use_line_detection: bool = True,
    force_provider: str | None = None,
    force_model: str | None = None,
    progress=print,
) -> BatchReport:
    """논문 폴더 전체를 처리한다.

    입력:
        root — 논문 폴더. library_path — 작업 서고(없으면 만든다).
        engine_id — OCR 엔진. None이면 기본 엔진(주의: 한글을 못 읽을 수 있다).
        force_provider·force_model — llm_vision이 쓸 LLM을 고정(`--model provider:model`).
            없으면 폴백 순서. 어느 쪽이든 실행 전에 «도는 모델»을 한 줄 찍는다.
        dry_run — True면 계획만 보여 준다.
        limit — 처리할 최대 편수 (시범 실행용).
        max_pages — 이 쪽수를 넘는 문헌은 건너뛴다 (큰 것을 나중으로 미룰 때).
        replace_original — 원본을 아카이브로 옮기고 텍스트 레이어를 입힌 것으로 바꿀지.
    출력: BatchReport.
    """
    from core.library import init_library

    root = Path(root).resolve()
    archive_root = Path(archive_root) if archive_root else root / ARCHIVE_DIRNAME
    log_path = Path(log_path) if log_path else library_path / LOG_FILENAME

    report = BatchReport()
    started = time.time()

    progress(f"폴더를 훑는 중: {root}")
    tasks, already = survey_folder(root)
    report.scanned_files = len(tasks) + already
    report.already_text = already

    if only:
        # 파일명에 이 문자열이 든 것만 남긴다 (특정 논문을 시범 실행할 때).
        before = len(tasks)
        tasks = [t for t in tasks if only in t.path.name]
        progress(f"  '{only}' 필터: {before}편 중 {len(tasks)}편 선택")

    if max_pages:
        before = len(tasks)
        tasks = [t for t in tasks if t.pages <= max_pages]
        if before != len(tasks):
            progress(f"  {before - len(tasks)}편은 {max_pages}쪽을 넘어 제외했습니다.")

    done = _load_done(log_path)
    remaining = [t for t in tasks if str(t.path) not in done]
    report.skipped_done = len(tasks) - len(remaining)

    if limit:
        remaining = remaining[:limit]

    report.targets = len(remaining)
    report.total_pages = sum(t.pages for t in remaining)

    progress(
        f"\n전체 {report.scanned_files}개 중 "
        f"텍스트 있음 {already}개(건너뜀), 처리 대상 {len(tasks)}개"
    )
    if report.skipped_done:
        progress(f"  이미 처리 완료 {report.skipped_done}편 (기록으로 확인)")
    progress(f"  이번에 처리할 것: {report.targets}편 / {report.total_pages}쪽")
    if engine_id == "llm_vision" or engine_id is None:
        progress(f"  → LLM 호출 예상 {report.total_pages}회")
        # 어느 모델이 맡는지 실행 전에 찍는다 — 폴백은 조용해서 유료 API가 처리하는 줄
        # 모르고 돌린 사고가 있었다(D-056). 미리보기에서도 찍어 --execute 전에 보게 한다.
        try:
            progress(f"  → 도는 모델: {describe_llm_target(force_provider, force_model)}")
        except ValueError as e:
            progress(f"\n{e}")
            report.elapsed_sec = time.time() - started
            return report

    if dry_run:
        progress("\n[미리보기] 실제로는 아무것도 바꾸지 않았습니다.")
        for t in remaining[:20]:
            progress(f"   {t.pages:4d}쪽  [{t.verdict}]  {t.topic}/{t.path.name}")
        if len(remaining) > 20:
            progress(f"   … 외 {len(remaining) - 20}편")
        progress("\n실제로 실행하려면 --execute 를 붙이세요.")
        report.elapsed_sec = time.time() - started
        return report

    if not library_path.exists() or not (library_path / "library_manifest.json").exists():
        init_library(library_path)
        progress(f"작업 서고를 만들었습니다: {library_path}")

    # 파이프라인은 한 번만 만든다. 편마다 새로 만들면 엔진 초기화가 반복된다.
    pipeline, registry = build_pipeline(library_path)
    engine = registry._engines.get(engine_id) if engine_id else None
    if engine is not None and not engine.is_available():
        progress(
            f"\n엔진 '{engine_id}'을(를) 쓸 수 없습니다.\n"
            "→ llm_vision이면 LLM 프로바이더 설정(.env·Ollama·OAuth 프록시)을 확인하세요."
        )
        report.elapsed_sec = time.time() - started
        return report

    for idx, task in enumerate(remaining, 1):
        progress(f"\n[{idx}/{len(remaining)}] {task.path.name} ({task.pages}쪽)")
        doc_id = _safe_doc_id(int(time.time() * 10) % 100000 + idx)
        record = _process_one(
            task,
            library_path,
            doc_id,
            engine_id,
            archive_root,
            replace_original,
            pipeline,
            keep_workspace=keep_workspace,
            page_sleep=page_sleep,
            use_line_detection=use_line_detection,
            force_provider=force_provider,
            force_model=force_model,
        )
        _append_log(log_path, record)

        if record.get("status") == "ok":
            report.processed += 1
            per_page = record["elapsed_sec"] / max(record.get("pages") or 1, 1)
            progress(
                f"    완료 — {record.get('embedded_pages')}쪽 구움"
                + (", 원본 아카이브됨" if record.get("replaced") else "")
                + f" ({record.get('elapsed_sec')}초, 쪽당 {per_page:.1f}초)"
            )
        else:
            report.failed += 1
            report.failures.append(record)
            progress(f"    실패 — {record.get('error', '')[:120]}")

        # 편 사이에 쉬어 간다 (LLM 사용량 한도).
        if paper_sleep and idx < len(remaining):
            progress(f"    {paper_sleep:.0f}초 쉽니다…")
            time.sleep(paper_sleep)

    report.elapsed_sec = time.time() - started
    return report
