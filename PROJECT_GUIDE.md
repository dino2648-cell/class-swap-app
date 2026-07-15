# 결보강 관리 시스템 프로젝트 설명서

이 문서는 다른 PC, 다른 개발자, 또는 배포 환경에서 현재 프로젝트를 이어서 작업할 수 있도록 만든 인수인계용 설명서입니다.

프로젝트 루트 경로:

```text
/Users/songjun-yeob/Documents/New project
```

로컬 실행 주소:

```text
http://127.0.0.1:8000/
```

주의: `frontend/index.html`을 `file://`로 직접 열면 API 요청, 쿠키 로그인, 다운로드 기능이 정상 동작하지 않을 수 있습니다. 반드시 FastAPI 서버를 띄운 뒤 `http://127.0.0.1:8000/` 또는 배포 도메인으로 접속해야 합니다.

## 1. 서비스 개요

경북소프트웨어마이스터고등학교 교사를 위한 수업 교체, 보강, 결보강 계획서 작성, 주간 반영본 다운로드, 관리자 운영 도구를 제공하는 웹 애플리케이션입니다.

핵심 목표:

- 학기 시간표 엑셀 업로드 후 교사별 주간 시간표 자동 구축
- 학사일정에 따라 실제 날짜별 시간표 전개
- 교사 간 수업 맞교환 신청 및 수락
- 보강 담당 교사 탐색 및 요청
- 행사 등으로 여러 교사가 장기간 부재할 때 일괄 보강 계획 생성
- 관리자 계정/시간표/학사일정/이력/수당/영향도 관리
- 결보강 계획서 및 주간 전체 시간표 반영본 다운로드

## 2. 기술 스택

- Backend: Python, FastAPI
- ASGI Server: Uvicorn
- Database: SQLite
- Frontend: 정적 React 앱, Babel standalone, CDN React
- Styling: CSS 단일 파일
- Auth: 서명 쿠키 기반 세션
- Password Hash: PBKDF2 기반 해시
- Excel Parsing: Python 표준 라이브러리 `zipfile`, `xml`
- Excel/PDF Export: 자체 XML/XLSX 생성, 자체 PDF 스트림 생성
- Tests: Python `unittest`, FastAPI `TestClient`

중요한 제약:

- 현재 프런트엔드는 빌드 도구 없이 CDN React와 Babel로 동작합니다.
- 운영망에서 외부 CDN 접근이 차단될 가능성이 있으면 React/Babel 파일을 로컬 정적 파일로 내려받거나 Vite/Next.js 등으로 번들링 구조를 바꾸는 것이 좋습니다.
- DB는 SQLite 단일 파일입니다. 동시 접속이 매우 많아질 경우 PostgreSQL 전환을 검토해야 합니다.

## 3. 폴더 구조

```text
.
├── app/
│   ├── config.py              # 환경변수 및 설정
│   ├── db.py                  # SQLite 스키마, DB 초기화
│   ├── excel_parser.py        # 시간표 엑셀 파싱 및 표준 양식 검증
│   ├── plan_export.py         # 결보강 계획서/주간 전체 시간표 엑셀/PDF 생성
│   ├── schemas.py             # API 요청 Pydantic 모델
│   ├── schedule_service.py    # 핵심 업무 로직
│   ├── security.py            # 비밀번호 해시/검증
│   └── server.py              # FastAPI 앱, API 라우트
├── frontend/
│   ├── index.html             # 정적 앱 진입점
│   ├── app.js                 # React 전체 UI
│   ├── styles.css             # 전체 스타일
│   └── assets/                # 로고, 배너 이미지
├── tests/
│   ├── test_app.py            # 주요 기능 통합 테스트
│   └── fixtures/              # 테스트용 시간표 엑셀
├── data/
│   ├── class_swap.db          # 로컬 SQLite DB
│   ├── import_previews/       # 시간표 업로드 미리보기 JSON
│   └── templates/             # 표준 시간표 양식 위치
├── main.py                    # FastAPI 앱 실행 진입점
├── requirements.txt           # Python 의존성
├── Dockerfile                 # Docker 배포용
├── docker-compose.yml         # Docker Compose 배포용
├── Makefile                   # 개발 편의 명령
├── README.md                  # 간단 소개 문서
└── PROJECT_GUIDE.md           # 현재 문서
```

