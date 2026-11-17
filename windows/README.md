# 매무시 Windows 판

TSF(Text Services Framework) 입력기다. 코어(`core/`)와 찰떡 엔진(`engine/`)은 macOS 판과 같고, 이 폴더에는 Windows 어댑터·설정 프로그램·설치 프로그램만 있다.

| 구성 | 위치 | 설명 |
|---|---|---|
| `MaimusiTIP.dll` (x64, x86, arm64) | `tip/` | 텍스트 서비스. 각 앱 안에 올라가 키를 코어 세션에 넘기고 조합을 문서에 반영한다 |
| `MaimusiSettings.exe` | `settings/` | 설정 창. `--register-user`/`--unregister-user`로 사용자 입력 방법 목록에 더하고 뺀다 |
| `MaimusiEngine.exe` | `build_engine.ps1` | 찰떡(Kiwi) 엔진. 사용자당 하나만 떠서 모든 앱이 named pipe로 함께 쓴다 |
| 설치 프로그램 | `installer/`, `package.ps1` | Inno Setup. 버전마다 별도 폴더에 설치하고 `regsvr32`로 등록한다 |

## 동작

- **한/영 키**(`VK_HANGUL`)로 한글·영문을 바꾼다. 작업 표시줄의 `가`/`A` 표시기를 클릭해도 된다. 한/영 키가 없는 키보드는 설정의 「오른쪽 Alt로도 한/영 전환」을 켠다. 한글·영문 상태는 앱 사이에 공유되고, 앱이 스스로 바꾼 상태(IMM 변환 모드 등)는 그 앱에만 적용된다.
- 입력 칸이 아닌 곳(웹 페이지 본문, 동영상 플레이어 등)에 포커스가 있으면 TSF가 알려 주는 키보드 비활성·빈 문맥·읽기 전용 상태를 따라 키를 가로채지 않는다. 한글 상태에서도 YouTube의 F(전체 화면) 같은 단축키가 그대로 동작한다. 한/영 키만 예외.
- **한자 키**(`VK_HANJA`)는 조합 중이면 변환(Space와 같음), 변환 중이면 다음 후보(↓와 같음)다.
- 나머지 키 동작은 macOS 판과 같다(README의 사용법). 선택 텍스트 재편집은 `Ctrl+Shift+R`.
- **Shift+Space**는 일반 두벌식처럼 친 그대로(자동 띄어쓰기 없이) 확정하고 공백을 넣는다(0.5.3, 공용 코어). 설정 「직접 넣은 공백」은 없앴고 `rule.existing_spaces`는 기본값 그대로 엔진에 보낸다.
- **경계 조정**은 ⇧←(줄이기)·⇧→(늘리기) 두 키다. 후보 창 아래 줄에 키캡과 이름으로 보이고 지금 쓸 수 없는 쪽은 흐리게 둔다. 늘리기로 다음 어절을 다 가져오면 합쳐지고, 앞 어절과는 ←로 옮긴 뒤 ⇧→(`docs/SEGMENT_EDITING.md`). 코어의 `HC_KEY_MERGE_*`는 C ABI 호환 때문에 남아 있다.
- **경계 기억**: 고쳐 확정하면 한 번에 기억한다. 확정할 때 문서의 InputScope(`GUID_PROP_INPUTSCOPE`)가 암호·PIN·메일·로그인 이름·URL·숫자·전화번호·한 글자 칸이면 학습을 요청하지 않는다(조합을 시작할 때 읽음, `TextService::readInputScope`). 기억한 띄어쓰기가 쓰인 문장은 후보 창 아래 줄 오른쪽에 「기억한 띄어쓰기」로 알리고, 입력 표시기 메뉴의 「방금 기억한 띄어쓰기 잊기 (…)」(기억한 게 있을 때만)와 설정의 기억 목록에서 하나씩 지운다. 마지막으로 기억한 것은 설정의 `lastLearned`에 둔다.
- **훈음으로 한자 찾기**(선택, 기본 꺼짐, 설정 `hanjaGlossSearch` → `configure`의 `hanja_gloss`): 「살찔비」 → 肥, 「배울학학교교」 → 學校.
- **단어장**(`common/wordbook.cpp`, 형식 `docs/WORDBOOK.md`): 설정에서 내보내기·가져오기(가져오기는 더하기만), 「기기 사이에 단어장 맞추기」로 고른 폴더의 `Maimusi\maimusi-wordbook-<deviceID>.json`. 맞추는 때는 설정 앱을 열 때와 「지금 맞추기」, 단어·기억이 바뀐 3초 뒤(그 앱의 입력기나 설정 앱), 입력하는 앱의 입력기가 포커스를 받을 때 마지막으로 맞춘 지 5분이 지났으면. `Local\MaimusiWordbookSync`로 한 번에 하나만 하고 `settings.json`은 쓰기 직전에 다시 읽어 합친다. 입력기의 백그라운드 작업은 DLL 참조를 쥔 스레드에서 하므로 앱이 텍스트 서비스를 내려도 DLL이 먼저 내려가지 않는다. 자체 시험: `MaimusiSettings.exe --test-wordbook [폴더]`.
- **설정 「띄어쓰기 규칙」의 예문**: 설정 앱이 엔진 파이프로 `space` 요청에 지금 규칙(`spacing`)을 실어 보낸다. 엔진이 떠 있지 않으면 설정 앱이 띄운다(찰떡 엔진이 있을 때).
- **TSF 앱**(Chrome·Edge·Electron 앱·Firefox·Office·메모장·VS Code 등)에서는 문장 전체가 밑줄 친 조합으로 문서 안에 표시된다.
- **IMM32 앱**(일반 EDIT 컨트롤, `WM_IME_*`를 직접 처리하는 메신저·워드프로세서 등. 문맥 상태가 `TS_SS_TRANSITORY`이면서 Chromium류처럼 `TS_SS_NOHIDDENTEXT`가 없거나 IMM 연결 계층의 상위 동적 플래그가 있는 경우로 판별)은 Windows의 IMM 연결 계층(CUAS)이 한국어 조합을 「확정 문자열 + 조합 중인 한 글자」로만 전달한다. 띄어쓰기 전 문장을 문서에 넣으면 앞부분이 즉시 확정되므로, 이런 앱에서는 입력 중인 문장을 커서 옆 작은 창에 보여 주고 확정할 때 문서에 넣는다.
- 엔진: 찰떡 엔진이 준비되기 전이나 응답이 0.6초를 넘으면 경량 모델(`spacing.hspm`, 있으면)이 대신 띄어쓴다. 경량 모델이 없으면 첫 Space는 엔진이 뜰 때까지 최대 5초 기다린다.
- 엔진 파이프(`\\.\pipe\Maimusi.Engine.<사용자 SID>`)는 소유자가 사용자이고, 사용자·SYSTEM과 AppContainer(ALL APPLICATION PACKAGES, ALL RESTRICTED APPLICATION PACKAGES)만 열 수 있으며 원격 연결을 거부한다. AppContainer에는 데이터 읽기·쓰기와 소유자 확인에 필요한 권한만 주고 파이프 인스턴스 생성 권한은 주지 않는다. 무결성 레이블은 중간(medium)이다.
- 입력기는 파이프의 소유자가 자기 사용자이고 레이블이 중간 이상일 때만 입력을 보낸다. 낮은 무결성 프로세스도 같은 사용자 소유로 같은 이름의 파이프를 만들 수 있지만 레이블은 낮음으로만 붙으므로 가로챌 수 없다(AppContainer는 전역 이름의 파이프를 만들지 못한다). 엔진은 설정 시간(기본 20분) 동안 요청이 없으면 스스로 끝난다.
- **샌드박스 앱**(시작 메뉴 검색창 `SearchHost`, 스토어 앱 등 AppContainer): 엔진을 띄우지는 않지만, 다른 앱에서 입력할 때 시작된 엔진이 떠 있으면 그것을 쓴다. 엔진은 연결한 프로세스의 토큰을 보고, AppContainer·낮은 무결성·제한 토큰이면 띄어쓰기·후보·상태 확인만 받고 설정 변경(`configure`)과 경계 학습(`learn`)은 거부한다. 엔진이 꺼져 있으면 경량 엔진을 쓴다. AppContainer가 아닌 낮은 무결성 프로세스는 파이프 레이블 때문에 접속하지 못하고 경량 엔진을 쓴다.
- 설정 파일: `%APPDATA%\Maimusi\settings.json`. AppContainer는 이 파일을 읽지 못하므로, 저장할 때마다(그리고 일반 앱의 입력기가 설정을 읽을 때 다르면) 사용자 단어·학습한 경계·단어장 기록(`wordbookStamps`, `lastLearned`)·동기화 상태(`syncFolder`, `deviceID`, `syncLast`, `syncError`)를 뺀 설정 사본을 `HKCU\Software\Maimusi\Sandbox`의 `Settings`(JSON 문자열)에 쓰고, 이 키만 AppContainer가 읽을 수 있게 한다. 샌드박스 앱에서는 이 사본을 읽으며, 입력 표시기 메뉴의 설정 항목은 바꿀 수 없게 흐리게 표시한다. 진단 로그는 `HKCU\Software\Maimusi\DebugLog`(DWORD)=1일 때만 `%LOCALAPPDATA%\Maimusi\debug.log`에 쓰며, 입력한 글자는 기록하지 않는다.

