#!/usr/bin/env python3
"""이체자 사전 생성 — 공개 원자료에서 층(tier)이 붙은 사전 파일을 만든다 (D-080).

무엇을 만드는가 (resources/ 아래):

| 파일 (resources/variant_chars_*.json) | 원자료 | 층 | 배포 |
|---|---|---|---|
| opencc_script | OpenCC ST·TW·HK·JP신자체 (Apache-2.0) | script | 포함 |
| unihan_strict | Unihan kZVariant (Unicode License) | strict | 포함 가능 |
| unihan_loose  | Unihan kSemanticVariant·kSpecializedSemanticVariant | loose | 포함 가능 |
| unihan_script | Unihan kSimplifiedVariant·kTraditionalVariant | script | 포함 가능 |
| cjkvi_twedu_loose | cjkvi-variants twedu (교육부 異體字字典 추출) | loose | **미포함** |
| cjkvi_hydzd_loose | cjkvi-variants hydzd (漢語大字典 추출) | loose | **미포함** |
| cjkvi_jp_old_style_script | cjkvi-variants jp-old-style (JIS 구자체) | script | **미포함** |

cjkvi 계열은 저장소에 LICENSE 파일이 없고 원자료의 이용 조건이 따로 있어, 사용자가
`--cjkvi`로 직접 내려받아 로컬에서만 쓴다(.gitignore가 막는다). 파일마다 `_source`에
URL·파일명·가져온 날짜·라이선스 메모가 남는다 — 어디서 왔는지 모르는 쌍은 나중에
걸러낼 방법이 없다.

사용법:
    uv run python scripts/build_variant_dicts.py --opencc
    uv run python scripts/build_variant_dicts.py --unihan-zip ~/Downloads/Unihan.zip
    uv run python scripts/build_variant_dicts.py --unihan          # unicode.org에서 내려받기
    uv run python scripts/build_variant_dicts.py --cjkvi           # 라이선스 미확인, 로컬 전용
    uv run python scripts/build_variant_dicts.py --opencc --opencc-dir ./opencc  # 이미 받아 둔 파일

정렬 엔진은 strict 층만 동치로 쓰고 loose·script는 힌트로만 보여 준다. 어느 파일도
본문을 고치지 않는다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core.variant_sources import (  # noqa: E402
    UNIHAN_FIELD_TIERS,
    build_dict_payload,
    parse_cjkvi_csv,
    parse_jp_old_style,
    parse_opencc,
    parse_unihan_variants,
)

RESOURCES = ROOT / "resources"

OPENCC_BASE = "https://raw.githubusercontent.com/BYVoid/OpenCC/master/data/dictionary/"
OPENCC_FILES = ["STCharacters.txt", "TWVariants.txt", "HKVariants.txt", "JPShinjitaiCharacters.txt"]
OPENCC_LICENSE = "Apache-2.0 (https://github.com/BYVoid/OpenCC/blob/master/LICENSE)"

UNIHAN_ZIP_URL = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"
UNIHAN_LICENSE = "Unicode License (https://www.unicode.org/license.txt)"

CJKVI_BASE = "https://raw.githubusercontent.com/cjkvi/cjkvi-variants/master/"
CJKVI_LICENSE = (
    "미확인 — 저장소에 LICENSE·README 없음. 한 파일 머리에 'Copyright (c) 2014 CJKVI Database'. "
    "원자료(교육부 異體字字典·漢語大字典)의 이용 조건이 따로 있다. 로컬 전용."
)


def _fetch(url: str) -> bytes:
    """URL을 내려받는다. HTTPS_PROXY 환경변수는 urllib이 자동으로 따른다."""
    print(f"  ↓ {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — 고정 URL
        return resp.read()


def _write_atomic(path: Path, data: dict) -> None:
    """임시 파일에 쓰고 갈아 끼운다. write_text는 먼저 0바이트로 자른다(D-069)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o644)  # mkstemp는 0600으로 만든다 — 저장소 파일은 읽기 권한이 있어야 한다
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _report(path: Path, payload: dict) -> None:
    print(
        f"  → {path.relative_to(ROOT)}  [{payload['_tier']}]  {payload['_source']['pair_count']}쌍"
    )


