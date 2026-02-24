"""Phase 12-1: Git 그래프 통합 테스트.

테스트 시나리오:
1. trailer 파싱 테스트
2. layers_affected 추출 테스트
3. 커밋 로그 수집 테스트
4. 링크 생성 테스트 (explicit / estimated)
5. API 데이터 생성 테스트
6. Based-On-Original trailer 자동 기록 테스트
"""

import json
import os
import textwrap
from pathlib import Path

import git
import pytest

from src.core.git_graph import (
    _collect_commits,
    _find_nearest_original_before,
    build_links,
    extract_layers_affected,
    get_git_graph_data,
    parse_trailer,
)


# ──────────────────────────────────────
# 1. trailer 파싱 테스트
# ──────────────────────────────────────


class TestParseTrailer:
    """parse_trailer() 함수 테스트."""

    def test_basic_trailer(self):
        """기본 trailer를 파싱한다."""
        msg = textwrap.dedent("""\
            feat: L5 표점 추가

            Based-On-Original: abc123def456
        """)
        assert parse_trailer(msg, "Based-On-Original") == "abc123def456"

    def test_no_trailer(self):
        """trailer가 없으면 None을 반환한다."""
        msg = "feat: L4 확정 텍스트 수정"
        assert parse_trailer(msg, "Based-On-Original") is None

    def test_multiple_trailers(self):
        """여러 trailer 중 특정 key만 추출한다."""
        msg = textwrap.dedent("""\
            feat: L5 표점 추가

            Signed-off-by: researcher
            Based-On-Original: abc123
        """)
        assert parse_trailer(msg, "Based-On-Original") == "abc123"
        assert parse_trailer(msg, "Signed-off-by") == "researcher"

    def test_trailer_with_full_hash(self):
        """40자 전체 해시를 파싱한다."""
        full_hash = "a" * 40
        msg = f"feat: L6 번역\n\nBased-On-Original: {full_hash}"
        assert parse_trailer(msg, "Based-On-Original") == full_hash

    def test_trailer_with_spaces(self):
        """trailer 값에 공백이 있는 경우."""
        msg = "feat: L5\n\nBased-On-Original:   abc123  "
        assert parse_trailer(msg, "Based-On-Original") == "abc123"


# ──────────────────────────────────────
# 2. layers_affected 추출 테스트
# ──────────────────────────────────────


class TestExtractLayers:
    """extract_layers_affected() 함수 테스트."""

    def test_single_layer(self):
        assert extract_layers_affected("feat: L4 확정 텍스트 수정") == ["L4"]

    def test_multiple_layers(self):
        result = extract_layers_affected("feat: L1 L2 이미지 + OCR")
        assert "L1" in result
        assert "L2" in result

    def test_sub_layer_punctuation(self):
        result = extract_layers_affected("feat: L5 punctuation 추가")
        assert "L5" in result
        assert "L5_punctuation" in result

    def test_sub_layer_hyeonto(self):
        result = extract_layers_affected("feat: L5 hyeonto 추가")
        assert "L5" in result
        assert "L5_hyeonto" in result

    def test_sub_layer_translation(self):
        result = extract_layers_affected("feat: L6 translation")
        assert "L6" in result
        assert "L6_translation" in result

    def test_no_layer(self):
        assert extract_layers_affected("fix: 버그 수정") == ["unknown"]

    def test_case_insensitive_sub_layer(self):
        """서브 레이어 키워드는 대소문자 구분 없이 검색된다."""
        result = extract_layers_affected("feat: L5 Punctuation 작업")
        assert "L5_punctuation" in result


# ──────────────────────────────────────
# 3. 커밋 로그 수집 테스트
# ──────────────────────────────────────