참고:

- 예전에 `app/services/`(임용고시 문제생성기 관련 코드), `main.cpp`(무관한 스크래치 파일), `streamlit_gemini/`(별도의 Gemini 기반 임용고시 앱)가 이 폴더에 함께 섞여 있었으나, 결보강 관리 시스템과 무관하여 모두 정리했습니다.
  - `app/services/`와 `streamlit_gemini/` → `/Users/songjun-yeob/Documents/streamlit_gemini/` (기존 `streamlit_gemini`는 그대로, `app/services`는 그 안에 `legacy_api_services/`로 보존)
  - `main.cpp` → `/Users/songjun-yeob/Documents/cpp-scratch/main.cpp`
  - 정리 후 `py_compile`, 전체 테스트(24개), 서버 기동까지 재검증 완료.

## 4. 로컬 실행 방법

### 4.1 가상환경 생성

```bash
cd "/Users/songjun-yeob/Documents/New project"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4.2 서버 실행

개발 중 현재 사용한 포트는 `8000`입니다.

```bash
cd "/Users/songjun-yeob/Documents/New project"
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

브라우저 접속:

```text
http://127.0.0.1:8000/
```

헬스 체크:

```bash
curl -s http://127.0.0.1:8000/api/health
```

정상 예시:

```json
{
  "status": "ok",
  "environment": "development",
  "teacher_count": 39,
  "pending_swap_count": 0,
  "default_admin_username": "admin"
}
```

## 5. 환경변수

환경변수는 `app/config.py`에서 읽습니다. `.env.example`을 기준으로 운영환경에 맞게 설정합니다.

```text
APP_ENV=production
ALLOW_ORIGINS=http://localhost:8000
SECRET_KEY=change-this-secret-key
SESSION_COOKIE_NAME=school-swap-session
SESSION_MAX_AGE_SECONDS=1209600
DATABASE_PATH=/app/data/class_swap.db
PREVIEW_DIR=/app/data/import_previews
TIMETABLE_TEMPLATE_PATH=/app/data/templates/주간시간표_표준양식.xlsx
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=1234
DEFAULT_TEACHER_PASSWORD=1234
PORT=8000
```

운영 배포 시 반드시 바꿔야 하는 값:

- `SECRET_KEY`: 예측 불가능한 긴 문자열로 변경
- `DEFAULT_ADMIN_PASSWORD`: 초기 관리자 비밀번호 변경
- `ALLOW_ORIGINS`: 실제 서비스 도메인으로 변경
- `DATABASE_PATH`: 영속 볼륨 또는 백업 가능한 경로 지정
- `TIMETABLE_TEMPLATE_PATH`: 표준 시간표 양식 파일이 실제 존재하는 경로 지정

## 6. 초기 계정과 인증

초기 관리자:

```text
ID: admin
PW: 1234
```

실제 운영 전 조치:

- 최초 로그인 후 관리자 비밀번호 변경
- `.env`의 기본 비밀번호 노출 최소화
- 교사 초기 비밀번호 정책을 학교 운영 방식에 맞게 조정

인증 방식:

- `/api/auth/login`에서 ID/PW 검증
- 서버가 서명 쿠키 발급
- 쿠키명은 `SESSION_COOKIE_NAME`
- 비밀번호는 평문 저장하지 않음
- `security.py`에서 PBKDF2 해시 생성/검증

## 7. DB 구조

스키마 위치:

```text
app/db.py
```

주요 테이블:

### teachers

교사 및 관리자 계정.

주요 컬럼:

- `username`: 로그인 ID
- `display_name`: 화면 표시 이름
- `schedule_label`: 시간표 엑셀에서 매칭할 이름
- `role`: `admin` 또는 `teacher`
- `password_hash`: 해시된 비밀번호
- `must_change_password`: 최초 비밀번호 변경 필요 여부
- `is_active`: 활성 여부

### timetable_slots

주간 기준 시간표.

주요 컬럼:

- `teacher_id`
- `weekday`: 월=0, 화=1, 수=2, 목=3, 금=4
- `period`: 1~7
- `slot_type`: `class` 또는 `travel`
- `class_code`: 학반
- `subject`: 과목
- `location_label`: 순회 장소
- `source_text`: 엑셀 원문

### calendar_days

학사일정.

주요 컬럼:

