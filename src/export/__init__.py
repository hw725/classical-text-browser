"""연구 산출물 내보내기 패키지.

D-018(JSON 스냅샷)이 정의한 "교환 형식"과는 다른 축이다.
교환 형식은 다른 사람의 서고로 작업을 옮기기 위한 것이고,
이 패키지는 서고 밖에서 쓰는 **최종 산출물**을 입힌다.

현재 구성:
    text_layer_pdf — 원본 스캔 PDF에 보이지 않는 텍스트 레이어를 얹는다.
"""

from .text_layer_pdf import EmbedResult, embed_text_layer

__all__ = ["EmbedResult", "embed_text_layer"]