class TestCollectCommits:
    """_collect_commits() 함수 테스트."""

    def test_empty_repo(self, tmp_path):
        """빈 저장소에서 수집하면 빈 리스트를 반환한다."""
        repo = git.Repo.init(tmp_path / "empty_repo")
        commits, total, branches, _head = _collect_commits(tmp_path / "empty_repo")
        assert commits == []
        assert total == 0

    def test_nonexistent_path(self, tmp_path):
        """존재하지 않는 경로에서 수집하면 빈 리스트를 반환한다."""
        commits, total, branches, _head = _collect_commits(tmp_path / "no_such_repo")
        assert commits == []
        assert total == 0
        assert branches == []

    def test_collect_from_repo(self, tmp_path):
        """정상 저장소에서 커밋을 수집한다."""
        repo_path = tmp_path / "test_repo"
        repo = git.Repo.init(repo_path)

        # 커밋 3개 생성
        for i in range(3):
            (repo_path / f"file{i}.txt").write_text(f"content {i}", encoding="utf-8")
            repo.index.add([f"file{i}.txt"])
            repo.index.commit(f"feat: L{i+1} 작업 {i}")

        branch = repo.active_branch.name
        commits, total, branches, _head = _collect_commits(repo_path, branch=branch)

        assert total == 3
        assert len(commits) == 3
        # 최신 커밋이 먼저
        assert "L3" in commits[0]["message"]
        assert commits[0]["short_hash"] == commits[0]["hash"][:7]
        assert "layers_affected" in commits[0]

    def test_pagination(self, tmp_path):
        """limit/offset 페이지네이션이 동작한다."""
        repo_path = tmp_path / "page_repo"
        repo = git.Repo.init(repo_path)

        for i in range(5):
            (repo_path / f"f{i}.txt").write_text(f"c{i}", encoding="utf-8")
            repo.index.add([f"f{i}.txt"])
            repo.index.commit(f"commit {i}")

        branch = repo.active_branch.name
        commits, total, _, _head = _collect_commits(repo_path, branch=branch, max_count=2, offset=1)
        assert total == 5
        assert len(commits) == 2


# ──────────────────────────────────────
# 4. 링크 생성 테스트
# ──────────────────────────────────────


class TestBuildLinks:
    """build_links() 함수 테스트."""

    def test_explicit_link(self):
        """trailer가 있는 커밋은 explicit 링크를 생성한다."""
        orig = [{"hash": "abc123", "timestamp": "2026-01-01T10:00:00"}]
        interp = [{
            "hash": "def456",
            "timestamp": "2026-01-01T11:00:00",
            "message": "feat: L5\n\nBased-On-Original: abc123",
        }]

        links = build_links(orig, interp)
        assert len(links) == 1
        assert links[0]["match_type"] == "explicit"
        assert links[0]["original_hash"] == "abc123"
        assert links[0]["interp_hash"] == "def456"

    def test_estimated_link(self):
        """trailer가 없는 커밋은 타임스탬프 기반 estimated 링크를 생성한다."""
        orig = [
            {"hash": "orig1", "timestamp": "2026-01-01T09:00:00"},
            {"hash": "orig2", "timestamp": "2026-01-01T10:00:00"},
        ]
        interp = [{
            "hash": "interp1",
            "timestamp": "2026-01-01T10:30:00",
            "message": "feat: L5 표점",
        }]

        links = build_links(orig, interp)
        assert len(links) == 1
        assert links[0]["match_type"] == "estimated"
        # 해석 커밋 직전의 원본 커밋(10:00)을 찾아야 함
        assert links[0]["original_hash"] == "orig2"

    def test_no_original_commits(self):
        """원본 커밋이 없으면 링크가 생성되지 않는다."""
        interp = [{
            "hash": "interp1",
            "timestamp": "2026-01-01T10:00:00",
            "message": "feat: L5",
        }]
        links = build_links([], interp)
        assert len(links) == 0

    def test_mixed_links(self):
        """explicit과 estimated가 섞인 경우."""
        orig = [
            {"hash": "orig1", "timestamp": "2026-01-01T10:00:00"},
        ]
        interp = [
            {
                "hash": "interp1",
                "timestamp": "2026-01-01T11:00:00",
                "message": "feat: L5\n\nBased-On-Original: orig1",
            },
            {
                "hash": "interp2",
                "timestamp": "2026-01-01T12:00:00",
                "message": "feat: L6 번역",
            },
        ]

        links = build_links(orig, interp)
        assert len(links) == 2
        types = {l["match_type"] for l in links}
        assert "explicit" in types
        assert "estimated" in types


# ──────────────────────────────────────
# 5. find_nearest 테스트
# ──────────────────────────────────────


