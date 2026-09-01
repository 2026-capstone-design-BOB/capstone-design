# 협업 가이드 (Git & GitHub)

> 📍 [문서 허브](README.md) · 관련: [WORKFLOW.md](WORKFLOW.md)
>
> 팀 저장소 [`2026-capstone-design-BOB/capstone-design`](https://github.com/2026-capstone-design-BOB/capstone-design)의
> 브랜치 규칙과 작업 루틴입니다. 원래 저장소 루트 README에 있던 내용을 옮겼습니다.
> 커밋 메시지 형식·테스트 절차 등 개발 워크플로는 [WORKFLOW.md](WORKFLOW.md)를 보세요.

---

## 1. 브랜치 구조 및 역할

우리 프로젝트에는 총 5개의 브랜치가 운영됩니다.

* **`main`**: **최종 성역**. 교수님께 제출할 완성본만 존재합니다. (직접 수정 절대 금지)
* **`develop`**: **공동 작업실**. 팀원들의 모든 작업이 1차적으로 합쳐지는 곳입니다.
* **`feature/이름`**: **개인 작업실**. 각 팀원의 전용 공간입니다. (예: `feature/kim`)

---

## 2. 처음 시작할 때 (나만의 브랜치 만들기)

리포지토리를 클론(Clone)한 후, 딱 한 번만 수행합니다. (팀장님이 만든 `develop`을 기준으로 만듭니다.)

```bash
# 1. 원격 저장소 복제 (이미 했다면 생략)
git clone [리포지토리 주소]
cd [폴더이름]

# 2. develop 브랜치로 이동
git checkout develop

# 3. 최신 내용 가져오기
git pull origin develop

# 4. 나만의 브랜치 생성 (슬래시 포함!)
git checkout -b feature/본인이름

```

---

## 3. 일상적인 작업 루틴 (가장 중요!)

매일 작업할 때 아래 순서를 습관화하세요.

### ① 내 브랜치에서 작업 및 저장

```bash
git add .
git commit -m "[작업분류] 작업 내용 상세 기록"
git push origin feature/본인이름  # 내 서랍에만 올리는 거라 안전함!

```

* **커밋 메시지 예시:** `[Docs] 1주차 보고서 초안 작성`, `[Code] 로그인 UI 구현`

### ② 공동 작업실(develop)에 합치기 (GitHub PR)

내 컴퓨터에서 명령어로 합치지 않습니다! **GitHub 웹사이트**를 이용합니다.

1. GitHub 리포지토리 접속 ➔ **[Pull requests]** 탭 클릭 ➔ **[New pull request]**
2. **base: `develop**` ← **compare: `feature/본인이름**` 으로 설정
3. 작업 내용을 적고 **[Create pull request]** 클릭
4. 팀원들이 확인 후 문제가 없으면 **[Merge pull request]** 클릭

---

## 4. 최종 제출 (develop ➔ main)

이 과정은 팀장(본인)이 주도합니다.

1. `develop` 브랜치에 모든 팀원의 결과물이 모여 완벽한 상태가 되었을 때 수행합니다.
2. GitHub 사이트에서 **base: `main**` ← **compare: `develop**` 으로 PR을 생성합니다.
3. 최종 검토 후 합칩니다. (이때 교수님이 확인하시는 최종본이 업데이트됩니다.)

---

## 5. ⚠️ 주의사항 및 예외 상황 해결법

### 🚨 주의사항 (절대 금지!)

* **`git push origin main` 직접 금지**: 로컬에서 메인으로 직접 올리면 코드가 꼬이고 복구가 힘듭니다.
* **파일명 변경 주의**: 보고서 관리 시 `보고서_최종_1.docx` 처럼 이름을 바꾸지 마세요. `보고서.docx`로 파일명을 고정하고 **덮어쓰기** 하세요. (이력은 Git이 기억합니다.)

### ❓ 예외 상황: "동시에 같은 곳을 수정해서 충돌(Conflict)이 났어요!"

누군가 먼저 `develop`에 합쳐놓은 파일을 내가 수정했을 때 발생합니다.

* **해결법:** 1. `git checkout develop` ➔ `git pull origin develop` (최신본 가져오기)
2. `git checkout feature/내이름` ➔ `git merge develop` (내 브랜치에 합쳐보기)
3. 에러 난 파일의 내용을 수정 후 다시 `add`, `commit`, `push` 하면 해결!

### ❓ 예외 상황: "방금 push 한 내역을 취소하고 싶어요!"

당황하지 말고 팀장에게 말하세요. `git reset` 명령어가 있지만, 익숙지 않을 때 혼자 하면 더 꼬입니다.

---


---

**우리 팀 모두 화이팅입니다! 막히는 게 있으면 언제든 물어봐 주세요.**