## 화면

- 후보 창은 macOS와 같은 모양이다(0.5.3 빌드 33부터). 설정 「후보 창」에서 macOS와 같은 프리셋 8개(유리·옻칠·한지·먹·청자·가로·담백·기본(0.5.2))와 글자 크기(보통·크게·아주 크게)를 고른다. 설정 키도 같다(`candidatePreset`, `candidateTextSize`). 테마 값은 `common/candidatetheme.cpp`, 배치와 그리기는 `common/candidateview.cpp`(macOS `CandidateView`의 치수: 행 여백 글자 크기×0.3, 번호와 후보 사이 ×0.5, 아래 줄의 키캡·「기억한 띄어쓰기」·쪽 번호)에 있고, 실제 후보 창·설정 미리보기·`MaimusiSettings.exe --render-candidates <폴더>`(프리셋마다 밝게·어둡게 PNG)가 같은 코드로 그린다.
- 후보 창은 픽셀 단위 투명도가 있는 레이어드 창(`UpdateLayeredWindow`)이라 연속 곡률(스퀘어클)·둥근·각진 모서리와 부드러운 그림자를 macOS처럼 그린다. macOS의 반투명 재질과 Liquid Glass는 Windows에 없으므로, macOS가 화면 밖 그림에 쓰는 반투명 바탕색으로 그린다(뒤 화면을 흐리게 비추지는 않음). 색을 정하지 않은 테마는 앱 테마(밝게/어둡게)와 강조색을 따른다. 세부 조정(macOS의 「사용자 지정」)은 아직 Windows에 없다.
- 글꼴은 시스템의 맑은 고딕(한지 테마의 명조는 바탕, 없으면 맑은 고딕)이다. 투명한 바탕이라 글자는 회색조 안티에일리어싱으로 그리고, 맑은 고딕의 힌팅이 작은 크기에서 글자를 또렷하게 한다. 이 글꼴에 없는 한자(CJK 확장)는 Microsoft YaHei, SimSun-ExtB/ExtG, 시스템 대체 글꼴 순으로 찾는다. 0.5.3 빌드 33부터 Noto Sans KR은 넣지 않는다.
- 작업 표시줄의 `가`/`A`는 실제 시스템 DPI 크기로, 글리프의 잉크 영역을 재어 시스템 표시기와 같은 높이로 그린다.
- 설치 마법사 그림은 `tools/make_wizard.ps1`이 표지(`tools/mark.ps1`, macOS 아이콘과 같은 도형)로 배율별로 만든다.