- `date`
- `weekday`
- `is_school_day`
- `kind`
- `label`

### swap_requests

수업 교체 요청.

주요 컬럼:

- `requester_id`: 교체 요청자
- `responder_id`: 상대 교사
- `source_date`, `source_period`: 요청자가 원래 안 하게 될 수업
- `target_date`, `target_period`: 상대 교사의 교체 대상 수업
- `source_class_code`, `source_subject`
- `target_class_code`, `target_subject`
- `status`: `pending`, `accepted`, `rejected`, `expired`, `cancelled`
- `expires_at`
- `requester_hidden`, `responder_hidden`: 확인 후 숨김 처리

### coverage_requests

보강 요청.

주요 컬럼:

- `requester_id`: 원 수업 담당 교사
- `responder_id`: 보강 담당 교사
- `class_date`
- `period`
- `class_code`
- `subject`
- `status`
- `expires_at`
- `requester_hidden`, `responder_hidden`

### swap_history

교체 이력 기록.

### notifications

알림.

### app_settings

학기 시작일, 종료일 등 설정값.

## 8. 주요 기능과 로직 위치

핵심 업무 로직 대부분은 `app/schedule_service.py`에 있습니다.

### 8.1 시간표 업로드 및 파싱

관련 파일:

- `app/excel_parser.py`
- `app/server.py`
- `frontend/app.js`

API:

- `GET /api/template`
- `POST /api/admin/timetable/preview`
- `GET /api/admin/timetable/previews/{preview_id}`
- `POST /api/admin/timetable/confirm`

파싱 규칙:

- 시트명: `주간시간표`
- 월~목 1~7교시, 금 1~6교시
- 교사 열 포함 총 35열
- 수업 셀: `학반 과목`, 예: `203 자구B`, `중1 국어`
- 순회 셀: `학교명(N시간)`
- 예시 교사 `홍길동`은 경고 후 제외
- 표준 구조 불일치 시 업로드 거부

재업로드 시 계정 처리:

- 새 시간표에 새 교사가 있으면 계정 생성
- 기존 교사가 빠지면 관리자 화면에서 유지/비활성/삭제 선택 가능
- 기간제, 전입, 전출 교사 처리에 중요하므로 업로드 확정 전에 미리보기의 교사 동기화 정보를 확인해야 함

### 8.2 학사일정

API:

- `GET /api/admin/calendar-settings`
- `PUT /api/admin/calendar-settings`

기능:

- 학기 시작일/종료일 설정
- 공휴일/휴업일 등록
- 후보 탐색과 시간표 반영에서 수업일 여부 검사

### 8.3 개인 주간 시간표

API:

- `GET /api/schedule/weekly?date=YYYY-MM-DD`
- `GET /api/schedule/day?target_date=YYYY-MM-DD`
- `GET /api/schedule/monthly?month=YYYY-MM`

상태값:

- `class`: 원래 수업
- `free`: 공강
- `travel`: 순회
- `holiday`: 휴업일
- `swapped-in`: 교체로 들어온 수업
- `swapped-out`: 교체로 안 하게 된 수업
- `coverage-in`: 보강으로 맡게 된 수업
- `coverage-out`: 보강 배정으로 원 담당자가 안 하게 된 수업
- `coverage-pending-in/out`: 대기 중인 보강
- `locked`: 교체/보강 요청으로 잠긴 수업

### 8.4 수업 교체 신청

API:

- `GET /api/swaps/candidates?date=YYYY-MM-DD&period=N&week_offset=0|1`
- `POST /api/swaps/requests`
- `GET /api/swaps/requests`
- `POST /api/swaps/requests/{id}/accept`
- `POST /api/swaps/requests/{id}/reject`
- `POST /api/swaps/requests/{id}/cancel`
- `POST /api/swaps/requests/{id}/dismiss`

후보 탐색 조건:

- 요청자 본인의 수업이어야 함
- 이미 확정 교체된 수업은 다시 교체 불가
- 같은 학반 기준
- 이번 주/다음 주 후보 탭으로 나누어 조회
- 상대 교사가 요청자의 원수업 시간에 비어 있어야 함
- 요청자가 상대 교사의 수업 시간에 비어 있어야 함
- 순회, 공휴일, 휴업일 제외
- 기존 대기/확정 요청과 충돌하면 제외

