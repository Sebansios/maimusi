# 자동 업데이트

macOS 0.5.3부터 들어간다(`macos/Sources/Updater.swift`). Windows는 같은 형식과 키로 따로 구현한다
Windows 판은 아직 구현하지 않았습니다.

## 동작

1. 설정 「새 버전 자동으로 확인」(`updateAutoCheck`, 기본 켬)이 켜져 있으면 입력기 시작 90초 뒤와 그 뒤 한
   시간마다, 마지막 확인이 23시간 넘게 지났을 때 업데이트 정보를 받는다. 연결에 실패하면 3시간 뒤에
   다시 한다. 입력 메뉴 「업데이트 확인…」과 설정 › 정보 「지금 확인」은 언제든 바로 확인한다.
2. 주소는 Info.plist `HSUpdateURL`(packaging/product.env `UPDATE_URL_MACOS`):
   `https://dl.sebansios.com/maimusi/update/macos.json`. 질의 문자열 없음, `User-Agent: Maimusi`,
   `Accept-Language: ko` 고정, 쿠키·캐시 없음. 지금 판은 보내지 않고 이 Mac에서 비교한다. 404는 「올린
   업데이트 정보 없음」으로 보고 조용히 넘어간다.
3. 서명(아래)이 맞고, 플랫폼이 `macos`, 채널이 `stable`, 빌드가 지금 빌드보다 클 때만 새 버전으로 본다.
   `minimum_os`·`architectures`가 있으면 이 Mac이 맞아야 한다.
4. 자동 확인으로 찾았으면 타자가 4초 멈춘 뒤 화면 오른쪽 위에 알림 창을 띄운다. 키보드 초점을 가져가지
   않는 창이라(`canBecomeKey` false) 치던 키가 단추로 가지 않는다. 직접 확인했으면 결과(최신 버전,
   설치할 수 없음, 실패 이유)를 바로 띄운다.
   - 「업데이트」: 설치 파일을 `~/Library/Caches/HangulSpacing/Updates/<이름>`에 받는다. 서명된 크기보다
     커지면 멈춘다. 다 받으면 크기·SHA-256을 대조하고, 맞으면 `/System/Library/CoreServices/Installer.app`
     으로 연다. 관리자 암호와 설치는 설치 프로그램이 맡고, pkg의 preinstall/postinstall이 입력기를 내렸다
     다시 올린다. 이미 받아 둔 파일이 맞으면 다시 받지 않는다.
   - 「나중에」(닫기 단추도 같음): 24시간 뒤에 다시 알린다.
   - 「이 버전 건너뛰기」: 그 빌드는 자동으로 알리지 않는다. 더 높은 빌드는 알린다.
   - 「자세히」: 업데이트 정보의 `page`(https만).
5. 입력기가 시작할 때, 받아 둔 빌드가 지금 빌드 이하이면 받은 파일 폴더를 지운다.

설치 파일은 ad hoc 서명·공증 없음이라 Gatekeeper가 막을 수 있지만, 앱이 받은 파일에는 격리 속성
(`com.apple.quarantine`)이 붙지 않아 설치 프로그램이 바로 연다. 그래서 출처 확인은 아래 서명이 맡는다.

## 형식

`macos.json`(최대 64 KiB):

```json
{
  "format": "maimusi-update",
  "key": "maimusi-1",
  "payload": "<base64: 아래 JSON의 UTF-8 바이트>",
  "signature": "<base64: Ed25519(\"maimusi-update/1\\n\" + payload 바이트)>"
}
```

payload:

```json
{
  "format": "maimusi-update", "version": 1,
  "platform": "macos", "channel": "stable",
  "product": "0.5.4", "label": "", "build": 33,
  "published": "2026-11-20",
  "notes": ["한 줄 설명", "…"],
  "page": "https://sebansios.com/maimusi",
  "minimum_os": "13.0",
  "architectures": ["arm64", "x86_64"],
  "file": {"name": "Maimusi-0.5.4.pkg", "url": "https://dl.sebansios.com/maimusi/Maimusi-0.5.4.pkg",
           "bytes": 115377837, "sha256": "<소문자 16진 64자>"}
}
```

- 빌드 번호는 플랫폼과 관계없이 계속 올라가므로([개발 안내](DEVELOPMENT.md)) 빌드로만 비교한다.
- `notes`는 알림에 앞의 4줄까지 보인다(도구는 8줄, 줄마다 200자로 제한).
- 파일 이름은 ASCII 글자·숫자·`._-`만, macOS는 `.pkg`. 주소는 https만.
- `minimum_os`, `architectures`, `label`, `published`, `notes`, `page`는 생략할 수 있다.
- 사전 배포(`channel`이 `stable`이 아닌 것)는 지금 앱이 받지 않는다. 베타는 이 경로로 내보내지 않는다.

## 키

- 공개키: `packaging/update-keys.json`. macOS 빌드(`macos/build.sh`)가 Info.plist `HSUpdateKeys`에 넣고,
  키가 하나도 없으면 빌드가 멈춘다. Windows 빌드도 같은 파일을 쓴다.