## ARM64(Windows on Arm)

Windows 11 on Arm에서는 네이티브 ARM64 앱과 에뮬레이션되는 x64 앱이 같은 64비트 레지스트리(`HKLM\SOFTWARE\Classes\CLSID\{1A36DDCD-…}\InprocServer32`)를 읽으므로 64비트 DLL 경로가 하나뿐이다. 그래서 `arm64\MaimusiTIP.dll`은 **ARM64X** DLL이다. 같은 소스를 ARM64와 ARM64EC로 두 번 컴파일하고(코어도 `aarch64-pc-windows-msvc`, `arm64ec-pc-windows-msvc` 두 벌) `link /MACHINE:ARM64X`로 합친다. ARM64 앱은 ARM64 코드를, x64 앱은 ARM64EC 코드(네이티브, x64 호출 규약)를 쓴다. 32비트(x86) 앱은 x64 Windows와 같이 `x86\`을 쓴다.

- 「pure forwarder」(내보내기만 아키텍처별 DLL로 넘기는 작은 ARM64X DLL)는 쓰지 않는다. 넘겨받을 DLL을 이름으로만 찾으므로 앱 폴더·System32가 아닌 설치 폴더에서는 찾는 경로가 보장되지 않고, `regsvr32`가 넘겨받은 ARM64 DLL의 경로를 등록해 x64 앱이 불러오지 못한다.
- 설치 프로그램은 하나다. ARM64에서는 `{sys}\regsvr32.exe`(네이티브 ARM64)로 `arm64\`를, `{syswow64}`로 `x86\`을 등록하고 `x64\`는 등록하지 않는다. x64 Windows에서는 `arm64\`를 등록하지 않는다.
- 설정 프로그램과 찰떡 엔진(`MaimusiEngine.exe`)은 x64로 두고 ARM64에서는 에뮬레이션으로 실행한다. 그래서 ARM64에서는 Windows 11(빌드 22000) 이상이 필요하다(Windows 10 on Arm에는 x64 에뮬레이션이 없음). 경량 엔진(Rust 코어)은 DLL 안에서 네이티브로 돈다. kiwipiepy는 `win_arm64` 휠을 내지 않아(2026-10 기준 0.24.0까지 `win32`·`win_amd64`뿐) 네이티브 엔진은 아직 만들 수 없다.
- 링크할 때 나오는 `LNK4279`(`SetFilePointerEx`의 출구 썽크를 Rust std는 `i8`, UCRT는 `m8`로 표기)는 둘 다 8바이트 값을 정수 레지스터로 넘기는 같은 호출이라 무시해도 된다.

ARM64 실기에서 확인할 것(x64 PC에서는 빌드와 `dumpbin /headers`의 `AA64 machine (ARM64) (ARM64X)`까지만 확인할 수 있다):

1. 설치 후 `HKLM\SOFTWARE\Classes\CLSID\{1A36DDCD-…}\InprocServer32`가 `<버전>\arm64\MaimusiTIP.dll`, `WOW6432Node` 쪽이 `<버전>\x86\MaimusiTIP.dll`인지.
2. 네이티브 ARM64 앱(메모장, Edge 등)·x64 에뮬레이션 앱(x64 전용 앱, `tsf_harness.exe` x64 빌드)·x86 앱(`tsf_harness32.exe`)에서 각각 입력과 띄어쓰기(`--rich` 17개 시나리오: ARM64 빌드는 `vcvarsall x64_arm64`로 같은 시험을 빌드).
3. 세 종류 앱 모두에서 한/영 키, 오른쪽 Alt 한/영 설정, 작업 표시줄 `가`/`A` 표시기.
4. 찰떡 엔진이 에뮬레이션으로 시작되고(작업 관리자의 `MaimusiEngine.exe`, 아키텍처 x64) 세 종류 앱이 같은 엔진을 함께 쓰는지, 경량 모델 대체(엔진 시작 전 첫 Space).
5. 후보 창(프리셋별 모양·그림자·클릭)·설정 창, 업데이트 설치(열린 앱이 이전 폴더를 쓰는 동안 새 판 설치)와 제거.

## 빌드

필요: Visual Studio 2022 이상의 C++ 데스크톱 개발(MSVC, Windows SDK)과 「MSVC ARM64/ARM64EC 빌드 도구」 구성 요소(`Microsoft.VisualStudio.Component.VC.Tools.ARM64`), Rust(`x86_64-pc-windows-msvc`, `i686-pc-windows-msvc`, `aarch64-pc-windows-msvc`, `arm64ec-pc-windows-msvc`), Python, Inno Setup 6.3 이상. 찰떡 엔진을 넣으려면 `engine/requirements.lock`을 설치한 Python 3.13.

```powershell
rustup target add x86_64-pc-windows-msvc i686-pc-windows-msvc aarch64-pc-windows-msvc arm64ec-pc-windows-msvc
py -3.13 -m venv build\venv-engine
build\venv-engine\Scripts\python -m pip install -r engine\requirements.lock
powershell -ExecutionPolicy Bypass -File windows\build.ps1 -EnginePython build\venv-engine\Scripts\python.exe `
    [-Model build\models\nikl-morph.hspm] [-Refiner build\models\refiner-public]
powershell -ExecutionPolicy Bypass -File windows\package.ps1
```

