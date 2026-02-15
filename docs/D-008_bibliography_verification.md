# bibliography.schema.json 검증 보고서

> 작성: 2025-02-15 · Phase 9 완료 시점  
> 검증 기준: Dublin Core, MARC21, KORCIS KORMARC, NDL DC-NDL, 형태서지학

---

## 1. 검증 요약

현재 bibliography.schema.json은 **디지털 아카이브 메타데이터** 관점에서는 잘 설계되어 있다. Dublin Core 15요소와의 매핑이 양호하고, raw_metadata / _mapping_info라는 투명성 장치가 특히 우수하다.

그러나 **고전서지학(형태서지학)** 관점에서 보면, 한중일 고서 판본 감별의 핵심 요소인 **판식정보**가 구조적으로 빠져 있다. 문헌정보학 관점에서는 **간행사항**과 **권책수** 구조도 부재하다.

### 한줄 판정

| 관점 | 판정 | 비고 |
|------|------|------|
| Dublin Core 대응 | ✅ 양호 | 15요소 중 11개 직접 매핑 가능 |
| NDL DC-NDL 대응 | ✅ 양호 | title_reading, classification, material_type 수용 |
| KORCIS 대응 | ⚠️ 부분적 | edition_type 수용, 판식정보 미수용 |
| 형태서지학 | ❌ 미흡 | 판식정보(광곽, 계선, 어미, 행자수) 전무 |
| 현대 디지털 아카이브 | ✅ 우수 | digital_source, raw_metadata, _mapping_info |

---

## 2. 현재 스키마의 강점

### 2.1 Dublin Core 매핑 현황

| DC 요소 | 현재 필드 | 매핑 품질 |
|---------|-----------|-----------|
| Title | title, title_reading, alternative_titles | ✅ 우수 (독음까지 포함) |
| Creator | creator | ✅ 양호 (role, period 포함) |
| Contributor | contributors[] | ✅ 양호 |
| Date | date_created | ✅ 양호 (자유 텍스트 — 고서에 적합) |
| Language | language | ✅ 양호 |
| Subject | subject[] | ✅ 양호 |
| Type | material_type | ✅ 양호 |
| Format | physical_description | ⚠️ 자유텍스트만 |
| Publisher | — | ❌ 없음 |
| Identifier | digital_source.system_ids | ⚠️ 디지털 ID만, 문헌 자체 식별자 없음 |
| Description | notes | ⚠️ "해제"와 구분 안됨 |
| Rights | digital_source.license | ⚠️ 디지털 복제본 라이선스만 |
| Source | — | N/A (raw_metadata로 보완) |
| Relation | — | N/A (코어 스키마 Relation이 담당) |
| Coverage | — | N/A (고서에서 덜 중요) |

### 2.2 플랫폼 고유 강점

- **raw_metadata**: 원본 API 응답을 그대로 보존 → 정보 손실 방지
- **_mapping_info**: 필드별 매핑 출처와 신뢰도(exact/inferred/partial) 기록 → 투명성 확보
- **모든 필드 nullable**: 소스에 없는 정보를 강제하지 않음 → 점진적 보강 가능
- **script 필드**: language와 별도로 문자 체계 기록 (한자/한글/카타카나 구분)

---

## 3. 누락 항목 분석

### 3.1 P0: 즉시 보완 권장

#### (A) 판식정보 (printing_info) — 가장 큰 갭

고전서지학에서 판본 감별의 핵심. KORCIS KORMARC 008 고서 고정길이 필드에 체계적으로 코드화되어 있으며, 한국 고서 목록에서는 필수 기술 항목이다.

```
예시: "사주쌍변 유계 반엽 10행 20자 주쌍행 상하내향이엽화문어미"
```

포함해야 할 하위 요소:

| 요소 | 설명 | 예시값 |
|------|------|--------|
| 광곽(匡郭) | 변란 형태 | 사주단변, 사주쌍변, 좌우쌍변 |
| 광곽 크기 | 세로×가로 cm | "20.5 × 14.8 cm" |
| 계선(界線) | 유무 | 유계(有界), 무계(無界) |
| 행자수(行字數) | 반엽 행수×자수 | "10행 20자" |
| 주 행자수 | 주석 행수 (쌍행 여부) | "주쌍행" |
| 판구(版口) | 판심 중봉 선 형태 | 대흑구, 소흑구, 백구 |
| 어미(魚尾) | 위치, 색, 방향, 문양 | "상하내향이엽화문어미" |
| 판심제(版心題) | 판심에 기록된 서명 | "蒙求" |

**참고**: 이 정보는 KORMARC 008 위치 18-34(고서)에 코드화되어 있다. KORCIS 파서가 이 값을 가져올 수 있다면 raw_metadata에 보존 + printing_info에 구조화.

#### (B) 간행사항 (publishing)

DC Publisher에 해당. 고서에서는 "누가 어디서 간행했는가"가 판본 판별의 핵심이다.

| 요소 | 설명 | 예시값 |
|------|------|--------|
| 간행지(刊行地) | 간행 장소 | "全州" |
| 간행처(刊行處) | 간행 기관/인물 | "完營" |
| 간행유형 | 관판/사찬/사찰판 등 | "관판(官板)" |

MARC 260$a(출판지), 260$b(출판자)에 해당.

#### (C) 권책수 (extent)

고서의 규모를 나타내는 기본 단위. manifest.parts[]로 물리 파일은 관리되지만, 서지적 "n卷 n冊" 기술이 없다.

| 요소 | 설명 | 예시값 |
|------|------|--------|
| 권수(卷數) | 논리적 권 수 | "3卷" |
| 책수(冊數) | 물리적 책 수 | "1冊" |
| 결락(缺落) | 빠진 권책 | "卷2缺" |

