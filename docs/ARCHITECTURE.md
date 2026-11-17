# 구조

```
 키 입력 (NSEvent)
   │  KeyMapping: 글자 키는 물리 위치(ANSI 키코드)로, 숫자·기호는 시스템 배열 문자로
   ▼
 InputController (Swift, IMKInputController)      ── 클라이언트마다 하나
   │  hc_session_key()                               ▲ commit → insertText
   ▼                                                  │ preedit → setMarkedText
 Session (Rust core)  ────────────────────────────────┘ 후보 → CandidatePanel
   │  Composer: 두벌식 조합, 자모 단위 Backspace
   │  Space → prepare() → backend.space() → checked()
   ▼
 EngineHub (Swift)  ── hc_backend 콜백
   ├─ Kiwi 헬퍼 (Contents/Helpers/HangulEngine.app, JSON 줄 프로토콜, 0.6초 제한)
   └─ 경량 엔진 (Rust NgramModel, spacing.hspm)  ← 헬퍼가 없거나 준비 전·지연·실패 시
```

## 코어 (`core/`)

- `composer.rs`: 두벌식 조합 오토마타. 받침 이동(닭+ㅏ → 달가), 겹모음·겹받침, 자모 단위 되돌리기.
- `session.rs`: 입력기 상태 기계. 조합(띄어쓰기 없는 버퍼) ↔ 변환(띄어쓰기된 어절 목록, 선택 어절,
  후보 목록). 모든 플랫폼이 같은 상태 기계를 씁니다. 수동 분절은 어절 원형을 grapheme 단위로
  나누거나 합치며 확정 시 다시 자동 띄어쓰기를 하지 않습니다. `unicode-segmentation` 1.12.0을
  소스 그대로 vendor하여 오프라인 빌드를 유지합니다.
- `spacing/`: 경량 모델(HSPM 형식, Viterbi 분절)과 텍스트 단위 처리.
  - `prepare`: `간다.그리고` 처럼 문장부호 뒤에 한글이 붙어 있으면 먼저 경계를 넣습니다.
  - `checked`: 엔진 결과가 공백만 다를 때만 받아들이고, 사용자가 직접 넣은 공백을 지우는 결과는 버립니다.