- 서명 개인키는 Git과 동기화 드라이브 밖의 접근 제한 디렉터리에 보관합니다.
  실제 위치와 백업 기록은 비공개 운영 기록에서 관리하며 공개 소스에 넣지 않습니다.
  서명 도구에는 `--key <개인키>`로 경로를 전달합니다. 키를 잃으면 기존 앱에 새 판을
  알릴 수 없으므로 안전한 별도 백업이 필요합니다.
- 키 교체: `maimusi-1`이 새거나 잃으면 `maimusi-2`로 서명한다(이미 설치된 앱이 둘 다 믿는다). 다음 판에서
  새 예비 키를 `update-keys.json`에 더하고, 새는 키는 그 판을 받은 사용자가 대부분이 된 뒤 뺀다. 판마다
  들어 있는 키 목록을 배포 기록에 적는다.
- 모든 배포(R2 올리기, 업데이트 정보 서명)는 개인키가 있는 Mac에서 한다. Windows 설치 파일의 업데이트
  정보도 Mac에서 `--platform windows`로 서명해 올린다. Windows 기기에는 개인키를 두지 않는다.

## 출시 순서

설치 파일과 해시를 공개 주소에서 대조한 뒤에만 업데이트 정보를 올린다. 올리는 순간 설치된 앱이 알리기
시작한다. `tools/publish_update.py`가 이 순서를 지킨다.

1. 설치 파일(pkg·zip·exe)을 R2 `maimusi/maimusi/<이름>`에 올리고 공개 주소에서 받아 SHA-256을 대조한다.
2. `python3 tools/publish_update.py --platform macos --key /path/to/signing-key.key --file build/dist/Maimusi-0.5.4.pkg --notes notes.txt`
   - 공개 주소의 설치 파일이 로컬과 같지 않으면 멈춘다.
   - 지금 올라가 있는 업데이트 정보보다 빌드가 높지 않으면 멈춘다(설명만 고칠 때 `--allow-same-build`).
   - 서명해 `build/dist/update/macos.json`에 쓰고 도구·빌드한 앱 양쪽 규칙으로 검증한다. 여기까지는 올리지 않는다.
3. 같은 명령에 `--publish`: `npx wrangler r2 object put maimusi/maimusi/update/macos.json`
   (`application/json`, `Cache-Control: max-age=300`, `--remote`)으로 올리고, 공개 주소에서 다시 받아 바이트와
   서명을 확인한다.
4. 비공개 배포 기록에 업데이트 정보를 올린 시각과 서명 키 id를 적는다.

수동으로 할 때:

```sh
K=/path/to/signing-key.key
python3 tools/update_manifest.py sign --platform macos \
  --file build/dist/Maimusi-0.5.4.pkg --key "$K" --notes notes.txt \
  --minimum-os 13.0 --out build/dist/update/macos.json
python3 tools/update_manifest.py verify build/dist/update/macos.json --file build/dist/Maimusi-0.5.4.pkg
# 앱과 같은 규칙인지(빌드한 앱으로):
build/macos.noindex/HangulSpacing.app/Contents/MacOS/HangulSpacing --verify-update build/dist/update/macos.json packaging/update-keys.json
```

- 제품·빌드 번호는 `versions.json`에서 읽는다. 다른 판으로 만들려면 그 판의 커밋에서 실행한다.
- R2 버킷 `maimusi`의 `maimusi/update/macos.json`에 `Content-Type: application/json`,
  `Cache-Control: max-age=300`으로 올린다. 공개 주소에서 다시 받아 `verify`로 확인한다.
- 되돌리기: 잘못 올렸으면 이전 판의 업데이트 정보로 덮어쓴다. 앱은 지금보다 낮은 빌드를 무시하므로
  이미 받은 사용자에게는 영향이 없다. 설치 파일에 문제가 있으면 더 높은 빌드로 고쳐서 낸다.

## 시험

- `HangulSpacing --self-test`: 서명 확인, 바꾼 payload·다른 키·모르는 키·다른 플랫폼·사전 배포·http·잘못된
  해시·64 KiB 초과 거부, 빌드 비교, macOS·아키텍처 조건, 파일 대조.
- `python3 -m unittest discover -s tools/tests -p 'test_update_manifest.py'`: 도구의 서명·검증, 개인키 권한.
- `HangulSpacing --verify-update <정보> <공개키 JSON>`: 도구가 만든 파일을 앱 규칙으로 확인.
- `HangulSpacing --test-update <정보 주소> <공개키 JSON> <지금 빌드> <받을 폴더>`: 실제 요청으로 확인 → 받기 →
  대조까지(설치 프로그램은 열지 않는다). 이 경우에만 `http://127.0.0.1:<포트>` 주소를 받아들인다. 시험 키로
  `tools/update_manifest.py sign --url http://127.0.0.1:…`를 만들고 `python3 -m http.server --bind 127.0.0.1`
  로 내보낸다. 2026-11-10 확인: 정상(받기·대조·열기), 받아 둔 파일 재사용, 서명 뒤 바꾼 설치 파일 거부·삭제,
  상한보다 큰 파일 중단, 바꾼 업데이트 정보 거부, 404는 최신으로, 서버 없음은 실패 안내.
- `HangulSpacing --show-update-sample [초] [--no-glass]`: 실제 알림 창을 띄워 상태를 바꾸며 창 크기를 출력.
- `HangulSpacing --render-update <폴더>`: 알림 상태별 그림(화면 밖).
