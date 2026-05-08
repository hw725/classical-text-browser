"""SikuRoBERTa 기반 표점 추론.

yachagye/korean-classical-chinese-punctuation의 inference/구두점7_추론모델.py
구조를 참고했다. 본 모듈은 다음 두 가지를 추가한다:

1. PyTorch Lightning 의존성 제거 — 체크포인트의 hyper_parameters와 state_dict만
   읽어 일반 PyTorch 모듈로 재구성한다 (학습 환경 없이 배포 환경 가벼움).
2. 본체(classical-text-browser)와 호환되는 marks 배열 동시 생성 — punctuated
   문자열뿐 아니라 [{start, end, before, after}, ...] 형태의 정렬 정보를 함께 반환한다.

설계 결정:
- 무거운 import(torch, transformers, numpy)는 모두 메서드 안쪽으로 미룬다.
  Mock 엔진만 사용하는 경우 이 모듈을 import해도 실패하지 않게 하기 위함.
- 체크포인트 로드 시 weights_only=False 를 명시한다. PyTorch 2.6+에서 기본값이
  바뀌어 Lightning ckpt의 hyper_parameters dict를 못 읽는 사고를 방지.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# 7-class 라벨. 학습 시와 동일한 인덱스 순서. 변경 금지.
# yachagye 모델의 출력 차원 0~6에 1:1 매칭된다.
LABELS: list[str] = [",", "。", "·", "?", "!", "《", "》"]

# 같은 토큰 위치에 동시에 예측되면 모순이 되는 쌍.
# 두 부호가 모두 1로 나오면 신뢰도(시그모이드 점수)가 높은 쪽만 남긴다.
INVALID_PAIRS: list[tuple[str, str]] = [
    ("。", "?"),
    ("。", "!"),
    ("?", "!"),
]

# 모델 max_length=512에 안전 마진을 두고 청크 분할하는 임계값.
# 한자 1자=1토큰이지만 BERT는 [CLS]/[SEP]도 차지하므로 400자가 안전.
LONG_TEXT_THRESHOLD = 400


class PunctuationPredictor:
    """표점 예측기.

    구조: AutoModel(BERT) backbone + Dropout + Linear(num_labels=7) head.
    다중 라벨(multi-label) 분류이므로 sigmoid + threshold 사용.
    """

    def __init__(self, checkpoint_path: str | Path, device: str = "auto") -> None:
        # 메서드 안쪽 import: 모듈 임포트 시점에는 torch가 없어도 OK
        # (Mock 엔진만 쓰는 환경에서 이 모듈을 import해도 안전).
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch  # 다른 메서드에서 재사용

        ckpt_path = Path(checkpoint_path)
        if not ckpt_path.is_file():
            raise FileNotFoundError(f"체크포인트 파일이 없습니다: {ckpt_path}")

        # 디바이스 선택. CUDA가 없으면 자동으로 CPU로 폴백한다.
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)
        logger.info("SikuRoBERTa 디바이스: %s", self.device)

        # 체크포인트 로드.
        # weights_only=False — Lightning ckpt는 hyper_parameters(메타 dict)를 포함하므로
        # PyTorch 2.6+의 보안 기본값(True)으로는 로드되지 않는다.
        ckpt = torch.load(str(ckpt_path), map_location=self.device, weights_only=False)
        if "hyper_parameters" not in ckpt or "state_dict" not in ckpt:
            raise ValueError(
                "예상치 못한 체크포인트 구조입니다. "
                "yachagye Lightning 체크포인트(.ckpt)인지 확인하세요."
            )
        hparams = ckpt["hyper_parameters"]

        self.model_name: str = hparams["model_name"]
        self.num_labels: int = int(hparams["num_labels"])
        self.threshold: float = float(hparams.get("threshold", 0.5))
        dropout_rate = float(hparams.get("dropout_rate", 0.1))

        if self.num_labels != len(LABELS):
            raise ValueError(
                f"num_labels({self.num_labels})가 LABELS 길이({len(LABELS)})와 다릅니다. "
                f"학습 시 라벨 정의가 본 모듈의 LABELS와 일치해야 합니다."
            )

        # 베이스 BERT + 헤드 재구성. 베이스 모델은 HuggingFace에서 로드된다
        # (첫 호출 시 인터넷 다운로드 발생할 수 있음 — 사용자 안내 필요).
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.bert = AutoModel.from_pretrained(self.model_name)
        self.dropout = torch.nn.Dropout(dropout_rate)
        self.classifier = torch.nn.Linear(self.bert.config.hidden_size, self.num_labels)

        # Lightning state_dict의 키는 "bert.<...>" / "classifier.<...>"로 시작.
        # 각 모듈에 맞게 prefix를 떼고 load_state_dict.
        sd = ckpt["state_dict"]
        bert_sd = {k[len("bert."):]: v for k, v in sd.items() if k.startswith("bert.")}
        clf_sd = {
            k[len("classifier."):]: v
            for k, v in sd.items()
            if k.startswith("classifier.")
        }
        self.bert.load_state_dict(bert_sd)
        self.classifier.load_state_dict(clf_sd)

        self.bert.to(self.device).eval()
        self.classifier.to(self.device).eval()

    # ── 공개 메서드 ─────────────────────────────────────────────────

    def punctuate(self, text: str) -> tuple[str, list[dict]]:
        """원문을 받아 (punctuated, marks)를 반환.

        marks: [{start, end, before, after}, ...]
            - start == end - 1: 부호 직전 글자 인덱스 (점 부호이므로 길이 1).
            - 한 글자 뒤에 부호가 여러 개면 LABELS 순서로 합쳐 after에 들어간다.
            - 본체 _normalize_punct_marks() 와 호환.
        """
        if not text:
            return "", []
        if len(text) > LONG_TEXT_THRESHOLD:
            return self._punctuate_long(text)
        return self._punctuate_chunk(text)

    # ── 내부 ────────────────────────────────────────────────────────

    def _punctuate_chunk(self, text: str) -> tuple[str, list[dict]]:
        torch = self._torch
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        ).to(self.device)

        with torch.no_grad():
            outputs = self.bert(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            )
            seq = self.dropout(outputs.last_hidden_state)
            logits = self.classifier(seq)
            scores = torch.sigmoid(logits)[0].cpu().numpy()

        binary = (scores > self.threshold).astype("int64")
        binary = self._resolve_conflicts(binary, scores)

        tokens = self.tokenizer.convert_ids_to_tokens(inputs["input_ids"][0])
        return self._build_result(text, tokens, binary)

    def _punctuate_long(self, text: str) -> tuple[str, list[dict]]:
        """긴 텍스트는 청크 단위로 처리. 마크의 start/end는 원문 기준으로 시프트."""
        all_marks: list[dict] = []
        out_parts: list[str] = []
        offset = 0
        for chunk in _iter_chunks(text, LONG_TEXT_THRESHOLD):
            punctuated, marks = self._punctuate_chunk(chunk)
            for m in marks:
                shifted = dict(m)
                shifted["start"] = m["start"] + offset
                shifted["end"] = m["end"] + offset
                all_marks.append(shifted)
            out_parts.append(punctuated)
            offset += len(chunk)
        return "".join(out_parts), all_marks

    @staticmethod
    def _resolve_conflicts(binary, scores):
        """같은 토큰에 충돌하는 부호 둘 다 1이면, sigmoid 점수가 높은 쪽만 유지."""
        import numpy as np

        out = binary.copy()
        for p1, p2 in INVALID_PAIRS:
            if p1 not in LABELS or p2 not in LABELS:
                continue
            i1, i2 = LABELS.index(p1), LABELS.index(p2)
            both = (out[:, i1] == 1) & (out[:, i2] == 1)
            if not both.any():
                continue
            for row in np.where(both)[0]:
                if scores[row, i1] >= scores[row, i2]:
                    out[row, i2] = 0
                else:
                    out[row, i1] = 0
        return out

    @staticmethod
    def _build_result(
        text: str, tokens: list[str], binary
    ) -> tuple[str, list[dict]]:
        """토큰 단위 예측을 원문 글자에 정렬하여 (punctuated, marks)로 빌드.

        SikuRoBERTa(중국어 BERT 계열)는 한자 1자 = 1 토큰이라
        ##접두 subword가 거의 없다. 그래도 보호적으로 ##토큰은 건너뛴다.
        """
        out_chars: list[str] = []
        marks: list[dict] = []
        char_idx = 0

        for tok_idx, tok in enumerate(tokens):
            if tok in ("[CLS]", "[SEP]", "[PAD]"):
                continue
            if tok.startswith("##"):
                # subword 결합 토큰 — 원문 char 인덱스를 진행시키지 않는다.
                continue
            if char_idx >= len(text):
                break

            out_chars.append(text[char_idx])

            # 이 토큰 위치에 예측된 부호들을 LABELS 순서로 부착.
            if tok_idx < len(binary):
                row = binary[tok_idx]
                attached: list[str] = [
                    LABELS[i] for i in range(len(LABELS)) if row[i] == 1
                ]
                if attached:
                    after = "".join(attached)
                    out_chars.append(after)
                    marks.append({
                        "start": char_idx,
                        "end": char_idx + 1,
                        "before": "",
                        "after": after,
                    })

            char_idx += 1

        # 토큰 한도(512)에 잘려 남은 글자는 그대로 이어붙임 (부호 없이).
        if char_idx < len(text):
            out_chars.append(text[char_idx:])

        return "".join(out_chars), marks


def _iter_chunks(text: str, size: int) -> Iterable[str]:
    """텍스트를 size 글자씩 자르는 단순 청커.

    문장 경계를 인식하진 않는다. 청크 경계 직전 부호 예측이 살짝 흔들릴 수 있으나
    422자 학습/512 토큰 한도를 안전하게 지키는 것이 우선.
    """
    for i in range(0, len(text), size):
        yield text[i:i + size]