class TestFindNearest:
    """_find_nearest_original_before() 함수 테스트."""

    def test_finds_nearest(self):
        """해석 커밋 직전의 원본 커밋을 찾는다."""
        sorted_commits = [
            {"hash": "c3", "timestamp": "2026-01-03T10:00:00"},
            {"hash": "c2", "timestamp": "2026-01-02T10:00:00"},
            {"hash": "c1", "timestamp": "2026-01-01T10:00:00"},
        ]
        result = _find_nearest_original_before("2026-01-02T15:00:00", sorted_commits)
        assert result["hash"] == "c2"

    def test_all_after(self):
        """모든 원본이 해석 이후면 가장 오래된 것을 반환한다."""
        sorted_commits = [
            {"hash": "c2", "timestamp": "2026-01-03T10:00:00"},
            {"hash": "c1", "timestamp": "2026-01-02T10:00:00"},
        ]
        result = _find_nearest_original_before("2026-01-01T10:00:00", sorted_commits)
        assert result["hash"] == "c1"

    def test_empty(self):
        """빈 리스트면 None을 반환한다."""
        assert _find_nearest_original_before("2026-01-01T10:00:00", []) is None


# ──────────────────────────────────────
# 6. API 데이터 생성 (통합) 테스트
# ──────────────────────────────────────


