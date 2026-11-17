# 라이선스

## 저장소 자체 소스: 기본 저작권 유지

자체 소스와 문서는 `Copyright © 2026 Sebansios. All rights reserved.`로 공개합니다.
[루트 LICENSE](../LICENSE)는 저작권과 현재의 이용 허락 범위를 안내하는 고지입니다.
GitHub 약관에 따른 열람·포크와 법령상 권리는 유지하며, 공개 자체로 별도의
오픈소스 재사용·수정·재배포 허락을 부여하지 않습니다.
제3자 구성 요소는 해당 라이선스를 계속 따릅니다.

공식 배포 패키지의 무료 사용은 아래 EULA로 별도 허용합니다.
소스 고지와 제품 EULA를 구분하며, 학습 말뭉치·제한 모델을 이 저장소에 포함하지 않습니다.

## 자체 코드: 무료 배포 사용권 계약 (0.5.0부터)

현재 배포 패키지의 자체 코드(core, macos, windows, engine의 원저작 부분, tools)는 **무료 배포용 최종 사용자
사용권 계약(EULA)**으로 배포합니다. 소스 공개는 기존 제품 배포 조건을 변경하지 않습니다.
공개 절차는 [공개 소스 관리](PUBLIC_SOURCE.md)를 따릅니다. 원문은 [`packaging/LICENSE.txt.in`](../packaging/LICENSE.txt.in)이며,
빌드할 때 [`packaging/product.env`](../packaging/product.env)의 제품명·게시자(Sebansios)·웹사이트·문의
메일을 채워 앱의 `Contents/Resources/Licenses/LICENSE.txt`(Windows는 설치 폴더의 `Licenses\LICENSE.txt`),
설치 프로그램의 사용권 계약 화면, 배포 zip에 넣습니다.

요점: 개인·업무용 무료 사용, 설치 대수 제한 없음 / 판매·공식 배포처 외 재배포·수정 배포 금지 /
베타 고지 / 입력 내용 비수집 / 제3자 오픈소스 라이선스 우선(LGPL 라이브러리 교체·디버깅 목적 분석 허용) /
무보증 / 책임 제한(고의·중과실 제외, 약관규제법 고려) / 대한민국 법 준거.

저작권 표기는 `Copyright © 2026 Sebansios. All rights reserved.`이며 실명과 개인 메일은 어떤 배포물에도
넣지 않습니다. 향후 자체 소스의 이용 조건을 변경할 수 있으나, 외부 기여자의 권리와
제3자 구성 요소의 조건은 별도로 확인합니다.
이 계약서는 법률 자문을 거친 문서가 아니므로, 유료화나 기업 배포 전에는 전문가 검토를 받습니다.

## 제3자 구성 요소와의 관계

- **Kiwi / kiwipiepy / 모델 (LGPL)**: 별도 헬퍼 프로세스로 실행되고 파일이 교체 가능한 형태로 들어
  있습니다. 자체 코드는 어떤 라이선스든 괜찮고, 배포물에 LGPL 전문·고지·소스 위치를 넣으면 됩니다
  (빌드가 `Licenses/engine/`에 자동 수집).
- **libhangul 한자 사전 데이터 (BSD-3-Clause)**, **Unicode Emoji / CLDR (Unicode License v3)**:
  고지 유지 조건만 있습니다.
- **PyInstaller 부트로더**: GPL + 예외 조항으로, 동결한 프로그램의 배포를 제한하지 않습니다.
- **Windows 파이썬 런타임**: 동결한 엔진에 python313.dll과 함께 OpenSSL(Apache-2.0)·libffi(MIT) 등과
  Microsoft 재배포 런타임(VCRUNTIME140, UCRT)이 들어갑니다. 이 고지와 Microsoft 배포 조건은 Windows용 Python의
  `LICENSE.txt`에 있고 빌드가 `Licenses/engine/Python-LICENSE.txt`로 복사합니다. Microsoft 배포 조건(최종 사용자가
  재배포 코드를 보호하는 조건에 동의할 것)은 EULA 제5조에 넣었습니다. 입력기 DLL·설정 프로그램은 C 런타임을 정적
  링크합니다(/MT).

## NIKL 학습 모델 (2026-10-14 공개 승인)

경량 모델(`spacing.hspm`)과 경계 보정 모델(`boundary-refiner.npz`)은 국립국어원 「모두의 말뭉치」로 학습했다.
말뭉치 이용 약정(이용 목적 「한국어 띄어쓰기 모델 평가」, 이용 기간 ~2027-01-01) 제3조 1항에 따라 언어정보나눔터
「결과물 공개 신청」으로 승인을 받았다(신청 2026-10-07, 결과물 형태 「인공지능 모델/서비스/제품」, 공개 대상 외부(전체),
공개 위치 https://www.sebansios.com/maimusi, 승인 확인 2026-10-14). 승인 화면에는 별도 조건이 없어, 신청서에 적은
범위(두 모델을 매무시에 넣어 무료·비영리로 배포, 출처 표기)를 조건으로 본다.

- 출처 표기(약정 제3조 2항): `THIRD_PARTY_NOTICES.md`, 배포 README, 배포 페이지.
- 두 모델은 오픈소스가 아니며 매무시의 일부로만 배포한다(EULA 제2조).
- 경계 보정 모델은 OPELA(CC BY-NC-SA 4.0)를 뺀 학습 자료로 다시 학습한 판만 배포한다. 0.4.6 연구판
  (`fbbc743b…`, OPELA 2만 행 포함)은 배포하지 않는다. OPELA는 평가에만 쓴다.
- 이용 기간이 끝나면 말뭉치 원본·추출본·학습 cache를 파기한다(약정 제3조 8항). 이후 모델 재학습은 재신청이 필요하다.

빌드: `MODEL=build/models/nikl-morph.hspm REFINER=<boundary-refiner.npz가 든 폴더> ./macos/build.sh`.
Windows: `windows\build.ps1 -Model build\models\nikl-morph.hspm -Refiner build\models\refiner-public -EnginePython <python.exe>`.

## 소스 저장소와 모델의 구분

위 제품 배포 승인과 제3자 조건은 소스 저장소의 학습 자료·모델 재배포 허가를 뜻하지 않습니다.
학습 원문과 두 모델 파일은 소스 Git에 포함하지 않습니다. [모델 준비](../models/README.md)를 참고하세요.
