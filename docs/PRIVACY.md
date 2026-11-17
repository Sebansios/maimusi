# 개인정보

## 입력 데이터

- 입력한 글자는 조합·띄어쓰기에 필요한 동안만 메모리에 있습니다. 파일·로그·클립보드에 쓰지 않고
  밖으로 보내지 않습니다. 헬퍼 코드에는 네트워크 호출이 없습니다(헬퍼에 포함된 파이썬 표준
  라이브러리에는 통신 모듈이 있지만 쓰이지 않습니다).
- macOS 입력기의 네트워크 호출은 새 버전 확인·받기와 후보 창 글꼴 받기 두 가지이며, 둘 다
  `dl.sebansios.com`만 씁니다(0.5.3부터).
- 새 버전 확인(`Updater.swift`, 형식 [UPDATES.md](UPDATES.md)): `updateAutoCheck`가 켜져 있으면(기본값)
  입력기 시작 90초 뒤와 그 뒤 한 시간마다 마지막 확인이 23시간 넘게 지났을 때 고정 주소
  `https://dl.sebansios.com/maimusi/update/macos.json` 하나를 받습니다(실패하면 3시간 뒤). 주소에 질의
  문자열이 없고, 머리글은 `User-Agent: Maimusi`, 고정 `Accept-Language: ko`, 표준 `Accept`·`Accept-Encoding`
  뿐입니다. 지금 쓰는 판·기기·사용자 식별자는 보내지 않으며 판 비교는 이 Mac에서 합니다. 쿠키·캐시 없는
  ephemeral 세션이고 https가 아닌 곳으로의 넘김은 따르지 않습니다. 받은 정보는 앱에 넣은 Ed25519 공개키로
  서명을 확인한 뒤에만 쓰고(64 KiB 상한), 지금보다 높은 빌드만 알립니다. 사용자가 「업데이트」를 누르면
  서명된 주소의 설치 파일을 `~/Library/Caches/HangulSpacing/Updates/`에 받아 크기·SHA-256을 대조한 뒤
  macOS 설치 프로그램으로 엽니다. 설치한 판보다 오래된 받은 파일은 다음 시작 때 지우고, `uninstall.command`는
  이 폴더를 지웁니다. 기본 설정에 남는 것은 마지막 확인·시도 시각, 건너뛴 빌드, 「나중에」 시각, 받아 둔
  빌드 번호뿐입니다.
  앱에는 Noto Sans/Serif CJK KR 부분 글꼴이 들어 있고, 그 글꼴에 없는 한자가 후보에 처음 나오면
  `fontAutoDownload`가 켜져 있을 때(기본값) 고정 주소 `https://dl.sebansios.com/maimusi/fonts/<파일>`
  에서 전체 글꼴을 한 번 받습니다. 주소·헤더에 입력 내용이나 기기 정보를 싣지 않고(쿠키·캐시 없는
  ephemeral 세션, User-Agent `Maimusi`, 고정 `Accept-Language: ko`), 받은 파일은 크기와 SHA-256을 확인한 뒤
  `~/Library/Application Support/HangulSpacing/fonts/`에 둡니다. 서버에는 일반 내려받기처럼 IP 주소
  등 접속 정보만 전달됩니다. 같은 글꼴(Noto/Source Han/본고딕·본명조)이 이미 설치돼 있으면 받지 않습니다.
- 단어장 동기화(0.5.3부터, `Wordbook.swift`, 선택): 사용자가 고른 폴더 안의 `Maimusi/`에
  `maimusi-wordbook-<무작위 8자리>.json`을 쓰고 같은 폴더의 다른 기기 파일을 읽어 합칩니다. 세반시옷 서버나
  네트워크 코드는 쓰지 않으며, 폴더를 맞추는 일은 그 폴더의 서비스(iCloud Drive 등)나 사용자가 합니다.
  파일에는 등록한 단어, 기억한 띄어쓰기(손으로 고친 어절), 항목마다 바꾼 시각, 지운 항목의 시각만 들어
  있습니다. 기기 이름·사용자 이름은 넣지 않습니다. 형식은 [WORDBOOK.md](WORDBOOK.md).