`build\windows\dist\Maimusi-<버전>-Windows.exe`(x64·ARM64 겸용)와 `SHA256SUMS.txt`가 만들어진다. `package.ps1`은 설치될 파일과 설치 파일을 `tools/privacy_scan.py`로 검사하고(홈 경로·계정명·컴퓨터 이름·git 사용자, UTF-16 포함, 고정 엔진 내부 모듈까지) 실패하면 중단한다. 설치 파일에 드러나는 신원은 `packaging/product.env`의 게시자(세반시옷)·웹사이트·문의 메일뿐이다. 서명하지 않으므로 처음 실행할 때 SmartScreen 경고가 나온다(`docs/SIGNING.md`).

## 시험

```powershell
python -m pytest engine\tests                     # 공용 엔진
cargo test --manifest-path core\Cargo.toml        # 공용 코어
python windows\tests\pipe_smoke.py                # 엔진 named pipe 서버
build\windows\sandbox_pipe.exe build\windows\engine\dist\MaimusiEngine\MaimusiEngine.exe   # 샌드박스 접속
```

`windows/tests/sandbox_pipe.cpp`(빌드 명령은 파일 머리말)는 엔진 서버를 따로 띄우고 실제 AppContainer·LPAC(ALL APPLICATION PACKAGES 제외)·낮은 무결성 자식 프로세스에서 접속해 본다. AppContainer에서 띄어쓰기·후보·ping 응답과 `configure`·`learn` 거부, 엔진 파이프의 서버 인스턴스나 전역 파이프를 만들 수 없음, 설정 사본 읽기를 확인하고, 다른 계정(시스템 서비스) 소유 파이프와 낮은 무결성 프로세스가 만든 파이프를 입력기 클라이언트가 거부하는지 본다. 엔진 대신 `build\venv-engine\Scripts\python.exe engine\hangul_engine_main.py`로 소스의 서버를 시험할 수도 있다. `--launch <프로그램> [인수]`는 같은 AppContainer에서 프로그램을 실행한다(예: `tsf_harness.exe --rich`, 입력기 폴더에 `ALL APPLICATION PACKAGES` 읽기 권한 필요).

