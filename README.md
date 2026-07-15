# 결보강 관리 시스템

중·고등학교 교사용 수업 교체(결보강) 관리 웹 애플리케이션입니다.

> 다른 환경 또는 다른 개발자가 이어서 작업할 때는 먼저 [PROJECT_GUIDE.md](/Users/songjun-yeob/Documents/New%20project/PROJECT_GUIDE.md)를 확인하세요. 현재 기능 구조, 실행 방법, API, DB 테이블, 테스트, 배포 체크리스트가 상세히 정리되어 있습니다.

- 관리자: 주간 시간표 업로드/재업로드, 교사 계정 관리, 학기 일정 설정, 전체 교체 이력 조회, 확정된 교체 취소
- 교사: 로그인, 최초 비밀번호 변경, 내 주간/월간 시간표 확인, 교체 후보 탐색, 요청 전송, 수락/거절, 알림 확인
- 시간표: 표준 `주간시간표.xlsx` 양식만 허용하며, 업로드 시 구조 검증과 파싱 미리보기를 제공합니다.

## 기술 스택

- 백엔드: `FastAPI`
- DB: `SQLite`
- 인증: 서명 쿠키 기반 세션 + PBKDF2 비밀번호 해시
- 엑셀 파싱: Python 표준 라이브러리(`zipfile`, `xml`) 기반 `.xlsx` 구조 해석
- 프런트엔드: 정적 `React` UI(CDN 로드)

## 주요 기능

### 1. 시간표 업로드

- 표준 양식 다운로드 버튼 제공
- 시트명/헤더 구조 불일치 시 업로드 거부
- 병합 셀, 줄바꿈 셀 값, 순회 수업 `학교명(N시간)` 형식 지원
- 35열 범위 밖의 메모 데이터는 경고 후 무시
- 예시 교사 `홍길동` 행은 경고 후 제외
- 파싱 결과 미리보기 후 확정
- 인식 실패 셀은 관리자 화면에서 수동 보정 가능

### 2. 학사일정 전개

- 학기 시작일/종료일 설정
- 공휴일/휴업일 직접 입력
- 월별 개인 시간표와 전체 교사 시간표 생성

### 3. 수업 교체

- 같은 주, 같은 학반, 상호 공강/비순회, 기존 요청 충돌 없음 조건으로 후보 탐색
- 요청 대기 중 교시는 잠금 처리
- 수락 시 월간 시간표에 즉시 반영
- 거절/만료/취소/확정 이력 저장
- 관리자 확정 취소(되돌리기) 지원

## 실행 방법

### 1. 가상환경 및 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경 변수

```bash
cp .env.example .env
```

기본값만으로도 로컬 실행은 가능합니다. 운영 환경에서는 반드시 `SECRET_KEY`를 변경하세요.

### 3. 서버 실행

```bash
uvicorn main:app --reload
```

브라우저에서 [http://localhost:8000](http://localhost:8000) 으로 접속합니다.

## 초기 계정

- 기본 관리자: `admin / 1234`
- 교사 계정: 시간표 확정 시 자동 생성
- 교사 초기 비밀번호: `1234`
- 모든 사용자는 최초 로그인 시 비밀번호 변경이 필요합니다.

## 환경 변수

- `APP_ENV`: 실행 환경(`development`, `production`)
- `ALLOW_ORIGINS`: 허용 CORS origin
- `SECRET_KEY`: 로그인 쿠키 서명 키
- `SESSION_COOKIE_NAME`: 세션 쿠키 이름
- `SESSION_MAX_AGE_SECONDS`: 로그인 유지 시간(초)
- `DATABASE_PATH`: SQLite 파일 경로
- `PREVIEW_DIR`: 시간표 미리보기 JSON 저장 경로
- `TIMETABLE_TEMPLATE_PATH`: 표준 양식 파일 경로
- `DEFAULT_ADMIN_USERNAME`: 기본 관리자 ID
- `DEFAULT_ADMIN_PASSWORD`: 기본 관리자 초기 비밀번호
- `DEFAULT_TEACHER_PASSWORD`: 교사 초기 비밀번호
- `PORT`: 실행 포트

## 테스트

```bash
python -m unittest tests/test_app.py
```

현재 테스트 범위:

- 기본 로그인 및 최초 비밀번호 변경
- 실제 `.xlsx` 시간표 파일 미리보기 파싱
- 교체 후보 탐색 조건
- 대기 요청에 의한 중복 잠금
- 수락 후 월간 반영 및 관리자 취소

## Docker

### Docker build/run

```bash
docker build -t class-swap-app .
docker run --rm -p 8000:8000 -v class-swap-data:/app/data class-swap-app
```

### Docker Compose

```bash
docker compose up --build
```