수락 시 재검증:

- 교체 요청은 수락 시점에 다시 공휴일/충돌/공강 여부를 검사함
- 학사일정 변경 또는 시간표 재업로드 후 잘못 확정되는 것을 방지

계획서 표시 기준:

- 교체 요청 1건은 주간 결보강 내역에서 요청자 원수업 기준 1행만 표시
- 상대 교사 항목은 중복 표시하지 않음

### 8.5 보강 신청

API:

- `GET /api/coverage/sources?date=YYYY-MM-DD`
- `GET /api/coverage/candidates?date=YYYY-MM-DD&period=N&week_offset=0|1`
- `POST /api/coverage/requests`
- `GET /api/coverage/requests`
- `POST /api/coverage/requests/{id}/accept`
- `POST /api/coverage/requests/{id}/reject`
- `POST /api/coverage/requests/{id}/cancel`
- `POST /api/coverage/requests/{id}/dismiss`

후보 탐색 조건:

- 보강 대상은 본인의 원 수업 중 선택
- 이번 주/다음 주 후보 탭으로 조회
- 보강 대상 수업과 같은 요일/교시 기준으로 가능한 교사 조회
- 해당 교사가 그 날짜 그 교시에 수업/순회/대기 요청이 없어야 함
- 후보 목록에 해당 날짜의 수업 개수와 바쁜 정도 표시

### 8.6 행사 보강

별도 상단 메뉴:

```text
행사 보강
```

관리자 하위탭이 아니라 독립 메뉴입니다.

API:

- `POST /api/admin/event-coverage/preview`
- `POST /api/admin/event-coverage/requests`

기능:

- 행사명 입력
- 시작일/종료일 입력
- 여러 부재 교사 선택
- 기간 내 해당 교사들의 수업 목록 자동 조회
- 부재 교사끼리는 보강 후보에서 제외
- 가능한 교사를 수업별로 선택
- 선택한 보강 요청을 일괄 발송

현재 정책:

- 일괄 생성은 `pending` 보강 요청을 만드는 방식
- 상대 교사가 수락해야 최종 확정
- 관리자 강제 확정 배정 기능은 아직 없음

추가 개선 후보:

- 긴급 행사에는 관리자 직접 확정 모드 추가
- 보강 후보 자동 배정 최적화
- 특정 교사의 하루 최대 보강 수 제한
- 행사별 요청 묶음 ID 저장

### 8.7 결보강 계획서

API:

- `GET /api/plans/weekly?date=YYYY-MM-DD`
- `GET /api/plans/weekly/download?date=YYYY-MM-DD`
- `GET /api/plans/weekly/download.pdf?date=YYYY-MM-DD`

기능:

- 주간 단위 결보강 내역 조회
- 관리자: 전체 교사 내역
- 일반 교사: 본인 관련 내역만
- 엑셀 다운로드
- PDF 다운로드
- 교체로 원 담당자가 수업하지 않게 된 수업은 PDF에서 빨간 계열로 표시

주의:

- `결보강계획서`와 `주간전체시간표_반영본`은 다른 파일입니다.
- 계획서 PDF는 요약 내역 표입니다.
- 주간 전체 시간표 반영본은 교사별 전체 시간표 엑셀입니다.

### 8.8 주간 전체 시간표 반영본

API:

- `GET /api/admin/schedule/weekly/download?date=YYYY-MM-DD`

기능:

- 한 주 전체 교사의 반영 시간표를 엑셀로 다운로드
- `교체`: 새로 들어온 수업
- `교체됨`: 교체로 안 하게 된 수업
- `보강`: 보강으로 맡게 된 수업
- `보강 배정`: 원 담당자가 보강 배정으로 안 하게 된 수업

색상 정책:

- 일반 수업: 연한 녹색 계열
- 공강: 회색 계열
- 순회/휴업: 별도 색상
- 교체로 들어온 수업: 파란 계열
- 교체로 안 하게 된 수업: 빨간 계열
- 보강 관련: 주황 계열

관련 코드:

- `app/plan_export.py`
- `_slot_label`
- `_slot_style`
- `build_school_weekly_timetable_xlsx`

### 8.9 관리자 회원/교사 관리

API:

