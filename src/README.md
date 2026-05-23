# 🎙️ Pluiz V2 — 음성 기반 지능형 PC 제어 에이전트

음성 또는 텍스트 명령 하나로 PC 작업을 자동화하는 AI 에이전트입니다.

---

## ✅ 시작 전 필수 설치

### 1. Ollama 설치
[https://ollama.com](https://ollama.com) 에서 다운로드 후 설치

설치 후 터미널에서 llama3 다운로드 (약 4~5GB, 시간 소요):
```bash
ollama pull llama3
```

설치 확인:
```bash
ollama list
```
llama3가 목록에 있으면 완료

---

### 2. Python 환경 설정

Python 3.10 권장 (Anaconda 사용 시):
```bash
conda create -n venv_pluiz python=3.10 -y
conda activate venv_pluiz
```

---

### 3. 라이브러리 설치

```bash
pip install -r requirements.txt
```

> ⚠️ PyAudio 설치 실패 시:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

---

### 4. Chrome 설치
selenium이 Chrome을 제어하므로 반드시 Chrome이 설치되어 있어야 합니다.
[https://www.google.com/chrome](https://www.google.com/chrome)

---

### 5. Gemini API 키 설정

[https://aistudio.google.com](https://aistudio.google.com) 에서 API 키 발급 후:

`config/settings.py` 파일 열어서 아래 부분에 본인 키 입력:
```python
GEMINI_API_KEY = "여기에_본인_키_입력"
```

> 💡 API 키는 팀원 각자 발급받아 사용하세요. 공유 시 한도 초과 문제 발생합니다.

---

## 🚀 실행 방법

### 실행 전 확인사항

1. Ollama가 백그라운드에서 실행 중인지 확인
   - 작업관리자에서 `ollama.exe` 프로세스 있는지 확인
   - 없으면 Ollama 앱 실행

2. 가상환경 활성화 확인
```bash
conda activate venv_pluiz
```

### 실행

```bash
python app/main.py
```

---

## 🎮 사용 방법

실행 후 입력 방식 선택:
- `1` : 음성 입력 (마이크로 말하기)
- `2` : 텍스트 입력 (키보드로 입력)
- `quit` : 종료

### 명령 예시

**앱 실행/종료**
```
메모장 열어줘
크롬 켜줘
계산기 닫아줘
```

**웹 제어**
```
유튜브에서 아이유 검색해줘
네이버에서 날씨 검색해줘
강남역에서 홍대까지 경로 찾아줘
```

**파일/시스템**
```
바탕화면에 메모.txt 만들어줘
다운로드 폴더에서 pdf 파일 찾아줘
바탕화면에 프로젝트 폴더 만들어줘
```

---

## 🏗️ 시스템 구조

```
음성/텍스트 입력
      ↓
[STT] Google Speech API
      ↓
[두뇌] llama3 (로컬) → 명령 분류
      ↓
[라우터] 명령 유형 판단
      ↓                    ↓
[Gemini API]          [Open Interpreter]
복잡한 작업 처리        코드 생성 및 실행
(웹 제어, 자동화)      (파일/시스템 작업)
```

---

## 🛠️ 기술 스택

| 구성 요소 | 기술 |
|------|------|
| 음성 인식 | Google Speech API |
| 명령 분류 | llama3 (Ollama) |
| AI 두뇌 | Gemini API |
| 실행 엔진 | Open Interpreter |
| 브라우저 제어 | Selenium |
| UI | 터미널 (PyQt6 개발 예정) |

---

## ❗ 자주 발생하는 오류

**Ollama 연결 실패**
```
[Executor] Ollama 없음 → Gemini API 모드
```
→ Ollama 앱 실행 후 다시 시도

**PyAudio 설치 실패**
```bash
pip install pipwin
pipwin install pyaudio
```

**Gemini API 오류 (API Key not found)**
→ `config/settings.py`에서 API 키 확인

**Gemini API 한도 초과 (429 오류)**
→ 잠시 후 재시도 또는 새 API 키 발급

**selenium ChromeDriver 오류**
→ Chrome 최신 버전으로 업데이트

---

## 📁 프로젝트 구조

```
capstone_pluiz/
├── app/
│   ├── main.py              # 실행 진입점
│   ├── agents/
│   │   ├── base_agent.py    # 에이전트 추상 클래스
│   │   ├── local_agent.py   # llama3 명령 분류
│   │   └── supervisor_agent.py  # Gemini 두뇌
│   ├── executor/
│   │   └── interpreter_exec.py  # Open Interpreter 실행
│   ├── router/
│   │   └── command_router.py    # 명령 라우팅
│   └── services/
│       ├── stt.py           # 음성 인식
│       └── tts.py           # 음성 출력
├── config/
│   └── settings.py          # 설정 (API 키 입력)
├── data/                    # 로그 및 데이터
├── requirements.txt
└── README.md
```

---

## 👥 팀 정보

캡스톤 디자인 프로젝트 | Pluiz Team