def build_opencc(local_dir: Path | None) -> None:
    print("OpenCC")
    pairs = []
    for name in OPENCC_FILES:
        text = (
            (local_dir / name).read_text(encoding="utf-8")
            if local_dir
            else _fetch(OPENCC_BASE + name).decode("utf-8")
        )
        pairs.extend(parse_opencc(text))
    payload = build_dict_payload(
        pairs,
        tier="script",
        source_name="OpenCC (BYVoid/OpenCC) data/dictionary",
        source_url=OPENCC_BASE,
        source_files=OPENCC_FILES,
        license_note=OPENCC_LICENSE,
    )
    out = RESOURCES / "variant_chars_opencc_script.json"
    _write_atomic(out, payload)
    _report(out, payload)


def build_unihan(zip_path: Path | None) -> None:
    print("Unihan")
    blob = zip_path.read_bytes() if zip_path else _fetch(UNIHAN_ZIP_URL)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read("Unihan_Variants.txt").decode("utf-8")
    groups = {"strict": [], "loose": [], "script": []}
    for field, tier in UNIHAN_FIELD_TIERS.items():
        groups[tier].append(field)
    for tier, fields in groups.items():
        pairs = parse_unihan_variants(text, fields)
        payload = build_dict_payload(
            pairs,
            tier=tier,
            source_name=f"Unicode Unihan_Variants.txt — {', '.join(fields)}",
            source_url=UNIHAN_ZIP_URL,
            source_files=["Unihan_Variants.txt"],
            license_note=UNIHAN_LICENSE,
        )
        out = RESOURCES / f"variant_chars_unihan_{tier}.json"
        _write_atomic(out, payload)
        _report(out, payload)


def build_cjkvi(local_dir: Path | None) -> None:
    print("cjkvi-variants (라이선스 미확인 — 로컬 전용, .gitignore가 막는다)")
    jobs = [
        ("twedu-variants.txt", "twedu", "loose", parse_cjkvi_csv, "교육부 異體字字典 추출"),
        ("hydzd-variants.txt", "hydzd", "loose", parse_cjkvi_csv, "漢語大字典 추출"),
        ("jp-old-style.txt", "jp_old_style", "script", parse_jp_old_style, "JIS 구자체(IVS 제거)"),
    ]
    for fname, key, tier, parser, note in jobs:
        text = (
            (local_dir / fname).read_text(encoding="utf-8")
            if local_dir
            else _fetch(CJKVI_BASE + fname).decode("utf-8")
        )
        payload = build_dict_payload(
            parser(text),
            tier=tier,
            source_name=f"cjkvi/cjkvi-variants {fname} — {note}",
            source_url=CJKVI_BASE + fname,
            source_files=[fname],
            license_note=CJKVI_LICENSE,
        )
        out = RESOURCES / f"variant_chars_cjkvi_{key}_{tier}.json"
        _write_atomic(out, payload)
        _report(out, payload)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--opencc", action="store_true", help="OpenCC 간체·지역 변형·신자체 표 (script)"
    )
    ap.add_argument("--opencc-dir", type=Path, help="이미 내려받은 OpenCC 사전 디렉터리")
    ap.add_argument("--unihan", action="store_true", help="unicode.org에서 Unihan.zip 내려받기")
    ap.add_argument("--unihan-zip", type=Path, help="로컬 Unihan.zip 경로 (내려받기 대신)")
    ap.add_argument(
        "--cjkvi", action="store_true", help="cjkvi-variants 추출본 (라이선스 미확인, 로컬 전용)"
    )
    ap.add_argument("--cjkvi-dir", type=Path, help="이미 내려받은 cjkvi-variants 디렉터리")
    args = ap.parse_args(argv)

    if not (
        args.opencc
        or args.opencc_dir
        or args.unihan
        or args.unihan_zip
        or args.cjkvi
        or args.cjkvi_dir
    ):
        ap.print_help()
        return 1

    if args.opencc or args.opencc_dir:
        build_opencc(args.opencc_dir)
    if args.unihan or args.unihan_zip:
        build_unihan(args.unihan_zip)
    if args.cjkvi or args.cjkvi_dir:
        build_cjkvi(args.cjkvi_dir)
    print(
        "완료. 사전은 «이체자 관리» 화면 목록에 층과 함께 나타난다. "
        "본문은 어느 사전으로도 바뀌지 않는다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