- `GET /api/admin/teachers`
- `POST /api/admin/teachers`
- `PUT /api/admin/teachers/{id}`
- `POST /api/admin/teachers/{id}/reset-password`
- `DELETE /api/admin/teachers/{id}`

기능:

- 계정 생성
- 이름/ID/권한/시간표 매칭명 수정
- 비밀번호 초기화
- 계정 삭제
- 시간표 업로드 시 교사 목록 동기화

### 8.10 관리자 시간표 직접 관리

API:

- `GET /api/admin/timetable/slots`
- `POST /api/admin/timetable/slots`
- `PUT /api/admin/timetable/slots/{id}`
- `DELETE /api/admin/timetable/slots/{id}`

기능:

- 교사별 요일/교시 수업 조회
- 수업 추가
- 수업 수정
- 수업 삭제
- 순회 일정 관리

주의:

- 이미 확정된 교체/보강이 있는 상태에서 원 시간표를 직접 수정하면 영향도 검사를 실행해야 함

### 8.11 관리자 교체/보강 이력

API:

- `GET /api/admin/swaps`
- `POST /api/admin/swaps/{id}/cancel`
- `DELETE /api/admin/swaps/{id}`
- `POST /api/admin/coverage/{id}/cancel`
- `DELETE /api/admin/coverage/{id}`

기능:

- 교체/보강 전체 이력 조회
- 필터: 교사명, 학반, 날짜, 유형, 상태
- 확정 교체/보강 취소
- 이력 삭제
- 현재 반영 중인 교체/보강 목록을 필터/그룹/한 줄 리스트로 조회

### 8.12 월별 보강 수당

API:

- `GET /api/admin/coverage-allowances?month=YYYY-MM&rate=금액`

기능:

- 월별 확정 보강 건수 집계
- 교사별 보강 수당 산출
- 보강 단가 입력
- 교사별 세부 내역 확인
- CSV 다운로드

현재 정책:

- `accepted` 보강 요청만 산정
- 교체는 수당 계산에 포함하지 않음

### 8.13 영향도 검사

API:

- `GET /api/admin/impact-check`

기능:

- 확정 교체/보강과 현재 시간표/학사일정의 충돌 검사
- 교사 비활성/삭제 여부 검사
- 수업일 여부 검사
- 해당 시각 공강 여부 검사
- 시간표 재업로드 후 운영 사고 방지

추천 운영 절차:

1. 시간표 재업로드
2. 학사일정 변경
3. 영향도 검사 실행
4. 오류 또는 경고 확인
5. 필요한 교체/보강 취소 또는 시간표 수정

### 8.14 시스템 점검

API:

- `GET /api/admin/debug/schedule?teacher_id=ID&date=YYYY-MM-DD&period=N`

기능:

- 특정 교사/날짜/교시의 현재 상태 분석
- 교체 후보 가능 여부 확인
- 보강 후보 가능 여부 확인
- 충돌 잠금 상태 확인

후보 조회가 이상할 때 가장 먼저 확인할 디버깅 도구입니다.

## 9. 프런트엔드 구조

프런트 전체 로직:

```text
frontend/app.js
```

주요 컴포넌트:

- `App`: 전체 앱 상태, 로그인, 탭 전환, 데이터 로딩
- `WeeklyGrid`: 개인 주간 시간표
- `PlanPanel`: 결보강 계획서 작성/다운로드
- `EventCoveragePanel`: 행사 보강
- `AdminPanel`: 관리자 기능 묶음
- `AdminActiveSwapsPanel`: 현재 반영 중인 교체/보강 목록
- `AdminAllowancePanel`: 월별 보강 수당

스타일:

```text
frontend/styles.css
```

정적 자산:

```text
frontend/assets/
```

캐시 무효화:

`frontend/index.html`에서 `app.js`와 `styles.css`에 `?v=...` 버전 쿼리가 붙어 있습니다. 프런트 파일 변경 후 브라우저 캐시가 남으면 버전 문자열을 바꾸면 됩니다.

```html
<link rel="stylesheet" href="/static/styles.css?v=event-coverage-20260714" />
<script type="text/babel" src="/static/app.js?v=event-coverage-20260714"></script>
```

## 10. 주요 API 요약