- `romanize.rs`: 로마자 표기. 표준 발음 모형(연음·겹받침, ㅎ 탈락·격음화, 구개음화, 중화, 비음화,
  ㄹ의 비음화, 유음화)을 거쳐 2000년 개정안과 매큔라이샤워식(유성음화, k'·ch', n'g, ŏ·ŭ, shwi)을 만들고,
  예일식은 철자 기준으로 옮긴다(모호한 음절 경계에 마침표). 모든 한글 어절이 후보를 갖도록 세 표기를
  후보 목록 맨 아래에 붙이고, 한글이 없는 어절은 전각·반각 변환을 붙인다. ㄴ 첨가·명사 격음화 예외 등
  형태 정보가 필요한 규칙은 다루지 않는다.
- `ffi.rs` + `include/hangul_core.h`: C ABI. 문자열 범위는 UTF-16 단위(AppKit·Windows·Java와 동일).

## 키 처리

| 상태 | 키 | 결과 |
|---|---|---|
| 비어 있음 | Space, Enter, Backspace, 방향키, 단축키 | 앱으로 그대로 전달 |
| 비어 있음 | 기호 | 바로 입력 |
| 조합 중 | 글자·숫자 | 버퍼에 추가 |
| 조합 중 | Space | 띄어쓰기 → 변환 상태 |
| 조합 중 | Shift+Space | 친 그대로 확정 + 공백 (자동 띄어쓰기 없음, 일반 두벌식과 같음) |
| 조합 중 | Enter / Tab / 방향키 / 단축키 / 클릭 | 띄어쓰기해서 확정 후 키 전달 (Enter 전달은 설정) |
| 조합 중 | Esc | 띄어쓰기 없이 확정 후 Esc 전달 |
| 변환 중 | 글자 | 결과 + 공백 확정, 새 조합 시작 |
| 변환 중 | 닫는 문장부호 `.,?!)` 등 | 결과 + 부호 확정 |
| 변환 중 | Space | 선택 어절의 다음 후보, 후보가 없으면 결과 + 공백 확정 (설정: 바로 확정) |
| 변환 중 | ←→ / ↑↓ / 1–9 | 어절 선택 / 후보 / 후보 고르기 |
| 변환 중 | Shift+← / Shift+→ | 오른쪽 경계를 grapheme 하나 줄이기 / 늘리기. 다음 어절이 비면 합침, 영향받은 후보 캐시 초기화 |
| 변환 중 | 앞과 합치기 / 뒤와 합치기 버튼(Windows 후보 창만) | 인접 어절 합치기 |
| 변환 중 | Enter | 결과 확정 (키는 소비) |
| 변환 중 | Esc | 후보가 열려 있으면 후보 취소, 아니면 원문으로 |
| 수동 경계를 고치지 않은 변환 중 | Backspace | 원문으로 돌아가 마지막 글자 삭제 |
| 수동 경계 수정 후 또는 확정 텍스트 재편집 중 | Backspace | 현재 표시문 끝의 grapheme 삭제, 수동 경계와 Esc용 원문 유지 |
| 조합 없음 + 문서 텍스트 선택 | Control+Shift+R | 정확한 IMK 선택 영역을 읽어 수동 변환 상태로 진입 |

재진입은 `SelectionEditing`이 selectedRange·actualRange·UTF-16 길이를 대조한 다음
`hc_session_edit_selection`을 호출합니다. 첫 `setMarkedText`만 원래 문서 선택 범위를
replacementRange로 쓰고, 그 뒤에는 IMK의 현재 marked range를 사용합니다. 외부 선택에서
시작한 변환은 Esc 시 원문을 그대로 commit하여 복원합니다. 자세한 제약은
[SEGMENT_EDITING.md](SEGMENT_EDITING.md)에 있습니다.

`MarkedTextState`는 IMK controller와 독립 AppKit harness가 공유하는 표시 상태입니다.
재편집 내용을 모두 지우면 client marked range를 비우기 직전의 문서 위치만 유지하여 Esc가
원문을 정확히 복원하도록 합니다. 확정·reset 이후에는 이 위치를 폐기합니다.

## 성능 (Apple Silicon, 이 저장소의 자가 시험 기준)

- Kiwi: 한 문장 Space 처리 약 0.3–2ms(프로세스 간 통신 포함). 헬퍼 시작 약 2초, 메모리 600–850MB.
  20분(설정 가능) 쓰지 않으면 헬퍼를 종료하고, 다음 입력 때 다시 띄웁니다. 그동안은 경량 엔진이 처리합니다.
- 경량: 글자당 약 15µs(형태 사전 포함), 모델 8.5MB.

## 설치 위치 (중요)

macOS의 입력기 실행 에이전트(`imklaunchagent`)는 `/Library/Input Methods`에 있는 입력기만 띄웁니다.
같은 번들을 `~/Library/Input Methods`에 두면 입력 소스는 목록에 보이지만 실행 요청이
`LaunchInputMethod() Error, status=-50`으로 거부되어 **키가 아무것도 입력되지 않습니다**
(2026-09, macOS 27에서 정상 입력기인 구름 복사본으로도 같은 결과를 재현). 그래서 설치 패키지는
시스템 폴더에만 설치하며 관리자 암호가 필요합니다. 같은 번들 ID의 사본이 LaunchServices에 여럿
등록되지 않도록 빌드 산출물은 `.noindex` 폴더에 두고 빌드 후 등록을 해제합니다.

샌드박스 앱(시스템 설정의 키보드 화면, TextEdit 등)은 입력 소스 캐시를
`$(getconf DARWIN_USER_CACHE_DIR)<번들ID>/com.apple.IntlDataCache.le*`에 따로 두고, 새 입력기가 설치돼도
갱신하지 않습니다. 이 상태면 입력 소스 추가 목록에 나오지 않고, 선택해도 곧바로 이전 입력 소스로
돌아갑니다. 설치 후 스크립트가 이 앱별 캐시를 지우므로, 설치할 때 열려 있던 앱은 다시 열면 됩니다.

진단: `log stream --predicate 'process == "imklaunchagent" OR subsystem BEGINSWITH "org.hangulspacing"'`.
입력기는 수명 주기(서버 시작, 컨트롤러 생성, 헬퍼 준비·실패)만 기록하고 입력 내용은 기록하지 않습니다.

## 알려진 한계

- 두벌식만 지원. 세벌식 등은 미구현입니다.
- 확정한 문장은 사용자가 선택 후 명시적으로 재편집한 범위만 읽습니다. IMK 선택 영역을
  제공하지 않는 앱과 여러 줄 선택은 재편집할 수 없습니다.
- Kiwi 헬퍼는 arm64 전용입니다. Intel Mac에서는 경량 엔진만 동작합니다.
- 0.3.0 감사에서 나온 Kiwi 오분석(`공활한데` → `공 활한데`, 복합명사 과결합 등)은 아직 고치지 않았습니다.