- 경계 기억은 한 번 고치면 바로 기억합니다. 보안 입력(암호 칸) 중의 확정, 주소·메일·경로(`@`, `://`,
  `www.`, `/`, `\`)가 섞인 글, 한글이 없는 말은 기억하지 않습니다(`user_spacing.learn`,
  `InputController.takeLearning`). 입력 메뉴 「방금 기억한 띄어쓰기 잊기」와 설정 목록에서 하나씩 지웁니다.
- 설정 창 「개인정보」: 이 Mac에 남는 것(설정·단어·기억), 받아 둔 글꼴(지우기), 기기 밖으로 나가는 것
  (글꼴 받기, 새 버전 확인, 고른 동기화 폴더)을 보여 줍니다. Time Machine 같은 백업은 설정 파일
  (`~/Library/Preferences/<번들 ID>.plist`)과 받아 둔 글꼴도 함께 백업합니다. `uninstall.command --purge`는
  설정과 받아 둔 글꼴을 지우고, 사용자가 고른 동기화 폴더의 단어장 파일은 지우지 않습니다.
- Kiwi 헬퍼는 표준 입력으로 받은 문장을 처리해 표준 출력으로만 돌려줍니다. 헬퍼의 표준 오류는
  입력기가 버리며(`/dev/null`), 오류 응답에는 오류 종류만 담기고 입력 내용은 담기지 않습니다.
- 저장되는 것은 설정값(엔진, 키 동작, 띄어쓰기 규칙)뿐이며, macOS 기본 설정 저장소
  (`~/Library/Preferences/<번들 ID>.plist`)에 있습니다.
- 확정 텍스트의 띄어쓰기 편집은 사용자가 선택 후 Control+Shift+R 또는 입력 메뉴를 실행한
  경우에만 그 선택 영역을 IMK API로 읽습니다. 문서 전체·클립보드·접근성 API를 읽지 않으며,
  원문과 수동 편집 상태는 확정 또는 취소할 때까지 해당 입력 세션의 메모리에만 있습니다.
- 후보 선택 학습은 아직 입력기에 연결하지 않았습니다. 추가하더라도 이 Mac 안에만 저장하고 끌 수
  있게 합니다.

## Windows 판

- 찰떡 엔진은 사용자당 한 프로세스가 named pipe로 모든 앱의 입력기에 답합니다. 파이프는 원격 연결을
  거부하고, 같은 사용자·SYSTEM·AppContainer 앱만 열 수 있습니다. 입력기는 파이프 소유자가 자기
  사용자이고 무결성 레이블이 중간 이상일 때만 입력을 보냅니다. 엔진은 입력을 기록하지 않습니다.
- AppContainer 앱(스토어 앱, 시작 메뉴 검색창 등)은 엔진에 띄어쓰기·후보·상태 확인만 요청할 수
  있고 설정을 바꾸거나 경계 학습을 요청할 수 없습니다. 다만 띄어쓰기 결과에는 사용자 단어와 학습한
  경계가 반영되므로, 이 파이프를 직접 여는 AppContainer 앱은 결과를 비교해 특정 단어가 등록되어
  있는지 짐작할 수 있습니다.
- 설정은 `%APPDATA%\Maimusi\settings.json`에 있습니다. AppContainer 앱의 입력기가 읽을 수 있도록
  설정값의 사본을 `HKCU\Software\Maimusi\Sandbox`에 두며, 이 키는 모든 AppContainer 앱이 읽을 수
  있습니다. 사본에는 사용자 단어(`userWords`), 학습한 경계(`learnedBoundaries`), 단어장 기록
  (`wordbookStamps`, `lastLearned`), 동기화 폴더와 상태(`syncFolder`, `deviceID`, `syncLast`,
  `syncError`)를 넣지 않습니다(`windows/common/settings.cpp`). 입력기 제거(`--unregister-user`) 때 지웁니다.
- Windows 판은 네트워크에 연결하지 않습니다. 후보 창 글꼴 받기는 macOS에만 있고, Windows는 시스템의
  맑은 고딕(한지 테마는 바탕)을 씁니다.
- 경계 기억(0.5.3부터)은 한 번 고치면 바로 기억합니다. 확정할 때 문서의 입력 범위(InputScope,
  `GUID_PROP_INPUTSCOPE`)가 암호(`IS_PASSWORD`, `IS_PRIVATE`, 숫자·영숫자 PIN), 메일·로그인 이름·URL
  (`IS_EMAIL_SMTPEMAILADDRESS`, `IS_EMAIL_USERNAME`, `IS_LOGINNAME`, `IS_URL`), 숫자·전화번호
  (`IS_NUMBER`, `IS_DIGITS`, `IS_TELEPHONE_*`), 한 글자(`IS_ONECHAR`)인 칸에서는 엔진에 학습을 요청하지
  않습니다(`TextService::readInputScope`). 엔진의 내용 거르기(주소·메일·경로가 섞인 글, 한글이 없는 말)는
  macOS와 같습니다. 입력 표시기 메뉴 「방금 기억한 띄어쓰기 잊기」와 설정의 기억 목록에서 하나씩 지웁니다.
- 단어장(0.5.3부터, `windows/common/wordbook.cpp`): 내보내기 파일에는 등록한 단어와 기억한 띄어쓰기,
  항목마다 바꾼 시각만 들어 있습니다(지운 기록·기기 표시 없음). 동기화를 켜면 고른 폴더 안의 `Maimusi\`에
  `maimusi-wordbook-<무작위 8자리>.json`을 쓰고 같은 폴더의 다른 기기 파일을 읽어 합칩니다. 이 파일에는
  지운 항목의 시각과 무작위 기기 표시(`deviceID`)도 들어 있고, 기기 이름·사용자 이름은 넣지 않습니다.
  맞추기는 각 앱의 입력기와 설정 앱이 `Local\MaimusiWordbookSync` 뮤텍스로 한 번에 하나씩 하며,
  샌드박스 앱의 입력기는 하지 않습니다. 세반시옷 서버나 네트워크 코드는 쓰지 않고, 폴더를 다른 기기와
  맞추는 일은 그 폴더의 서비스(OneDrive 등)나 사용자가 합니다. 형식은 [WORDBOOK.md](WORDBOOK.md).
- 설정 앱 「띄어쓰기 규칙」의 예문은 설정 앱이 엔진 파이프로 `space` 요청에 지금 규칙(`spacing`)을
  실어 보냅니다(예문만 보내고 저장하지 않음). 엔진은 샌드박스 클라이언트의 `spacing`을 거부합니다.
- 설정 앱 「개인정보」: 이 PC에 남는 것(설정·단어·기억, 「설정 파일 보기」), 기기 밖으로 나가는 것
  (없음, 또는 고른 동기화 폴더)을 보여 줍니다. 파일 기록·OneDrive 폴더 백업·Windows 백업은 기본으로
  `%APPDATA%`를 백업하지 않으며, 디스크 전체 백업에는 설정 파일도 들어갑니다. 제거하면 설정 파일은
  남고(같은 PC에 다시 설치할 때 이어 쓰도록), 동기화 폴더의 단어장 파일도 지우지 않습니다.

## 배포물과 저장소

- `tools/privacy_scan.py`: 빌드 시점에 홈 경로, 로그인 이름, 전역 git 이름·이메일(+`PRIVACY_MARKERS`)을
  모아 앱 번들, pkg(펼친 내용 포함), zip, PyInstaller 내장 아카이브와 파이썬 바이트코드까지 검사합니다.
  찾은 위치만 출력하고 검사어 자체는 출력하지 않습니다. `macos/package.sh`는 검사가 통과해야 끝납니다.
- 빌드는 Rust `--remap-path-prefix`, Swift `-file-prefix-map`으로 빌드 경로를 지우고 바이너리를 strip합니다.
- pkg 페이로드는 cpio로 직접 만들어 확장 속성·AppleDouble 파일이 들어가지 않습니다.
- 개인 말뭉치, 입력 기록, 학습 프로필, 계정 정보는 저장소에 넣지 않습니다. `build/`와 기기별 환경
  파일은 `.gitignore`에 있습니다.
- 커밋 작성자는 저장소 로컬 설정의 익명 placeholder입니다([SIGNING.md](SIGNING.md) 참고).
