# 코드 서명·공증과 개인정보

배포물에 붙는 서명 명의는 사용자가 볼 수 있는 공개 정보입니다. 플랫폼마다 "무엇이 드러나는지"와
"드러나지 않게 하는 방법"이 다릅니다. (2026-09 기준 정리. 정책은 바뀔 수 있으니 등록 전에 각
플랫폼의 최신 안내를 확인하세요.)

## 요약

| 플랫폼 | 공식 서명에 드러나는 것 | 실명을 숨기는 현실적인 방법 |
|---|---|---|
| macOS (Developer ID + 공증) | 인증서 이름 `Developer ID Application: <법적 이름> (<팀 ID>)` | 법인(회사) 명의 가입. 개인 계정은 법적 이름이 그대로 표시됨 |
| macOS (서명 없음·ad-hoc) | 없음 | 가능. 대신 첫 실행 때 "확인되지 않은 개발자" 경고 → 사용자가 설정에서 허용 |
| Windows (Authenticode) | 게시자 이름 = 인증서 주체(개인이면 실명) | OSS용 무료 서명 서비스(SignPath Foundation 등)는 게시자가 재단 명의로 표시됨. 또는 서명 없이 배포 |
| Android (APK 서명) | 인증서 DN은 자유 입력(가명 가능) | 직접 배포·F-Droid는 가명 가능. Google Play와 2026년부터 단계 시행되는 "개발자 인증"은 신원 확인 필요 |
| iOS (App Store) | 판매자 이름 = 개인이면 법적 이름 | 법인 명의 가입. EU에서 "거래자"로 등록하면 주소·연락처도 공개 |

## macOS

- **지금 빌드**는 ad-hoc 서명(`codesign -s -`)입니다. 개인 정보가 전혀 들어가지 않지만 Gatekeeper가
  인증하지 않으므로, 다운로드한 pkg를 처음 열 때 사용자가 **시스템 설정 → 개인정보 보호 및 보안 →
  그래도 열기**를 눌러야 합니다.
- **Developer ID + 공증**을 하려면 Apple Developer Program(연 99달러)에 가입해야 합니다. 개인 계정의
  인증서에는 **가입자의 법적 이름**이 들어가고, 누구나 `codesign -dv` 또는 설치 화면에서 볼 수
  있습니다. 가명·닉네임은 허용되지 않습니다.
- 실명을 숨기려면 **법인 명의 조직 계정**이 필요합니다(D-U-N-S 번호, 법인 등기). 일본이라면 합동회사,
  한국이라면 법인 설립 수준이며, 개인사업자 상호는 일반적으로 조직 계정으로 인정되지 않습니다.
- 스크립트는 준비되어 있습니다: `SIGN_IDENTITY="Developer ID Application: …" ./macos/build.sh`,
  `INSTALLER_IDENTITY="Developer ID Installer: …" ./macos/package.sh` 후 `xcrun notarytool submit … --wait`
  와 `xcrun stapler staple`.

## 권장 순서

1. 지금: 서명 없이(ad-hoc) GitHub Releases에 배포하고, README에 "그래도 열기" 절차와 SHA-256을
   적습니다. 개인 정보는 드러나지 않습니다.
2. 사용자가 늘어 경고가 부담이 되면 그때 명의를 결정합니다: 실명 공개를 감수한 개인 계정 또는
   법인 계정.
3. Windows는 SignPath Foundation 같은 OSS 서명 프로그램을 신청하면 게시자가 재단 명의로 표시되어
   실명이 드러나지 않습니다(프로젝트가 OSI 승인 라이선스여야 하고 심사가 있습니다).

## 서명과 별개로 지킬 것

- git 커밋 작성자: 이 저장소는 로컬 설정으로 익명 placeholder를 씁니다. 새 GitHub 계정을 만들면
  `git config user.name "<계정명>"`, `git config user.email "<ID>+<계정명>@users.noreply.github.com"`
  으로 바꾸고, 공개 전에 기존 커밋 작성자도 바꿉니다(`git rebase -r --root --exec 'git commit --amend --no-edit --reset-author'`).
- GitHub 설정에서 "Keep my email addresses private"와 "Block command line pushes that expose my email"을 켭니다.
- 저작권 표기(`Copyright © 2026 …`)에는 실명이 필요 없습니다. 계정명이나 "… contributors"로 충분합니다.
- 번들 ID(`org.hangulspacing.inputmethod.HangulSpacing`)는 공개 전에 확정하세요. 바꾸면 기존 사용자는
  입력 소스를 다시 추가해야 합니다. `io.github.<계정명>.inputmethod.…` 형식이 흔합니다.
