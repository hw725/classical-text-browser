"""환경 진단 CLI — `python scripts/doctor.py` (어느 파이썬으로 실행해도 된다).

.venv·.venv-gpu를 각각 그 환경의 파이썬으로 조사해 PaddleOCR 등 엔진이 왜 안 되는지와
무엇을 지우고 남길지 권고한다. 파일은 지우지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path


# CJK Text Contract E3 — 한국어 Windows 콘솔은 cp949 라 «—»·«✓» 를 print 하면
# UnicodeEncodeError 로 즉사한다. 이 PC 는 PYTHONUTF8=1 이 박혀 있어 겪지 않는다.
from core.console import force_utf8_console

force_utf8_console()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core.env_doctor import diagnose, format_report, recommend  # noqa: E402


def main() -> int:
    report = diagnose(ROOT)
    recs = recommend(report)
    print(format_report(report, recs))
    if "--json" in sys.argv:
        import json

        print(json.dumps({"report": report, "recommendations": recs}, ensure_ascii=False, indent=2))
    return 1 if any(r["level"] == "fix" for r in recs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