### 인증

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/me`
- `POST /api/auth/change-password`

### 시간표 조회

- `GET /api/schedule/weekly`
- `GET /api/schedule/day`
- `GET /api/schedule/monthly`
- `GET /api/school/monthly`

### 교체

- `GET /api/swaps/candidates`
- `GET /api/swaps/requests`
- `POST /api/swaps/requests`
- `POST /api/swaps/requests/{id}/accept`
- `POST /api/swaps/requests/{id}/reject`
- `POST /api/swaps/requests/{id}/cancel`
- `POST /api/swaps/requests/{id}/dismiss`

### 보강

- `GET /api/coverage/sources`
- `GET /api/coverage/candidates`
- `GET /api/coverage/available`
- `GET /api/coverage/requests`
- `POST /api/coverage/requests`
- `POST /api/coverage/requests/{id}/accept`
- `POST /api/coverage/requests/{id}/reject`
- `POST /api/coverage/requests/{id}/cancel`
- `POST /api/coverage/requests/{id}/dismiss`

### 알림

- `GET /api/notifications`
- `POST /api/notifications/read`
- `POST /api/notifications/delete`

### 계획서/다운로드

- `GET /api/plans/weekly`
- `GET /api/plans/weekly/download`
- `GET /api/plans/weekly/download.pdf`
- `GET /api/admin/schedule/weekly/download`

### 관리자

- `GET /api/admin/calendar-settings`
- `PUT /api/admin/calendar-settings`
- `GET /api/admin/teachers`
- `POST /api/admin/teachers`
- `PUT /api/admin/teachers/{id}`
- `POST /api/admin/teachers/{id}/reset-password`
- `DELETE /api/admin/teachers/{id}`
- `POST /api/admin/timetable/preview`
- `POST /api/admin/timetable/confirm`
- `GET /api/admin/timetable/slots`
- `POST /api/admin/timetable/slots`
- `PUT /api/admin/timetable/slots/{id}`
- `DELETE /api/admin/timetable/slots/{id}`
- `GET /api/admin/swaps`
- `GET /api/admin/impact-check`
- `GET /api/admin/debug/schedule`
- `GET /api/admin/coverage-allowances`
- `POST /api/admin/event-coverage/preview`
- `POST /api/admin/event-coverage/requests`
- `POST /api/admin/swaps/{id}/cancel`
- `DELETE /api/admin/swaps/{id}`
- `POST /api/admin/coverage/{id}/cancel`
- `DELETE /api/admin/coverage/{id}`

## 11. 테스트

실행:

```bash
cd "/Users/songjun-yeob/Documents/New project"
PYTHONPYCACHEPREFIX=/private/tmp/codex-pyc .venv/bin/python -m unittest tests/test_app.py
```

컴파일 확인:

```bash
cd "/Users/songjun-yeob/Documents/New project"
PYTHONPYCACHEPREFIX=/private/tmp/codex-pyc .venv/bin/python -m py_compile app/db.py app/server.py app/schedule_service.py app/excel_parser.py app/plan_export.py app/schemas.py app/security.py
```

현재 테스트 범위:

- 로그인 및 최초 비밀번호 변경
- 실제 시간표 엑셀 파싱
- 시간표 업로드 미리보기/확정
- 교체 후보 탐색
- 보강 후보 탐색
- 이번 주/다음 주 후보 분리
- 요청/수락/거절/취소/숨김
- 보강 수락 후 주간 시간표 반영
- 교체 수락 후 주간/월간 시간표 반영
- 이미 교체된 수업 재교체 차단
- 교체 수락 시점 재검증
- 관리자 취소/삭제
- 주간 계획서 교체 중복 제거
- 계획서 PDF 색상 표시
- 주간 전체 시간표 반영본 엑셀 색상 표시
- 행사 보강 미리보기/일괄 요청
- 보강 수당 산출
- 영향도 검사
- 시스템 디버그 API

최근 확인 결과:

```text
Ran 24 tests
OK
```

## 12. Docker 실행

빌드:

```bash
docker build -t class-swap-app .
```

실행:

```bash
docker run --rm -p 8000:8000 --env-file .env -v class-swap-data:/app/data class-swap-app
```

Docker Compose:

```bash
docker compose up --build
```

주의:

- Dockerfile은 `/app/data`를 데이터 경로로 사용합니다.
- SQLite DB와 표준 양식 파일은 볼륨에 있어야 컨테이너 재시작 후 유지됩니다.
- `TIMETABLE_TEMPLATE_PATH=/app/data/templates/주간시간표_표준양식.xlsx` 경로에 양식 파일이 있어야 표준 양식 다운로드가 동작합니다.

## 13. AWS 배포 체크리스트

담당자에게 요청할 항목:

- 서비스 도메인
- HTTPS 인증서
- 서버 실행 환경: EC2, ECS, Elastic Beanstalk, Lightsail 중 선택
- Python 3.13 또는 Docker 실행 가능 환경
- 영속 스토리지: SQLite 파일 저장용 EBS/EFS 또는 컨테이너 볼륨
- 백업 정책: DB 파일 정기 백업
- 보안 그룹: 80/443만 외부 공개, 내부 포트 제한
- 환경변수 주입 방식
- 학교 내부망 접속 정책
- 로그 보관 정책
- 장애 시 재시작 정책

운영 권장:

- `APP_ENV=production`
- `SECRET_KEY` 변경
- `DEFAULT_ADMIN_PASSWORD` 변경
- `ALLOW_ORIGINS=https://실제도메인`
- HTTPS 필수
- DB 파일 매일 백업
- 업로드된 미리보기 파일 정기 정리