class TestGetGitGraphData:
    """get_git_graph_data() 통합 테스트. 실제 git 저장소를 만들어 테스트한다."""

    @pytest.fixture
    def library_with_repos(self, tmp_path):
        """테스트용 서고 + 원본/해석 저장소를 생성한다."""
        library = tmp_path / "test_library"
        doc_path = library / "documents" / "monggu"
        interp_path = library / "interpretations" / "monggu_interp_001"

        # 원본 저장소 생성 + 커밋
        doc_path.mkdir(parents=True)
        doc_repo = git.Repo.init(doc_path)
        (doc_path / "L4_text.txt").write_text("原文", encoding="utf-8")
        doc_repo.index.add(["L4_text.txt"])
        doc_repo.index.commit("feat: L4 확정텍스트 추가")
        orig_head = doc_repo.head.commit.hexsha

        # 해석 저장소 생성 + manifest + 커밋 (trailer 포함)
        interp_path.mkdir(parents=True)
        interp_repo = git.Repo.init(interp_path)
        manifest = {
            "interp_id": "monggu_interp_001",
            "source_document_id": "monggu",
        }
        (interp_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (interp_path / "L5_punct.json").write_text("{}", encoding="utf-8")
        interp_repo.index.add(["manifest.json", "L5_punct.json"])
        interp_repo.index.commit(
            f"feat: L5 punctuation 표점 작업\n\nBased-On-Original: {orig_head}"
        )

        return library, doc_path, interp_path, orig_head

    def test_graph_data_structure(self, library_with_repos):
        """그래프 데이터가 올바른 구조를 갖는지 확인한다."""
        library, doc_path, interp_path, _ = library_with_repos

        # 브랜치 이름 확인 (init 시 기본 브랜치)
        doc_repo = git.Repo(doc_path)
        interp_repo = git.Repo(interp_path)
        orig_branch = doc_repo.active_branch.name
        interp_branch = interp_repo.active_branch.name

        data = get_git_graph_data(
            library, "monggu", "monggu_interp_001",
            original_branch=orig_branch,
            interp_branch=interp_branch,
        )

        assert "original" in data
        assert "interpretation" in data
        assert "links" in data
        assert "pagination" in data

        assert len(data["original"]["commits"]) == 1
        assert len(data["interpretation"]["commits"]) == 1

    def test_explicit_link_created(self, library_with_repos):
        """Based-On-Original trailer로 explicit 링크가 생성되는지 확인한다."""
        library, doc_path, interp_path, orig_head = library_with_repos

        doc_repo = git.Repo(doc_path)
        interp_repo = git.Repo(interp_path)
        orig_branch = doc_repo.active_branch.name
        interp_branch = interp_repo.active_branch.name

        data = get_git_graph_data(
            library, "monggu", "monggu_interp_001",
            original_branch=orig_branch,
            interp_branch=interp_branch,
        )

        # explicit 링크가 있어야 함
        explicit_links = [l for l in data["links"] if l["match_type"] == "explicit"]
        assert len(explicit_links) == 1
        assert explicit_links[0]["original_hash"] == orig_head

    def test_interp_commit_has_base_hash(self, library_with_repos):
        """해석 커밋에 base_original_hash 필드가 채워지는지 확인한다."""
        library, doc_path, interp_path, orig_head = library_with_repos

        doc_repo = git.Repo(doc_path)
        interp_repo = git.Repo(interp_path)
        orig_branch = doc_repo.active_branch.name
        interp_branch = interp_repo.active_branch.name

        data = get_git_graph_data(
            library, "monggu", "monggu_interp_001",
            original_branch=orig_branch,
            interp_branch=interp_branch,
        )

        ic = data["interpretation"]["commits"][0]
        assert ic["base_original_hash"] == orig_head
        assert ic["base_match_type"] == "explicit"

    def test_layers_affected_in_commits(self, library_with_repos):
        """커밋에 layers_affected가 올바르게 추출되는지 확인한다."""
        library, doc_path, interp_path, _ = library_with_repos

        doc_repo = git.Repo(doc_path)
        interp_repo = git.Repo(interp_path)
        orig_branch = doc_repo.active_branch.name
        interp_branch = interp_repo.active_branch.name

        data = get_git_graph_data(
            library, "monggu", "monggu_interp_001",
            original_branch=orig_branch,
            interp_branch=interp_branch,
        )

        orig_layers = data["original"]["commits"][0]["layers_affected"]
        assert "L4" in orig_layers

        interp_layers = data["interpretation"]["commits"][0]["layers_affected"]
        assert "L5" in interp_layers
        assert "L5_punctuation" in interp_layers

    def test_pagination_info(self, library_with_repos):
        """pagination 정보가 올바른지 확인한다."""
        library, doc_path, interp_path, _ = library_with_repos

        doc_repo = git.Repo(doc_path)
        interp_repo = git.Repo(interp_path)

        data = get_git_graph_data(
            library, "monggu", "monggu_interp_001",
            original_branch=doc_repo.active_branch.name,
            interp_branch=interp_repo.active_branch.name,
        )

        assert data["pagination"]["total_original"] == 1
        assert data["pagination"]["total_interpretation"] == 1
        assert data["pagination"]["has_more"] is False

    def test_nonexistent_doc_repo(self, tmp_path):
        """원본 저장소가 없으면 빈 커밋을 반환한다."""
        library = tmp_path / "lib2"
        library.mkdir()

        data = get_git_graph_data(library, "no_doc", "no_interp")
        assert data["original"]["commits"] == []
        assert data["interpretation"]["commits"] == []
        assert data["links"] == []


# ──────────────────────────────────────
# 7. Based-On-Original trailer 자동 기록 테스트
# ──────────────────────────────────────


class TestTrailerAutoRecord:
    """_append_based_on_trailer() + git_commit_interpretation() 통합 테스트."""

    def test_trailer_appended_on_commit(self, tmp_path):
        """해석 커밋 시 Based-On-Original trailer가 자동 기록되는지 확인한다."""
        from src.core.interpretation import _append_based_on_trailer

        library = tmp_path / "lib3"
        doc_path = library / "documents" / "test_doc"
        interp_path = library / "interpretations" / "test_interp"

        # 원본 저장소
        doc_path.mkdir(parents=True)
        doc_repo = git.Repo.init(doc_path)
        (doc_path / "text.txt").write_text("원문", encoding="utf-8")
        doc_repo.index.add(["text.txt"])
        doc_repo.index.commit("init")
        orig_head = doc_repo.head.commit.hexsha

        # 해석 저장소 + manifest
        interp_path.mkdir(parents=True)
        manifest = {
            "interp_id": "test_interp",
            "source_document_id": "test_doc",
        }
        (interp_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        # trailer 추가 확인
        result = _append_based_on_trailer(interp_path, "feat: L5 작업")
        assert f"Based-On-Original: {orig_head}" in result

    def test_trailer_skipped_without_doc_repo(self, tmp_path):
        """원본 저장소가 없으면 trailer를 생략한다."""
        from src.core.interpretation import _append_based_on_trailer

        library = tmp_path / "lib4"
        interp_path = library / "interpretations" / "orphan_interp"
        interp_path.mkdir(parents=True)

        manifest = {
            "interp_id": "orphan_interp",
            "source_document_id": "nonexistent_doc",
        }
        (interp_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        result = _append_based_on_trailer(interp_path, "feat: 고아 커밋")
        assert result == "feat: 고아 커밋"  # trailer 없이 원래 메시지 그대로

    def test_trailer_skipped_without_manifest(self, tmp_path):
        """manifest.json이 없으면 trailer를 생략한다."""
        from src.core.interpretation import _append_based_on_trailer

        interp_path = tmp_path / "no_manifest"
        interp_path.mkdir(parents=True)

        result = _append_based_on_trailer(interp_path, "feat: 작업")
        assert result == "feat: 작업"
