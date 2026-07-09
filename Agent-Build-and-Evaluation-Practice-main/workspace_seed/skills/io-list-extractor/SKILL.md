---
name: io-list-extractor
description: PLC I/O List(엑셀/CSV) 파일을 파싱해 태그(주소·자료형·모듈·디바이스)를 추출하고 IR(중간표현) JSON으로 정리한다. 사용자가 "I/O 리스트 정리해줘", "이 엑셀에서 태그 뽑아줘", "I/O 매핑 초안 만들어줘" 처럼 I/O List 파일을 업로드하거나 언급하며 구조화를 요청할 때 사용한다.
---

# I/O List → IR 추출

PLC 프로젝트의 I/O List(엑셀/CSV)를 업로드받아, 태그명·주소·I/O 타입(DI/DO/AI/AO)·
자료형(BOOL/INT/REAL)·모듈·디바이스·설명을 열 헤더 자동 인식으로 뽑아낸다. 결과는
`io_ir/<파일이름>.json` 에 저장되며, 이후 `plc-code-generator`, `safety-validator` 등
다른 스킬이 이 IR을 입력으로 사용한다.

## CRUD/추출은 스크립트로 한다 (중요)
엑셀/CSV 를 직접 읽고 파싱하려 하지 말고, 이 스킬에 포함된 **`manage_io_list.py`** 를
`execute` 도구로 실행한다. 헤더 자동 인식·주소 패턴 추론·중복 검사·원자적 저장을
스크립트가 담당하므로 결과가 일관되고 JSON 손상이 없다. 명령은 **workspace 디렉터리에서**
실행한다(경로는 workspace 기준 상대경로).

```bash
# 추출 (기본: io_ir/<입력파일이름>.json 에 저장)
python3 skills/io-list-extractor/manage_io_list.py extract --input "업로드된파일.xlsx"

# 시트/출력경로/프로젝트명 지정
python3 skills/io-list-extractor/manage_io_list.py extract \
  --input "IO_List.xlsx" --sheet "IO" --output "io_ir/line1.json" --project-name "Line1"

# 생성된 IR 목록
python3 skills/io-list-extractor/manage_io_list.py list

# IR 내용 확인 (검토 필요한 태그만 보기)
python3 skills/io-list-extractor/manage_io_list.py show --file io_ir/line1.json --needs-review-only

# 무결성 재검증(중복 태그명/주소, 미판별 항목)
python3 skills/io-list-extractor/manage_io_list.py validate --file io_ir/line1.json
```

## 헤더 자동 인식
다음 열 이름(한글/영문, 대소문자·공백 무관)을 인식한다. 못 찾으면 필요한 열이 비어
`needs_review=true` 로 표시된다.
- 태그명: 태그, 태그명, 심볼, Tag, Tag Name, Symbol
- 주소: 주소, 번지, Address
- I/O 타입: 구분, 유형, 입출력, IO Type — 없으면 **Siemens 주소 패턴**(I x.x→DI, Q x.x→DO,
  IW→AI, QW→AO)으로 자동 추론
- 자료형: 자료형, 데이터타입, Data Type — 없고 DI/DO 면 BOOL 로 자동 확정, AI/AO 면
  판단 불가로 검토 표시
- 모듈/디바이스/설명: 모듈, 장치, 설명 등

새로운 파일 형식에서 헤더가 위 목록에 없어 인식이 안 되면, `manage_io_list.py`의
`ALIASES` 딕셔너리에 표현을 추가하는 코드 수정이 필요하다 — 그런 경우는 사용자에게
알리고, 임시로는 헤더를 표준 이름으로 바꾼 사본을 만들어 재시도할 수 있다.

## 절차
1. 사용자가 업로드한 파일 경로 확인.
2. `extract` 실행.
3. 출력 요약(총 태그 수, 검토 필요 수, 중복 여부)을 사용자에게 보고.
4. `needs_review` 태그가 있으면 어떤 태그인지, 왜 검토가 필요한지(`review_reason`)
   요약해서 사용자에게 확인을 요청한다 — 임의로 추측해서 채우지 않는다.
5. 사용자가 "검증해줘"라고 하면 `validate` 실행.

## 주의
- IR을 생성했다고 바로 신뢰하지 않는다. `needs_review=true` 항목은 반드시 사람 확인이
  필요하다고 안내한다(안전 인터록·비상정지 관련 태그는 특히 강조).
- 원본 파일의 민감 정보(고객사명, 설비 고유번호 등)가 있다면, 외부 LLM 처리 전 마스킹이
  필요한지 사용자에게 먼저 확인한다.
- xlsx 파일은 `openpyxl` 이 필요하다. 없다면 사용자에게 `uv add openpyxl` 실행을 안내한다.
