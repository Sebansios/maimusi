# Linux

Linux 입력기는 아직 구현되지 않았습니다. Linux에서 공용 Rust 코어와 Python 엔진의
회귀 시험을 수행할 수 있으며, 이것은 데스크톱 입력기 지원과 구분합니다.

## 구현 경계

- 조합·후보·수동 분절은 `core/`의 세션과 `core/include/hangul_core.h`를 재사용합니다.
- 찰떡 엔진의 요청·응답 형식은 `engine/hangul_ime/ime_service.py`를 공유합니다.
- Linux 어댑터·설정·데스크톱 연동은 이 폴더에, 설치 리소스는 구현 시
  `packaging/linux/`에 둡니다. 공용 코드와 OS별 API를 분리합니다.
- IBus와 Fcitx 5 연동 방식을 비교한 뒤 첫 지원 대상을 결정합니다.
  Wayland·X11, GNOME·KDE, GTK·Qt·Electron의 조합·확정·후보 위치·재변환을 확인합니다.
- 엔진 프로세스는 사용자별로 실행하고 IPC 권한·제한 시간·경량 대체·입력 비기록
  원칙을 유지합니다. 설정과 cache는 XDG 경로를 사용하며 저장소 안에 쓰지 않습니다.
- 클라이언트가 UTF-8 byte offset이나 문자 수를 요구하면 어댑터에서 C ABI의
  UTF-16 범위로 변환합니다. 한글·결합문자·이모지의 선택 범위를 시험합니다.

## 현재 가능한 검사

```sh
python tools/dev.py check
```

CI의 Linux 공통 시험과 향후 Linux 데스크톱 종단 시험은 별도 단계로 유지합니다.
구현 전에는 설치 패키지나 Linux 지원 완료를 표시하지 않습니다.

참고: [IBus](https://github.com/ibus/ibus/wiki),
[Fcitx 5 개발 문서](https://fcitx-im.org/wiki/Develop).