### 3.2 P1: 중기 보완 (raw_metadata로 임시 보완 가능)

| 항목 | 설명 | DC 대응 |
|------|------|---------|
| binding_type (장정) | 선장본, 포배장, 호접장, 절첩장 등 | DC Format 확장 |
| abstract (해제) | 내용·의의·특징 서술. notes와 분리 필요 | DC Description |
| provenance (전래정보) | 장서인(藏書印), 소장 이력, 기증 기록 | Qualified DC Provenance |
| identifier (문헌 식별자) | KORCIS 제어번호, NDL BID 등 문헌 자체의 ID | DC Identifier |

### 3.3 P2: 장기 (필요시 추가)

- rights: 원본 문헌의 저작권 상태 (공유영역 등)
- relation: 관련 문헌 (이판, 개간, 번각 등) — 코어 스키마 Relation이 담당 가능

---

## 4. 제안: printing_info 필드 설계 초안

"모든 필드 nullable" 원칙을 유지하면서, 판식정보를 구조화하는 초안:

```json
"printing_info": {
  "description": "판식정보. 형태서지학적 판본 감별 요소.",
  "oneOf": [
    { "type": "null" },
    {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "gwangwak": {
          "type": ["string", "null"],
          "description": "광곽(匡郭) 형태. 예: 사주단변, 사주쌍변, 좌우쌍변"
        },
        "gwangwak_size": {
          "type": ["string", "null"],
          "description": "광곽 크기 (세로×가로 cm). 예: 20.5 × 14.8 cm"
        },
        "gyeseon": {
          "type": ["string", "null"],
          "description": "계선(界線). 예: 유계, 무계"
        },
        "haengja": {
          "type": ["string", "null"],
          "description": "행자수(行字數). 예: 반엽 10행 20자"
        },
        "ju_haengja": {
          "type": ["string", "null"],
          "description": "주(注) 행자수. 예: 주쌍행, 주단행"
        },
        "pangoo": {
          "type": ["string", "null"],
          "description": "판구(版口). 예: 대흑구, 소흑구, 백구"
        },
        "eomi": {
          "type": ["string", "null"],
          "description": "어미(魚尾). 예: 상하내향이엽화문어미, 상흑어미"
        },
        "pansimje": {
          "type": ["string", "null"],
          "description": "판심제(版心題). 판심에 기록된 서명."
        },
        "summary": {
          "type": ["string", "null"],
          "description": "판식 요약 (자유 텍스트). 예: 사주쌍변 유계 반엽10행20자 주쌍행 상하내향이엽화문어미"
        }
      }
    }
  ],
  "default": null
}
```

---

## 5. 제안: publishing 필드 설계 초안

```json
"publishing": {
  "description": "간행사항. DC Publisher 대응.",
  "oneOf": [
    { "type": "null" },
    {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "place": {
          "type": ["string", "null"],
          "description": "간행지. 예: 全州, 京城"
        },
        "publisher": {
          "type": ["string", "null"],
          "description": "간행처/간행자. 예: 完營, 校書館"
        },
        "publication_type": {
          "type": ["string", "null"],
          "description": "간행 유형. 예: 관판, 사찬, 사찰판, 방각본"
        }
      }
    }
  ],
  "default": null
}
```

---

## 6. 제안: extent 필드 설계 초안

```json
"extent": {
  "description": "권책수. 고서의 논리적·물리적 규모.",
  "oneOf": [
    { "type": "null" },
    {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "volumes": {
          "type": ["string", "null"],
          "description": "권수(卷數). 예: 3卷"
        },
        "books": {
          "type": ["string", "null"],
          "description": "책수(冊數). 예: 1冊"
        },
        "missing": {
          "type": ["string", "null"],
          "description": "결락 정보. 예: 卷2缺, 零本"
        }
      }
    }
  ],
  "default": null
}
```

---

## 7. 기존 필드 소규모 보완 제안

| 필드 | 현재 | 제안 |
|------|------|------|
| notes | 자유 메모 | notes와 별도로 `abstract` (해제) 필드 추가 검토 |
| edition_type | 판종만 | 장정(binding_type)을 별도 필드로 분리 검토 |
| digital_source.system_ids | 디지털 ID | 문헌 자체 식별자용 최상위 `identifiers` 필드 추가 검토 |

---

## 8. 적용 로드맵

### Phase 10 전 (이번 세션)
- [ ] 이 보고서를 `docs/D-008_bibliography_verification.md`로 저장
- [ ] 스키마 수정은 하지 않음 (보고서만 작성)

### Phase 10 중 (새 대화창)
- [ ] P0 항목 (printing_info, publishing, extent) 스키마에 추가
- [ ] KORCIS 파서 보완 시 판식정보 매핑 로직 포함

### Phase 11+ (이후)
- [ ] P1 항목 (binding_type, abstract, provenance, identifier) 순차 추가
- [ ] 蒙求 실데이터로 전체 필드 검증

---

## 9. 참고 자료

- Dublin Core Metadata Element Set (ISO 15836): https://www.dublincore.org/specifications/dublin-core/dces/
- MARC21 Format for Bibliographic Data: https://www.loc.gov/marc/bibliographic/
- KORCIS KORMARC 고서 008 필드: https://librarian.nl.go.kr/kormarc/KSX6006-0/sub/00X_008_8.html
- NDL DC-NDL 메타데이터: https://dcpapers.dublincore.org/article/952137696
- 판식(版式) — 한국민족문화대백과사전: https://encykorea.aks.ac.kr/Contents/Item/E0059679
- 어미(魚尾) — 한국민족문화대백과사전: https://encykorea.aks.ac.kr/Article/E0080120
- 고서의 각부분 명칭 (김봉희 교수 강의): https://blog.daum.net/saramdls/10410414