`windows/tests/tsf_harness.cpp`는 설치된 입력기를 실제로 불러 입력해 보는 종단 시험이다(빌드 명령은 파일 머리말). 기본은 TSF 키 관리자를 통해 프로세스 안에서 키를 넣어 화면을 차지하지 않는다. `--sendinput`은 실제 키보드 경로(한/영 키 포함)를 쓰며 시험 창이 앞에 있어야 한다. `--rich`(TSF RichEdit), 기본(EDIT, IMM 연결), `--imm`(WM_IME_*를 직접 처리하는 창), `--ms`(Microsoft 한국어 IME 비교). 32비트 DLL은 x86으로 빌드한 같은 시험으로 확인한다.

개발 중 다시 빌드한 DLL은 `tools\dev_install.ps1`이 매번 새 폴더에 복사해 등록한다(앱이 잡고 있는 DLL과 충돌하지 않도록). 처음 한 번은 `-Elevated`.

## 알려진 제한

- ARM64 판은 아직 실기에서 확인하지 않았다(위 「ARM64」의 확인 목록). Windows 10 on Arm은 지원하지 않는다.
- 제거 후에도 열려 있는 앱이 DLL을 잡고 있으면 파일은 다시 시작할 때 지워지며, 그 전에는 같은 버전을 다시 설치할 수 없다.
- 업데이트 후 이미 열려 있던 앱은 다시 시작할 때까지 이전 버전을 쓴다. 설치 프로그램은 버전·빌드마다 별도 폴더(`0.5.2.22` 등)에 설치하고, 아직 쓰이는 이전 폴더는 지우지 않고 다음 업데이트 때 정리한다. 이전 DLL이 자기 폴더에서 엔진·모델을 찾지 못하면 현재 등록된 설치 폴더의 것을 쓴다.
- 업데이트할 때 TSF 프로필을 다시 등록하지 않는다(열려 있는 앱의 입력기가 꺼지므로). DLL 경로와 아이콘 경로만 고친다.
- 로그인 화면·UAC 같은 보안 데스크톱에서는 동작하지 않는다.
