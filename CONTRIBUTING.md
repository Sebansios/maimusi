# 개발 안내

매무시는 공용 엔진과 운영체제 어댑터를 한 저장소에서 개발합니다.
자체 소스는 현재 [기본 저작권 유지](LICENSE)로 공개합니다.
버그 보고와 기능 제안을 받을 수 있으며, 외부 코드 기여를 병합하기 전에는
그 코드의 이용·수정·배포 및 향후 라이선스 변경에 필요한 권한을 확인합니다.

| 경로 | 책임 |
|---|---|
| `core/` | Rust 조합기·세션·띄어쓰기와 C ABI |
| `engine/` | Python 찰떡 엔진·후보 변환·회귀 시험 |
| `macos/` | InputMethodKit 어댑터·설정·macOS 빌드 |
| `windows/` | TSF 어댑터·설정·Windows 빌드 |
| `linux/` | Linux 어댑터 설계와 구현 예정 범위 |
| `packaging/` | 공통 제품 정보와 플랫폼별 설치 리소스 |
| `tools/` | 버전·검증·데이터 변환·공개 소스 검사 |
| `models/` | 모델 준비 안내. 제한된 모델 파일은 포함하지 않음 |
| `docs/` | 사용자·개발자에게 공개할 기능·계약 문서 |

## 시작

Git, Rust stable, Python 3.13을 설치합니다. 가상환경은 각 기기의 로컬 디스크에 둡니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r engine/requirements.lock -r tools/requirements.lock
.venv/bin/python tools/dev.py check
```

Windows에서는 같은 명령에 `.venv\Scripts\python.exe`를 사용합니다.
전체 엔진 시험에는 Kiwi와 잠금 파일의 의존성이 필요합니다. 로컬 학습 자료가 필요한
시험은 해당 자료가 없으면 건너뛸 수 있으므로 결과의 skip 수를 함께 확인합니다.

```sh
python tools/dev.py doctor    # 도구·Git 상태·플랫폼 확인
python tools/dev.py check     # 버전·공개 경계·Rust·Python 공통 시험
python tools/dev.py core      # 외부 네트워크 없이 Rust 시험
python tools/dev.py engine    # Python 엔진 시험
python tools/dev.py tools     # 개발 도구 시험
```

플랫폼별 빌드·실기 검증은 [macOS](README.md#빌드-macos),
[Windows](windows/README.md), [Linux](linux/README.md)를 따릅니다.
공통 시험 통과는 플랫폼 입력기 설치·실기 입력 검증을 대신하지 않습니다.

## 공동 작업

각 기기에는 독립 clone과 가상환경·빌드 폴더를 둡니다. `.git`이나 작업 트리를
클라우드 드라이브로 동기화하지 않습니다. 모든 플랫폼의 통합 기준은 `main`이며,
작업은 `feature/<주제>`, `fix/<주제>`, `chore/<주제>`처럼 짧은 브랜치로 나눕니다.
같은 브랜치에 두 기기가 동시에 커밋하지 않습니다.

시작할 때 `git status`, `git fetch origin`으로 확인하고 깨끗한 작업 트리에서
`git switch -c feature/<주제> origin/main`으로 분기합니다. 기존 변경이 있으면
먼저 별도 작업 브랜치에 보존합니다. 다른 기기에서 이어받을 때는 해당 커밋을
fetch해 별도 브랜치로 가져옵니다. 강제 push나 자동 stash/pull을 하지 않습니다.

공용 C ABI(`core/include/hangul_core.h`), 엔진 JSON 프로토콜,
설정·단어장 파일 형식 변경은 모든 어댑터의 영향을 확인합니다.
OS별 동작을 공용 코어에 넣거나 UI를 다른 플랫폼에 그대로 복사하지 않습니다.
리뷰에는 기준 커밋, 변경 이유, 공통 시험 결과, 각 OS의 실기 검증 여부를 적습니다.

## 버전과 출시

제품·엔진·빌드 번호는 `versions.json`에서 관리합니다.
`python tools/versions.py sync` 후 `python tools/versions.py check`로 확인합니다.
빌드 번호는 플랫폼 전체에서 공유하며 같은 번호의 배포물을 덮어쓰지 않습니다.
출시 담당자가 통합 브랜치에서 번호를 정하고, 다른 작업 브랜치는 출시 전까지
번호를 따로 올리지 않습니다. 출시 기록에는 소스 커밋·모델 해시·산출물 해시·검증 OS를 남깁니다.

## 공개 범위

에이전트 지침, 개인 작업 메모, 기기별 설정, 서명 개인키, 인증 정보, 학습 원문과
제한된 모델은 커밋하지 않습니다. 공개용 설명에는 개인 경로나 기기 식별자를 넣지 않습니다.
`python tools/public_source.py audit`는 Git에 포함될 파일을 검사합니다.
공개 소스 준비 절차와 계정 분리는 [공개 소스 관리](docs/PUBLIC_SOURCE.md)를 따릅니다.
