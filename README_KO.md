# DCSS 한국어 협동 포크

공식 Dungeon Crawl Stone Soup 0.34.1을 기반으로 한국어 협동 멀티플레이를
만드는 작업 공간이다. 원본 라이선스와 크레딧은 `LICENSE`와
`crawl-ref/CREDITS.txt`에 보존되어 있다.

## 바로 웹에서 플레이

현재 Windows PC에서 그래픽 WebTiles판을 바로 실행할 수 있다.

1. 프로젝트 최상위의 `PLAY_WEB.cmd`를 더블클릭한다.
2. 자동으로 열리는 `http://127.0.0.1:8080/`에서 플레이한다.
3. 끝낼 때는 `STOP_WEB.cmd`를 실행한다.

서버가 이미 실행 중이면 `PLAY_WEB.cmd`는 기존 플레이 세션을 보호하기 위해 새 탭을
열지 않는다. 브라우저를 닫았다면 위 로컬 주소를 직접 열면 된다.
다시 컴파일해야 할 때는 `BUILD_WEB.cmd`를 사용한다. 첫 전체 빌드는 오래 걸릴 수
있지만 이후 빌드는 변경된 파일만 처리한다. 서버 로그는
`.webtiles-runtime/webtiles.log`와 `.webtiles-runtime/webtiles-error.log`에 남는다.

WebTiles 전용 서버는 현재 `0.0.0.0:8080`에서 대기하므로 같은 LAN의 PC와 휴대폰은
`http://서버-PC의-IP:8080/`으로 접속할 수 있다. 인터넷에 공개할 때는 8080 포트를
그대로 노출하지 말고 HTTPS 역방향 프록시와 방화벽을 앞에 두어야 한다. P2P 연결은
공개 STUN과 호스트 방식 WebRTC 데이터 채널을 사용하며, 대칭 NAT 환경까지 안정적으로
지원하려면 운영 서버에 TURN을 추가해야 한다.

## 한글화 범위

- DCSS 0.34.1의 현재 설명 키 3,778개를 모두 한국어 데이터베이스에 포함했다.
- 전투 메시지와 메뉴 등 현재 C++ 소스에서 추출한 고정 문구 13,215개를 정확한
  영문 키 기반 한국어 카탈로그로 제공한다.
- WebTiles의 로비, 로그인, 계정 복구, 채팅, 관전, 액션 패널과 모바일 조작 문구를
  한국어로 제공한다.
- 예전 한국어 번역과 정확히 일치하는 문장은 재사용했고, 나머지는 HPLT 번역 모델로
  채운 초안이다. 키 누락은 없지만 자동 번역 문장은 계속 사람의 검수가 필요하다.

전체 키와 서식 토큰은 다음 명령으로 다시 검사할 수 있다.

```powershell
python .\crawl-ref\source\util\i18n\audit_korean.py `
  --base .\crawl-ref\source\dat\descript `
  --korean .\crawl-ref\source\dat\descript\ko `
  --catalog .\crawl-ref\source\dat\strings\ko\messages.txt
```

## 현재 단계

완료된 기반은 다음과 같다.

- 한국어 설명 데이터 기본 활성화
- 시간제한 방 턴, 자동 대기 및 자동 AFK
- 동시 이동 충돌과 공정한 순환 우선순위
- 다운, 구조, 관전 및 다음 층 합류 규칙
- 계단 집결과 파티 맵 이동 규칙
- 모바일 방향패드, 빠른 행동, 턴 표시줄, 정보 서랍
- `USE_MULTIPLAYER` C++ 빌드의 활성 플레이어 컨텍스트 전환
- Windows MSYS2에서 실행되는 그래픽 WebTiles 빌드와 원클릭 실행/종료
- 390×844 모바일 화면의 방향패드, 확인 버튼, 빠른 행동과 팝업 폭 대응
- 제목·월드 설정·최대 인원·턴 시간을 지정하는 공개 방 생성
- 전용 서버 방 목록, 대기방 방장 이양, 시작 후 플레이어 난입 잠금
- 시작 전후 관전 입장과 호스트 중심 WebRTC P2P 시그널링/데이터 채널
- 일반 DCSS 기본값, 무작위/지정 시드, 디센트와 스프린트별 독립 월드 디렉터리

현재 완성되어 직접 플레이할 수 있는 범위는 한국어 WebTiles 싱글플레이이다.

방 생성·검색·입장·시작 잠금·관전과 실제 P2P 연결은 브라우저에서 동작한다. 다만
참가 플레이어의 입력을 각자의 C++ 액터에 적용하는 공유 월드 실행 루프는 아직
완성되지 않았다. 현재 방장은 게임 프로세스를 소유하고 나머지 접속자는 같은
WebTiles 스트림을 받는다. 다음 엔진 단계는 각 플레이어의 고유 ID, 위치, 시야와
입력 큐를 이 프로세스의 C++ 공유 월드에 연결하는 것이다. 상세 기준은
`crawl-ref/docs/develop/multiplayer_ko.md`에 있다.

## 이번 단계에서 추가된 공유 월드 경계

- C++ `multiplayer::room`이 최대 8명의 플레이어와 방 내부 숫자 ID를 관리한다.
- 각 플레이어는 서로 다른 `mid_t` actor ID와 위치를 가지며 `actor_at()`과
  `actor_by_mid()`가 활성 방 안의 동료도 찾는다.
- 플레이어 행동을 처리하는 동안 `you`, 탐험 지도, 망각 지도, 현재 가시 셀과 이동
  흔적을 해당 플레이어 상태로 교체하고 범위를 벗어나면 원래 상태로 복원한다.
- C++ 턴 큐는 서버가 정한 우선순위대로 한 명당 한 명령만 받고, 빠진 입력은 자동
  대기로 채운다.
- WebTiles 브리지는 모바일/웹의 원시 키 중 한 턴짜리 명령만 허용하고, 인증된
  플레이어 ID와 명령 이름을 `multiplayer_command_batch` 스키마 1로 직렬화한다.

WebSocket 방 수명주기와 WebRTC 연결은 완료되었다. 이제 C++ 배치 실행 루프를 연결하고,
모든 플레이어 행동 뒤에 몬스터가 한 번만 움직이도록 `world_reacts()`를 분리하는
작업이 남아 있다. 메뉴·주문·능력처럼 여러 번의 입력이 필요한 명령도 플레이어별
UI 세션으로 분리해야 한다.

## Windows WebTiles 빌드

이 작업 공간에는 WebTiles 빌드용 MSYS2 패키지와 프로젝트 전용 Python 가상환경이
준비되어 있다. 최상위에서 다음을 실행한다.

```powershell
.\BUILD_WEB.cmd
```

직접 빌드하려면 다음과 같다.

```powershell
C:\msys64\usr\bin\bash.exe .\scripts\build-webtiles.sh
```

웹용 실행 파일은 `crawl-ref/source/crawl.exe`, 보존한 콘솔판은
`crawl-ref/source/crawl-console.exe`이다.

## 서버 규칙 테스트

```powershell
C:\msys64\usr\bin\bash.exe .\scripts\test-webtiles.sh
```

모바일 JavaScript 문법 검사는 다음과 같다.

```powershell
node --check '.\game_data\static\mobile_controls.js'
node --check '.\game_data\static\game.js'
```
