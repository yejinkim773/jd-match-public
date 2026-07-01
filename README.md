# FitCheck

이력서 X 채용공고 항목별 적합도 분석

## 주요 기능

- **JD 자동 수집** — URL 입력 시 채용공고 텍스트 자동 크롤링 (잡코리아, 사람인, ninehire 등 지원)
- **이미지형 JD 지원** — 이미지 캡처 업로드 시 AI가 텍스트 자동 추출
- **AI 매칭 분석** — 필수요건·우대사항 항목별 충족 여부, 매칭 스코어(0~100점), 보완 팁 제공
- **공고 관리** — 분석 결과를 Google Sheets에 저장, 지원 여부 체크, 마감 임박 알림
- **구글 캘린더 연동** — 마감일 원클릭 캘린더 등록

## 기술 스택

| 역할 | 사용 기술 |
|---|---|
| 프론트엔드 | Streamlit |
| AI 분석 | Google Gemini API (gemini-2.5-flash) |
| 데이터 저장 | Google Sheets API (gspread) |
| 크롤링 | requests, BeautifulSoup |
| PDF 파싱 | pdfplumber |

## 실행 방법

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. 시크릿 설정

`.streamlit/secrets.toml.example`을 복사해 `.streamlit/secrets.toml`로 이름 바꾼 뒤 값을 채워주세요.

```toml
GOOGLE_API_KEY = "Gemini API 키"
SPREADSHEET_ID = "Google Sheets ID"

[gcp_service_account]
# Google Cloud 서비스 계정 JSON 내용
```

- **Gemini API 키** — [Google AI Studio](https://aistudio.google.com/apikey)에서 발급
- **서비스 계정** — Google Cloud Console에서 발급 후 Sheets 편집 권한 부여

### 3. 실행

```bash
streamlit run app.py
```

## 화면 구성

| 탭 | 기능 |
|---|---|
| 내 이력서 | PDF 업로드 또는 직접 입력으로 이력서 등록 |
| JD 분석 | URL·텍스트·이미지로 채용공고 입력 후 AI 분석 |
| 내 공고 목록 | 저장된 공고 목록, 지원 여부 체크, 마감 알림 |
| 설정 | 알림 기준 스코어·D-day 설정 |
