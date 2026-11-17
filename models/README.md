# 경량 띄어쓰기 모델

입력기에 내장되는 경량 엔진의 모델(`*.hspm`)은 **저장소에 넣지 않습니다**. 빌드하는 기기에서 만들거나
보관본을 복사해 쓰고, 배포물에는 입력기와 함께만 들어갑니다.

## 형식

`HSPM` v1: 음절 n-gram·형태 자질의 로그 오즈 가중치와 어절 보너스, 체언·어간 목록을 정렬된 표로
담은 바이너리입니다. 해시 표를 만들지 않고 파일을 그대로 이진 탐색하므로 메모리 사용량이 파일
크기와 같습니다. 형식은 `core/src/spacing/model.rs` 머리말에 있습니다.

## 현재 모델

| 파일 | 원본 | 크기 | 비고 |
|---|---|---:|---|
| `nikl-morph.hspm` | 참조 구현의 `spacing_model_nikl_morph.json` + `morph_lex.json` | 8.5MB | 국립국어원 모두의 말뭉치 구어 약 3만 문장으로 학습 |

```bash
python3 tools/convert_ngram_model.py spacing_model_nikl_morph.json morph_lex.json \
    -o build/models/nikl-morph.hspm
core/target/release/hc-tool eval build/models/nikl-morph.hspm <gold.txt>...
```

변환 결과는 참조 파이썬 구현과 같은 점수를 냅니다(형태 사전 없이 NIKL 지역어 자료의 표준어 대역 91.2 / 일상대화 92.2 /
일상대화22 92.1 / 메신저 68.7, 참조 재계산값과 일치).
기존에 ‘방언’으로 표시했던 집합은 `form` 표준어 대역이었으므로 실제 지역어 성능을 뜻하지 않습니다.

## 문자 경계 보정 모델 (정본)

정본은 OPELA를 뺀 NIKL 학습판 `boundary-refiner.npz`(SHA-256 `91c644bb6b26809b83a4a9b36c36c30d2abc16d4c79f0848e46dcc5e3a3a3c03`,
빌드 위치 `build/models/refiner-public/`)이다. 국립국어원 공개 승인(2026-10-14)에 따라 0.5.0 Beta 2부터 Kiwi 헬퍼 안
`hangul_ime/models/`에 들어간다(`REFINER=build/models/refiner-public ./macos/build.sh`). 학습·비교 근거는
내부 학습·비교 기록에 보존합니다. [배포 범위](../docs/LICENSING.md)를 참고하세요.

헬퍼는 `HANGUL_SPACING_REFINER` → 사용자 폴더(`~/Library/Application Support/HangulSpacing/models/boundary-refiner.npz`)
→ 번들 모델 순으로 찾는다. 파일이 없거나 유효하지 않으면 기존 Kiwi 경로를 쓰고, `ready`·`ping`의 `refiner`로 실제
모델 해시와 상태를 확인한다. 0.4.6 연구판(`fbbc743b…`, OPELA 포함)은 퇴역시켜 `build/models/retired/`에만 두며 배포하지 않는다.

모델 가중치·원문·학습 cache는 저장소에 넣지 않는다.

## 배포 조건

- 국립국어원이 2026-10-14에 두 모델(경량 모델, 경계 보정 모델)의 공개를 승인했습니다. 오픈소스 라이선스가 아니며
  이 소프트웨어의 일부로만 재배포합니다([../docs/LICENSING.md](../docs/LICENSING.md), `THIRD_PARTY_NOTICES.md`).
- Windows 판은 `nikl-morph.hspm`을 설치 폴더의 `spacing.hspm`으로 넣습니다(`windows/build.ps1 -Model`).

## 다음 과제

- 모바일 키보드용으로는 정확도가 더 높은 소형 신경망(음절 CNN 등)을 같은 디코더 뒤에 붙이는 것이
  다음 단계입니다.
