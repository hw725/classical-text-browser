# -*- coding: utf-8 -*-
# 정본: yoon/oauth_quota.py, 2026-10-27 (C:\Users\junto\Downloads\2026\util\yoon\oauth_quota.py).
# 이 사본은 손대지 않는다(긴 줄 noqa 표시만 더함) — 앱용 캐시·막힘 해제는
# providers/openai_oauth_provider.py 의 OAuthQuotaGuard 가 감싼다.
"""OpenAI 구독 OAuth 남은 사용량 조회 — `codex /status` 와 같은 값.

2026-10-27 사용자 지시: OAuth 를 쓸 때마다 남은 사용량을 먼저 확인하고 그만큼 작업에 들어간다.
고정 상한(20·100000)은 남은 양을 모른 채 들어가는 것이라 쓰지 않는다.

`codex app-server`(stdio JSON-RPC)의 account/rateLimits/read 를 부른다. 읽기 전용이라
사용량을 소비하지 않는다. 조회에 실패하면 None 을 돌려주고, 부르는 쪽은 「모름」으로 다룬다.

    python oauth_quota.py          # 사람용 요약
    python oauth_quota.py --json   # 원 응답
"""
import json
import shutil
import subprocess
import sys
import threading
import time

TIMEOUT = 60


def _codex_cmd():
    exe = shutil.which("codex") or shutil.which("codex.cmd")
    if not exe:
        raise RuntimeError("codex CLI 를 찾지 못했습니다")
    return [exe, "app-server"]


def read_quota(timeout=TIMEOUT):
    """account/rateLimits/read 응답(result)을 돌려준다. 실패하면 RuntimeError."""
    proc = subprocess.Popen(_codex_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, encoding="utf-8")
    replies = {}

    def pump():
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                replies[msg["id"]] = msg

    threading.Thread(target=pump, daemon=True).start()

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def wait(rid):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if rid in replies:
                m = replies[rid]
                if "error" in m:
                    raise RuntimeError(f"app-server 오류: {m['error']}")
                return m["result"]
            if proc.poll() is not None:
                raise RuntimeError(f"codex app-server 가 종료했습니다(코드 {proc.returncode})")
            time.sleep(0.05)
        raise RuntimeError(f"{timeout}초 안에 응답이 없습니다")

    try:
        send({"id": 1, "method": "initialize",
              "params": {"clientInfo": {"name": "yoon_oauth_quota", "version": "1"}}})
        wait(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read", "params": None})
        return wait(2)
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()     # 이 함수가 띄운 자식 프로세스만 끈다


def _window(w):
    if not w:
        return None
    mins = w.get("windowDurationMins")
    reset = w.get("resetsAt")
    return {"used_pct": w.get("usedPercent"),
            "left_pct": 100 - w["usedPercent"] if w.get("usedPercent") is not None else None,
            "window_min": mins,
            "resets_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(reset)) if reset else None}


def summarize(res):
    """창별 남은 % 와 사용 가능 여부. left_pct 는 창들 중 가장 적게 남은 값."""
    rl = res.get("rateLimits") or {}
    wins = {k: _window(rl.get(k)) for k in ("primary", "secondary")}
    lefts = [w["left_pct"] for w in wins.values() if w and w["left_pct"] is not None]
    return {"plan": rl.get("planType"),
            "allowed": res.get("ordinaryUsageAllowed"),
            "reached": rl.get("rateLimitReachedType"),
            "windows": wins,
            "left_pct": min(lefts) if lefts else None}


def describe(s):
    parts = []
    for name, w in s["windows"].items():
        if w:
            span = (f"{w['window_min'] // 60}시간" if w["window_min"] and w["window_min"] < 1440
                    else f"{w['window_min'] // 1440}일" if w["window_min"] else name)
            parts.append(f"{span} 창 {w['left_pct']}% 남음(리셋 {w['resets_at'] or '모름'})")
    head = f"OAuth 남은 사용량 [{s['plan'] or '요금제 모름'}]: " + (" · ".join(parts) or "창 정보 없음")  # noqa: E501
    if s["allowed"] is False or s["reached"]:
        head += f"  ※ 지금 사용 불가({s['reached'] or 'ordinaryUsageAllowed=false'})"
    return head


RESERVE_PCT = 10     # 이 아래로 남으면 OAuth 를 멈춘다(다른 Codex 작업 몫). --oauth-reserve 로 바꾼다  # noqa: E501
RECHECK_EVERY = 20   # 호출 이만큼마다 다시 조회한다


class QuotaGate:
    """OAuth 호출 직전마다 묻는 문지기. 첫 호출 전과 RECHECK_EVERY 회마다 남은 양을 다시 읽는다.

    allow() 가 False 면 부르는 쪽은 호출하지 않고 보류로 남긴다. 조회 실패도 False(「모름」)다 —
    남은 양을 모른 채 들어가지 않는다.
    """

    def __init__(self, reserve_pct=RESERVE_PCT, every=RECHECK_EVERY, reader=None, say=print):
        # reader 를 만들 때 고른다 — 시험이 모듈의 read_quota 를 갈아끼울 수 있게
        self.reserve, self.every, self.say = reserve_pct, every, say
        self.reader = reader or read_quota
        self.calls = self._since = 0
        self.first = self.last = None
        self.stopped = None

    def _read(self):
        try:
            s = summarize(self.reader())
        except Exception as e:
            self.stopped = f"남은 사용량 모름({type(e).__name__}: {e})"
            return None
        self.last = s
        if self.first is None:
            self.first = s
        return s

    def allow(self):
        if self.stopped:
            return False
        if self.last is None or self._since >= self.every:
            self._since = 0
            s = self._read()
            if s is None:
                self.say(f"  [OAuth] {self.stopped} — 이후 항목은 보류로 남깁니다")
                return False
            self.say(f"  [OAuth] {describe(s)} · 이번 실행 호출 {self.calls:,}회")
            if s["allowed"] is False or s["reached"]:
                self.stopped = f"사용 불가({s['reached'] or 'ordinaryUsageAllowed=false'})"
            elif s["left_pct"] is None:
                self.stopped = "남은 % 를 응답에서 못 읽음"
            elif s["left_pct"] <= self.reserve:
                self.stopped = f"남은 {s['left_pct']}% ≤ 예비 {self.reserve}%"
            if self.stopped:
                self.say(f"  [OAuth] 멈춤 — {self.stopped}. 이후 항목은 보류로 남깁니다")
                return False
        return True

    def note_call(self):
        self.calls += 1
        self._since += 1

    def report(self):
        """실행 끝에 쓰는 한 줄 — 호출 수와 그동안 줄어든 %(호출당 소비 실측 근거)."""
        if self.first is None:
            return f"OAuth 남은 사용량: 조회 못 함 — {self.stopped or '호출 없음'}"
        s = self._read() or self.last
        drop = (self.first["left_pct"] or 0) - (s["left_pct"] or 0)
        per = f" · 호출당 약 {drop / self.calls:.3f}%p" if self.calls and drop > 0 else ""
        return (f"OAuth 호출 {self.calls:,}회 · 시작 {self.first['left_pct']}% → 지금 {s['left_pct']}% 남음"  # noqa: E501
                f"{per}" + (f" · 멈춘 이유: {self.stopped}" if self.stopped else ""))


def main():
    # 이 사본에서만 더함(CJK 계약 E3): cp949 콘솔에서 한글 출력이 UnicodeEncodeError 로 죽지 않게
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        res = read_quota()
    except Exception as e:
        print(f"OAuth 남은 사용량: 모름 — {e}")
        return 2
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(describe(summarize(res)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
