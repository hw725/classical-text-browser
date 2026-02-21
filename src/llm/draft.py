"""LlmDraft — Draft → Review → Commit 패턴.

LLM 결과는 항상 Draft 상태로 생성.
사람이 검토(accept/modify/reject) 후 확정.

레이아웃 분석, 번역, 주석 등 모든 LLM 기능에서 사용.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LlmDraft:
    """LLM 결과의 Draft.

    흐름:
        LLM 호출 → Draft(pending) → 사람 검토 → accepted/modified/rejected → Commit
    """

    draft_id: str = field(
        default_factory=lambda: str(uuid.uuid4())[:8]
    )
    purpose: str = ""               # "layout_analysis", "translation", "annotation"
    status: str = "pending"         # pending → accepted | modified | rejected

    # LLM 결과
    provider: str = ""
    model: str = ""
    prompt_used: str = ""
    response_text: str = ""
    response_data: Optional[dict] = None  # 구조화된 결과 (JSON 파싱 후)

    # 비용
    cost_usd: float = 0.0
    elapsed_sec: float = 0.0

    # 검토 결과
    reviewed_by: str = "user"
    reviewed_at: Optional[str] = None
    modifications: Optional[str] = None  # modified일 때 변경 내용 설명

    # 품질 평가 (비교 테스트용)
    quality_rating: Optional[int] = None     # 1~5점
    quality_notes: Optional[str] = None      # "주석 영역 빠뜨림"
    compared_with: Optional[list] = None     # ["base44_bridge", "anthropic"]
    chosen_reason: Optional[str] = None      # "블록 구분 가장 정확"

    # 타임스탬프
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def accept(self, quality_rating: Optional[int] = None, notes: str = ""):
        """Draft를 승인한다."""
        self.status = "accepted"
        self.reviewed_at = datetime.now().isoformat()
        if quality_rating:
            self.quality_rating = quality_rating
        if notes:
            self.quality_notes = notes

    def modify(self, modifications: str, quality_rating: Optional[int] = None):
        """Draft를 수정 후 승인한다."""
        self.status = "modified"
        self.reviewed_at = datetime.now().isoformat()
        self.modifications = modifications
        if quality_rating:
            self.quality_rating = quality_rating

    def reject(self, reason: str = ""):
        """Draft를 거부한다."""
        self.status = "rejected"
        self.reviewed_at = datetime.now().isoformat()
        self.quality_notes = reason

    def to_dict(self) -> dict:
        """JSON 직렬화용."""
        return {k: v for k, v in self.__dict__.items() if v is not None}