SQLite 운영 주의:

- 소규모 학교 내부 업무에는 충분히 단순하고 관리가 쉽습니다.
- 다수 동시 접속, 여러 관리자 동시 수정, 장기 운영 통계가 많아지면 PostgreSQL로 전환하는 것이 안전합니다.

## 14. 운영 시나리오

### 학기 시작 전

1. 관리자 로그인
2. 학기 시작일/종료일 설정
3. 공휴일/휴업일 입력
4. 표준 시간표 양식 다운로드
5. 주간 시간표 업로드
6. 파싱 미리보기 확인
7. 인식 실패 셀 수정
8. 빠진 교사 처리 방식 선택
9. 시간표 확정
10. 교사 계정 확인
11. 영향도 검사 실행

### 일반 교체

1. 교사가 로그인
2. 교체 신청 탭 이동
3. 내 수업 선택
4. 이번 주/다음 주 후보 확인
5. 후보 선택 후 요청
6. 상대 교사가 수락
7. 주간 시간표와 계획서에 반영

### 일반 보강

1. 교사가 보강 신청 탭 이동
2. 보강 대상 내 수업 선택
3. 이번 주/다음 주 가능한 교사 확인
4. 후보 교사 선택 후 요청
5. 상대 교사가 수락
6. 보강 수업으로 표시
7. 월별 보강 수당 산출에 포함

### 행사 보강

1. 관리자가 행사 보강 탭 이동
2. 행사명 입력
3. 시작일/종료일 입력
4. 부재 교사 여러 명 선택
5. 계획 생성
6. 수업별 보강 교사 선택
7. 선택 요청 일괄 전송
8. 상대 교사 수락 후 확정

### 계획서 작성

1. 계획서 작성 탭 이동
2. 기준 날짜 선택
3. 해당 주 결보강 내역 확인
4. 엑셀 또는 PDF 다운로드
5. 필요 시 주간 전체 시간표 반영본 다운로드

## 15. 디자인/UX 정책

현재 디자인 방향:

- 메인 톤: 학교 로고 계열의 차분한 초록
- 강조 색상은 기능별로 분리
- 교체로 들어온 수업: 파랑
- 교체로 안 하게 된 수업: 빨강
- 보강: 주황
- 일반 수업: 연한 녹색
- 공강: 회색

관리자 화면 구조:

- 상단 독립 메뉴: 관리자, 행사 보강, 계획서 작성
- 관리자 내부 하위탭: 매뉴얼, 시간표 업로드, 시간표 직접 관리, 회원/교사 관리, 학사일정, 시스템 점검, 영향도 검사, 월별 보강 수당, 교체/보강 이력

## 16. 자주 발생한 이슈와 해결법

### 16.1 `file:///.../frontend/index.html`에서 기능이 이상함

원인:

- 서버 API가 아닌 로컬 파일로 앱을 열었기 때문
- 쿠키, API 경로, 다운로드가 꼬일 수 있음

해결:

```text
http://127.0.0.1:8000/
```

으로 접속.

### 16.2 서버가 안 열림

확인:

```bash
curl -s http://127.0.0.1:8000/api/health
```

재실행:

