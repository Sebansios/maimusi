# 매무시 (Maimusi)

띄어쓰기 없이 입력하고 **스페이스**를 누르면 문장 전체가 자동으로 띄어쓰기되는 한글 입력기입니다.
운영체제의 입력 소스로 설치합니다. 입력 처리는 기기 안에서 수행하며, 사용자가 등록한 단어와
직접 고친 띄어쓰기 일부는 기기에 저장할 수 있습니다. 앱별 입력·재편집 지원 범위는 다릅니다.
자세한 데이터 처리는 [개인정보 안내](docs/PRIVACY.md)를 참고하세요.

Hangul input method with automatic spacing.

```
나는학교에간다        ⎵ →  나는 학교에 간다
아버지가방에들어가신다  ⎵ →  아버지가 방에 들어가신다
```

## 상태

현재 소스의 제품 버전은 **0.5.3**, 엔진 버전은 **0.1.0**입니다.
버전 정본은 [versions.json](versions.json)이며, 개발 소스와 이미 배포된 설치 파일은 구분합니다.
제품 안내와 설치 파일은 [공식 배포 페이지](https://sebansios.com/maimusi)를 참고하세요.
기능 변경은 [릴리스 설명](docs/release/0.5.3.md)에 정리합니다.

| 플랫폼 | 상태 |
|---|---|
| macOS 13+ (Apple Silicon·Intel 유니버설) | 동작: InputMethodKit 입력기, 설치 패키지 |
| Windows 10 1809+ (x64, 64·32비트 앱) | 동작: TSF 입력기, 설치 프로그램 ([windows/README.md](windows/README.md)) |
| Linux | 계획: 공용 코어·엔진 재사용, 데스크톱 어댑터 미구현 ([설계](linux/README.md)) |
| iOS / Android 키보드 | 미구현 (경량 엔진은 모바일 메모리 한도를 고려해 설계) |

배열은 **두벌식(KS X 5002)만** 지원합니다. 다른 배열은 판본별 명세와 조합 시험을 갖춘 뒤 추가합니다.

## 사용법

| 키 | 동작 |
|---|---|
| 띄어쓰기 없이 입력 | 밑줄 친 조합 중 문장으로 쌓입니다 |
| Space | 자동 띄어쓰기 → 변환 상태(마지막 어절 선택) |
| 변환 중 Space | 선택 어절의 다음 후보: 한자 → 이모지·단위·날짜 → 로마자(2000년 개정안·매큔라이샤워·예일) |
| 계속 입력 | 변환 결과를 공백과 함께 확정하고 이어서 입력 |
| Enter | 확정 (조합 중 Enter는 띄어쓰기 후 줄바꿈·전송까지, 설정 가능) |
| ← → | 어절 선택 |
| 변환 중 Shift+← / Shift+→ | 선택 어절의 오른쪽 경계를 한 글자 줄이기 / 늘리기 (다음 어절을 다 가져오면 합쳐짐) |
| 수동 수정 후 Backspace | 현재 경계를 유지하며 끝 글자 삭제 |
| ↑ ↓, 1–9 | 선택 어절의 후보 (한자·이모지·단위·날짜) |
| Esc | 띄어쓰기 전 원문으로 되돌리기 |
| Shift+Space | 일반 두벌식처럼 친 그대로 확정하고 공백 (자동 띄어쓰기 없이) |
| 텍스트 선택 후 Control+Shift+R | 확정한 텍스트의 띄어쓰기 편집 (선택 영역 API를 지원하는 앱) |
| 한/영 키 (Windows) | 한글·영문 전환. 한자 키는 변환·다음 후보 |

입력 메뉴의 **설정…**에서 엔진, 키 동작, 띄어쓰기 규칙(보조 용언·복합명사·숫자+단위)을 바꿀 수 있습니다.

붙어 있는 `학교에간다`를 나누려면 변환 상태에서 `Shift+←`를 두 번 눌러
`학교에 간다`로 고치고 Enter로 확정합니다. 잘못 나뉜 `학교 에간다`는 `학교`를 고른 채
`Shift+→`로 `에`를 가져옵니다. 앞 어절과 합치려면 ←로 앞 어절을 고른 뒤 `Shift+→`를 누릅니다. 수동으로 바꾼 경계는 확정할 때 자동 띄어쓰기로 덮어쓰지 않습니다.
한글 자모·결합문자·이모지는 한 글자 단위로 다룹니다.

확정한 텍스트는 선택한 뒤 `Control+Shift+R` 또는 입력 메뉴의 **선택한 텍스트의 띄어쓰기 편집**으로
다시 편집합니다. 재편집을 시작해도 자동으로 띄어쓰지는 않으며, Esc는 선택했던 원문을 복원합니다.
빈 선택·여러 줄·1,000자를 넘는 선택은 지원하지 않습니다. 앱별 IMK 선택 영역 지원에 따라
작동하지 않을 수 있습니다. 구현과 검증 범위는 [분절 편집](docs/SEGMENT_EDITING.md)에 있습니다.

## 띄어쓰기 엔진

| 엔진 | 위치 | 메모리 | 비고 |
|---|---|---|---|
| Kiwi (기본) | 별도 헬퍼 프로세스 | 기존 Apple Silicon 측정 약 600–850MB | Python 엔진의 띄어쓰기 규칙·변환 기능 |
| 경량 | 입력기 안의 Rust 코어 | 기존 모델 약 9MB | 모델을 별도로 준비한 빌드에서 헬퍼 대체 |

학습 말뭉치와 제한된 모델 파일은 이 저장소에 포함하지 않습니다.
Kiwi는 macOS에서 Apple Silicon용 헬퍼를 사용하며, Windows 구성은
[플랫폼 안내](windows/README.md)를 참고하세요.
모델 준비와 배포 범위는 [models/README.md](models/README.md)에 설명합니다.

엔진 결과는 **띄어쓰기만 바뀐 경우에만** 적용됩니다. 글자가 달라지거나 사용자가 직접 넣은 공백이 사라지는 결과는 버리고 원문을 유지합니다.

## 구조

```
core/      Rust 코어: 자모·두벌식 조합기, 입력 세션 상태 기계, 경량 띄어쓰기, C ABI
engine/    Python 엔진 서비스(Kiwi 띄어쓰기 규칙, 한자·이모지·단위·날짜 후보)
macos/     Swift + InputMethodKit 입력기, 빌드·패키지 스크립트
windows/   TSF 입력기(C++), 설정 프로그램, Inno Setup 설치 프로그램
linux/     Linux 어댑터 설계·지원 범위 (아직 미구현)
packaging/ 설치 패키지 리소스, 설치 후 스크립트, 제거 스크립트
tools/     모델 변환, 라이선스 수집, 개인정보 검사
docs/      설계·서명·라이선스·개인정보 문서
```

## 빌드 (macOS)

필요: Xcode 명령줄 도구, Rust(stable, `aarch64-apple-darwin`·`x86_64-apple-darwin`), Kiwi 헬퍼를 넣으려면 `engine/requirements.lock`을 설치한 Python 3.13.

공개 소스만으로 Apple Silicon 개발 번들을 만들 때는 제한된 모델과 번들 글꼴을
제외할 수 있습니다. Kiwi 헬퍼의 의존성은 별도로 설치합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r engine/requirements.lock
MODEL=none FONTS=none REFINER= ARCHS=arm64 \
  ENGINE_PYTHON="$PWD/.venv/bin/python" ./macos/build.sh
```

이 구성에는 매무시의 경량·경계 보정 모델과 번들 글꼴이 들어가지 않습니다.
Intel Mac용 경량 엔진 빌드에는 별도 모델 준비가 필요합니다.
모델이 준비된 빌드와 배포 패키지 조립은 [개발 안내](docs/DEVELOPMENT.md)와
[모델 안내](models/README.md)를 참고하세요.
배포물에는 `tools/privacy_scan.py`를 통한 개인정보 검사를 적용합니다.

## 문서

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): 구성 요소, 키 처리, 안전 장치
- [docs/PRIVACY.md](docs/PRIVACY.md): 입력 데이터 처리와 배포물 개인정보 점검
- [docs/UPDATES.md](docs/UPDATES.md): 자동 업데이트의 서명된 업데이트 정보 형식, 키 관리, 출시 순서
- [docs/SIGNING.md](docs/SIGNING.md): 코드 서명·공증과 개인정보 노출
- [docs/LICENSING.md](docs/LICENSING.md): 소스·제품·제3자 구성 요소의 이용 조건
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 라이선스

자체 소스와 문서는 **Copyright © 2026 Sebansios. All rights reserved.**로 공개합니다.
현재 별도의 오픈소스 이용 허락은 부여하지 않습니다. GitHub 약관에 따른 열람·포크,
법령상 권리와 제3자 구성 요소의 라이선스는 그대로 적용됩니다.
배포 패키지는 함께 제공하는 무료 사용 EULA를 따릅니다.
[소스 저작권 고지](LICENSE)와 [라이선스·제3자 조건](docs/LICENSING.md)을 참고하세요.

## 개발 참여와 소스 관리

공용 코어·엔진과 플랫폼 어댑터를 한 저장소에서 관리합니다.
개발 환경·시험·브랜치·버전 관리는 [개발 안내](docs/DEVELOPMENT.md),
공개 범위와 소스 내보내기는 [공개 소스 관리](docs/PUBLIC_SOURCE.md)를 참고하세요.