```bash
cd "/Users/songjun-yeob/Documents/New project"
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

### 16.3 새 프런트 변경이 안 보임

해결:

- 브라우저 강력 새로고침
- `frontend/index.html`의 `?v=...` 버전 변경

### 16.4 시간표 업로드 후 교사가 이상함

확인:

- 미리보기의 교사 동기화 정보
- `schedule_label`
- 동명이인 접미어
- 빠진 교사 처리 방식

### 16.5 교체 후보가 안 나옴

확인:

- 같은 학반인지
- 이번 주/다음 주 탭이 맞는지
- 상대 교사가 해당 시간에 공강인지
- 요청자도 상대 수업 시간에 공강인지
- 순회/공휴일/휴업일 여부
- 이미 대기 또는 확정 요청이 있는지
- 관리자 시스템 점검 API 사용

### 16.6 보강 후보가 적게 나옴

확인:

- 선택한 보강 대상 수업이 맞는지
- 이번 주/다음 주 탭이 맞는지
- 같은 요일/교시 기준인지
- 후보 교사가 해당 시각 수업/순회/요청 충돌이 없는지
- 행사 보강에서는 선택된 부재 교사가 후보에서 제외됨

### 16.7 다운로드 파일 색상이 기대와 다름

구분:

- 계획서 PDF: `결보강계획서_...pdf`
- 주간 전체 시간표 엑셀: `주간전체시간표_반영본_...xlsx`

주의:

- 이미 내려받은 파일은 바뀌지 않습니다.
- 서버 재시작 후 새로 다운로드해야 최신 스타일이 적용됩니다.

## 17. 현재 알려진 개선 후보

기능 개선:

- 관리자 행사 보강에서 직접 확정 모드 추가
- 행사별 묶음 ID 저장
- 보강 자동 배정 최적화
- 교사별 하루/주간 보강 최대 횟수 제한
- 계획서 HWP 양식 직접 출력
- PDF 레이아웃 고도화
- 교체/보강 내역 엑셀 다중 시트 출력
- 알림 실시간 업데이트

기술 개선:

- React CDN 제거 후 Vite 번들링
- SQLite에서 PostgreSQL 전환 옵션
- Alembic 같은 DB 마이그레이션 도구 도입
- 서버 로그 파일 저장
- 관리자 작업 감사 로그 강화
- 테스트 DB fixture 정리
- API 문서용 OpenAPI 설명 강화

보안 개선:

- 운영 기본 비밀번호 화면 노출 금지
- HTTPS 필수
- 쿠키 `secure=True` 운영 적용
- 관리자 2차 인증 검토
- 비밀번호 정책 강화
- 계정 잠금 정책 추가

## 18. 작업 시 권장 순서

새 기능을 추가할 때:

1. `app/schemas.py`에 요청/응답 모델 추가
2. `app/schedule_service.py`에 업무 로직 추가
3. `app/server.py`에 API 라우트 연결
4. `frontend/app.js`에 UI/상태 추가
5. `frontend/styles.css`에 스타일 추가
6. `tests/test_app.py`에 회귀 테스트 추가
7. `py_compile` 실행
8. 전체 테스트 실행
9. 서버 재시작
10. `http://127.0.0.1:8000/`에서 브라우저 확인

백엔드 검증 명령:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-pyc .venv/bin/python -m py_compile app/db.py app/server.py app/schedule_service.py app/excel_parser.py app/plan_export.py app/schemas.py app/security.py
```

전체 테스트:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-pyc .venv/bin/python -m unittest tests/test_app.py
```

## 19. 인수인계 핵심 요약

- 실제 앱은 `main.py`의 `create_app()`으로 실행됩니다.
- API 라우트는 `app/server.py`에 있습니다.
- 기능 로직은 대부분 `app/schedule_service.py`에 있습니다.
- 시간표 엑셀 파싱은 `app/excel_parser.py`입니다.
- 계획서/엑셀/PDF 다운로드 생성은 `app/plan_export.py`입니다.
- 화면은 `frontend/app.js`, 디자인은 `frontend/styles.css`입니다.
- DB는 기본적으로 `data/class_swap.db`입니다.
- 로컬 테스트 접속은 `http://127.0.0.1:8000/`입니다.
- `file://`로 열지 마세요.
- 변경 후에는 테스트와 서버 재시작이 필요합니다.

