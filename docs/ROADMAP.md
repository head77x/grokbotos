# Grok Bot OS 로드맵

설치 후 첫 화면은 Grok Bot이다. 사용자는 기존 계정으로 로그인하거나 구독하고, Grok Bot에게 일을 시킨다. 앱이 필요하면 Flathub에서 설치하거나, Grok Bot이 만든 앱을 사용자 홈에 둔다. OS 업데이트는 bootc가 한다.

체크박스는 두 가지를 섞지 않는다. 코드가 트리에 있으면 `[x]`와 함께 "코드"라고 적는다. 가상머신이나 실기기에서 확인하지 않았으면 그 사실을 같은 줄에 적는다. 이전 AI-OS 이미지에서 확인한 사실을 이 이미지의 확인으로 적지 않는다.

이전 오케스트레이터(상태 머신, 앱 레지스트리, Claude/Grok/Ollama CLI, 개발 에이전트, 웹 셸)는 2026-10-22에 저장소에서 지웠다(보안 리뷰 L: 인증 없는 웹 셸). git 기록에만 있다. 이유는 [`DECISIONS.md`](./DECISIONS.md) 2026-10-18 항목.

## 지금 구조

```text
fedora-bootc
  -> tty1 자동 로그인 (grokbot)
  -> sway 키오스크
  -> grokbot-kiosk (종료되면 재실행)
  -> grokbot-launch
       기본: native. /usr/bin/grok-bot (고정 RPM, app_id grok-bot)
       GROKBOT_DISABLE_BUNDLED_APP=1 이면 Firefox 키오스크
```

앱 설치는 사용자 권한 `grokbot-install` 하나다. Flatpak은 `--user`와 Flathub만. Grok Bot이 만든 앱은 `~/Apps/<id>`와 `~/.local/share/applications/grokbot-local-<id>.desktop`.

## Phase A — 부팅하면 Grok Bot 키오스크

- [x] tty1 자동 로그인 → sway → 단일 실행 진입점 `grokbot-launch` (코드). 계정 이름은 `grokbot`. 홈 디렉터리는 매 부팅 tmpfiles로 보장하고 내용은 유지한다. 이 패턴은 2026-07-11 검은 화면의 수정이다. **이 조합의 부팅은 미확인.**
- [x] 앱이 죽으면 `grokbot-kiosk`가 1초 뒤 다시 실행 (코드). sway는 exec 자식을 재시작하지 않는다.
- [x] 패널, 창 테두리, 데스크톱 아이콘 없음 (sway 설정, 코드).
- [x] 기본 이미지에 Grok Bot 0.71.2 RPM을 amd64와 arm64 모두 넣도록 빌드가 정해져 있다 (코드). 이 환경에서 두 RPM의 sha256, 파일 목록, 스크립트릿을 확인했다. **dnf 설치와 화면 출력은 미확인.**
- [x] 플레이스홀더: `GROKBOT_DISABLE_BUNDLED_APP=1`이면 Firefox `--kiosk`가 로컬 안내 페이지를 연다 (코드, 셸 테스트). **화면 출력은 미확인.**
- [ ] 이 이미지를 amd64와 arm64 VM에서 설치하고, 재부팅 뒤 Grok Bot만 보이는지 확인. 2026-07-09 UTM 확인은 이전 이미지다.
- [ ] Plymouth 스플래시. 넣지 않았다.

**완료 기준:** 클린 설치 → 재부팅 → 다른 데스크톱 없이 Grok Bot(또는 플레이스홀더)만 보인다. 앱을 죽여도 다시 뜬다.

## Phase B — 로그인 / 구독

- [x] 이 OS의 계정 시스템, 토큰 저장, OAuth 클라이언트를 두지 않는다 (코드에서 제거, 이후 저장소에서도 삭제).
- [x] 플레이스홀더 세션은 `~/.local/share/grokbot/firefox-profile`에 남는다 (코드). `grokbot-sign-out`은 그 디렉터리만 지운다 (셸 테스트).
- [x] 네이티브 Grok Bot 0.71.2 RPM을 amd64·arm64 이미지 빌드에 고정했다 (코드, sha256은 이 환경에서 확인). 첫 화면이 그 앱의 로그인/구독인지는 **미확인.**
- [ ] 재부팅 뒤 그 세션이 홈에 남는지, 앱 안 로그아웃 뒤 다시 로그인 화면인지 실기 확인.

**완료 기준:** 설치 직후 첫 화면에서 Grok Bot 로그인 또는 구독을 끝낼 수 있고, 재부팅 후에도 그 세션이 홈 디렉터리에 남아 있다.

## Phase C — 앱 설치

- [x] `grokbot-install flatpak <app-id>`: `flatpak install --user -y flathub` (코드, 가짜 flatpak으로 테스트). 임의 URL 설치는 없다.
- [x] `grokbot-install local`: `~/Apps/<id>`에 복사하고 `.desktop`을 쓴다. 심볼릭 링크와 홈 밖 경로는 거부한다 (셸 테스트).
- [x] `Super+Space` / `Alt+Space`는 fuzzel, `Super+G` / `Alt+G`는 Grok Bot 포커스, `Alt+Tab`과 `Alt+F4`는 유지 (sway 설정, 코드). **키 입력은 미확인.**
- [ ] Flathub에서 앱 하나를 실제로 설치하고 fuzzel로 연 뒤 Grok Bot으로 돌아오는 실기 확인.
- [ ] Grok Bot이 `grokbot-install`을 직접 호출하는 연결. 헬퍼와 규격만 있다. RPM은 이미지 빌드에 들어가 있으나, 앱이 이 명령을 부르는지 확인하지 않았다.

**완료 기준:** Grok Bot(또는 복구 셸)이 Flathub 앱과 로컬 앱을 설치하고, 키오스크에서 그 앱과 Grok Bot을 오갈 수 있다.

## Phase D — Grok Bot이 만든 앱의 권한

로컬 앱은 지금 사용자 `grokbot` 권한으로 그대로 실행된다. Flatpak 앱만 Flatpak 샌드박스를 탄다. 이 단계는 아직 없다.

- [ ] 로컬 앱의 기본 권한: 파일, 네트워크, 장치.
- [ ] 격리 수단 선택 (bubblewrap, Flatpak 매니페스트, 또는 다른 것).
- [ ] Grok Bot이 설치를 요청할 때 사용자가 권한을 볼 수 있는 경로.
- [ ] 홈 디렉터리 전체를 지우는 테스트 앱이 막히는지 확인.

**완료 기준:** Grok Bot이 만든 앱이 허용하지 않은 경로와 장치에 닿지 못한다.

## Phase E — 업데이트, 롤백, 하드웨어 이미지

- [x] bootc 이미지 빌드와 GitHub Actions(`build.yml`, `build-disk.yml`)가 amd64와 arm64를 각각 `grokbotos`, `grokbotos-arm64`로 내도록(2026-10-21 `oais`에서 이름 변경) 정의되어 있다. 디스크 이미지는 qcow2와 anaconda ISO. **이 워크플로 정의는 유지했다. 이 전환 커밋으로 이미지를 만들어 보지는 않았다.** 이전 커밋의 GHCR 푸시와 arm64 ISO 설치는 이전 이미지에서 확인됐다.
- [ ] `bootc upgrade`와 이전 배포로 롤백이 이 이미지에서 동작하는지 확인.
- [ ] `bootc switch`로 기존 bootc 시스템을 이 이미지로 바꾸는 경로. 이전에도 안 했다.
- [ ] amd64 실기 또는 VM 부팅. 이전 확인은 arm64 UTM뿐이었다.
- [ ] 정해진 하드웨어에 구워 넣는 팩토리 이미지.
- [ ] 하드웨어 호환 매트릭스. 전략과 빈 체크리스트는 [`HARDWARE.md`](./HARDWARE.md). 행은 아직 없다. 어떤 기기도 이 이미지로 확인하지 않았다.

**완료 기준:** 설치된 시스템이 레지스트리의 다음 이미지로 원자적으로 올라가고, 실패하면 이전 부팅으로 돌아온다. Nvidia처럼 커널 밖 드라이버가 필요하면 그 변형 이미지의 빌드에 들어 있어야 한다. 부팅한 뒤 `dnf`로 깔아 둔 모듈은 완료로 치지 않는다.

## Phase F — 되팔기, 선물

Omarchy 4의 Reset Computer와 설치 때 새 주인에게 넘기는 흐름에서 가져온 목표다. 그 배포판의 코드를 가져오지는 않았다.

### 컴퓨터 초기화 (Reset Computer)

**목표.** 쓰던 기계를 남에게 넘기기 전에, Grok Bot 세션과 사용자 데이터를 지우고 첫 부팅과 같은 상태로 되돌린다. OS 이미지 자체는 다시 설치하지 않는다.

**설계.** bootc에서 불변인 것은 `/usr`와 ostree 배포다. 지울 것은 `/var`의 사용자 상태다. 홈, 사용자 Flatpak, 컨테이너 상태, 저널, `/etc/machine-id`와 SSH 호스트 키처럼 기계를 식별하는 값. 다음 부팅에서 `systemd`의 첫 부팅 조건이 다시 성립하면 tmpfiles가 빈 `/var/home/grokbot`를 만들고, tty1은 다시 `grokbot`으로 들어간다. 세션 파일이 없으므로 Grok Bot은 로그인/구독 화면으로 시작한다. 확인 없는 단축키로는 실행하지 않는다. 복구 콘솔에서 확인 문구를 받은 뒤에만 지우고, 지우기 전에 목록을 보여 준다.

**완료 기준.** 확인 없이 실행하면 파일이 그대로다. 실행 뒤 `/usr`와 `bootc status`의 배포는 바뀌지 않고, 키오스크 홈과 다른 사용자 홈의 세션이 없으며, 재부팅하면 Grok Bot 로그인/구독만 보인다. 관리자 계정으로 `Ctrl+Alt+F2`에 들어갈 수 있다.

**상태.** 전체 초기화는 구현하지 않았다. 첫 버전 `grokbot-factory-reset`만 있다. `--dry-run`은 지우지 않고 목록만 출력한다. `--confirm RESET`일 때만 `/var/home/grokbot` 안의 내용을 지운다. 홈 디렉터리 자체, `/usr`, `/etc`, `machine-id`, 다른 사용자 홈은 그대로다. 재부팅하지 않고, sway 단축키에 연결되어 있지 않다. 심볼릭 링크와 다른 파일시스템의 마운트는 거부한다. 셸 테스트는 임시 디렉터리만 쓴다. 이 샌드박스의 `/var`에서는 실행하지 않았다. 되팔기에 충분한 초기화로 보면 안 된다.

### 새 주인 설정 (OEM / 선물)

**목표.** 기계를 미리 설치해 두고, 받는 사람의 첫 부팅이 그 사람의 Grok Bot 로그인 또는 구독으로 이어진다. 준비하는 사람의 계정 세션은 디스크에 남지 않는다.

**설계.** 설치(Anaconda kickstart)에 선물 모드를 둔다. 복구용 관리자 계정만 만들고 Grok Bot에는 로그인하지 않는다. `/var/lib/grokbot/oem-handoff` 같은 표시만 남긴다. 첫 부팅은 지금과 같이 tty1 → sway → `grokbot-launch`이고, 홈에 세션이 없으면 Grok Bot이 자기 로그인/구독 화면을 연다. 이 OS는 계정을 만들지 않는다. 준비하는 사람이 이미 로그인했다면, 넘기기 전에 위의 초기화가 그 홈을 비워야 한다. 초기화와 달리 이쪽은 설치 시점의 경로다.

**완료 기준.** 선물 모드로 설치한 디스크에 Grok Bot 설정 디렉터리가 없다. 받는 사람의 첫 화면이 로그인 또는 구독이다. 복구 계정은 준비할 때 만든 그대로다. 준비하는 사람의 토큰이나 프로필이 홈에 없다.

**상태.** 구현하지 않았다. kickstart와 첫 부팅 표시 파일은 없다.

## Phase G — Grok Bot이 만드는 드라이버

베이스는 Fedora bootc를 유지한다. Arch로 바꾸지 않는다. 로컬에서 파생 이미지를 만들고, 실패하면 이전 배포로 돌아오는 이 흐름은 bootc의 배포 모델에 기대어 있다. 설계는 [`HARDWARE.md`](./HARDWARE.md)의 "Grok Bot이 제안하는 드라이버"다.

**목표.** 사용자가 Grok Bot에게 드라이버나 하드웨어 문제를 말하면, Grok Bot이 원인을 보고, 드라이버를 고르거나 만들고, 지금 부팅 중인 bootc 이미지 위에 로컬 이미지를 올린 뒤, 사용자가 확인하면 그 이미지로 전환한다. 첫 부팅이 실패하면 이전 배포로 돌아온다.

**설계.**

1. 진단. `lspci`, `lsusb`, `dmesg`, 실행 중인 커널, 그 커널이 요구하는 펌웨어가 이미지에 있는지를 본다.
2. 선택. 고친 결과는 akmods/DKMS 형태의 커널 모듈이거나, RPM Fusion 또는 `linux-firmware` 패키지다. 소스와 패키지 이름을 로그에 남긴다.
3. 로컬 이미지. `Containerfile`의 `FROM`은 지금 부팅 중인 이미지다. 커널 헤더와 빌드 도구는 빌드 스테이지에만 있고, 마지막 레이어에는 만든 모듈이나 펌웨어만 남긴다.
4. 확인. 적용 전에 사용자가 로그를 보고 승인한다. 승인 없는 적용은 없다.
5. 전환. `bootc switch` 또는 `bootc upgrade`로 그 로컬 이미지에 맞춘 뒤 재부팅한다.
6. 건강 확인. 첫 부팅에서 화면이 뜨는지, 네트워크가 붙는지, Grok Bot이 시작하는지 본다. systemd 유닛이 제한 시간과 부팅 횟수를 센다.
7. 롤백. 건강 확인이 실패하면 그 유닛이 `bootc rollback`으로 이전 배포를 고르고 재부팅한다. 새 배포가 아예 올라오지 못하면 부트 카운터가 이전 항목으로 보낸다.

**안전.**

- 사용자가 확인하기 전에는 `bootc switch`를 하지 않는다.
- 만든 모듈의 출처를 로그로 보여 준다. 서명되지 않은 모듈을 조용히 신뢰하지 않는다.
- Secure Boot가 켜져 있으면 서명 없는 모듈은 로드되지 않는다. MOK 등록은 사용자가 보는 단계이고, Secure Boot를 끄지 않는다.
- 빌드 도구와 헤더는 부팅되는 이미지에 남기지 않는다.
- 임의 URL의 커널 모듈을 확인 없이 받지 않는다.

**완료 기준.** 확인 없이는 배포가 바뀌지 않는다. 승인 뒤에만 로컬 이미지로 전환한다. 건강 확인이 실패하면 이전 bootc 배포로 부팅하고, Grok Bot이 그 사실을 로그로 보여 준다. 성공한 부팅은 그 배포를 유지하고 부팅 횟수를 끝낸다. 실행 중인 이미지에 커널 헤더가 없다. 이 과정은 실기에서 한 번도 실패와 성공을 둘 다 보여 줘야 완료다.

**상태.** 구현하지 않았다. 진단 명령, Containerfile 템플릿, 건강 확인 유닛, 롤백 경로, MOK 절차가 없다. 시험하지 않았다.

## Phase H — 32비트(i386) 레거시 에디션 (나중에, 별도 브랜치)

상태: **시작 안 함**. 메인 이미지와 분리된 브랜치/에디션으로 나중에 따로 개발한다.

- **동기:** 20년 가까이 된 PC에서도 Grok Bot을 쓰게 한다. 예: HP Compaq nw8000 (Pentium M, 32비트, 최대 RAM 2GB).
- **방식:** 32비트 베이스(예: Debian i386) 위에 브라우저만 있는 가벼운 키오스크. Firefox가 Grok Bot 웹 앱을 띄운다. Fedora와 Chromium/Electron은 32비트 지원을 끊었기 때문이다.
- **한계:**
  - bootc 업데이트 없음.
  - grokbotd, 동의(consent) 창, Dock, 한글 입력기(IME) 연동은 처음에는 없다.
  - Firefox 32비트 지원이 언제까지 이어질지 확인해야 한다.
  - RAM 2GB에서 성능을 실측해야 한다.

## 이전 이미지에서 이미 확인된 것

아래는 Grok Bot OS 전환 **이전** 이미지의 기록이다. 다시 확인하기 전에는 이 로드맵의 완료로 세지 않는다.

- [x] `ghcr.io/head77x/oais`(amd64)와 `ghcr.io/head77x/oais-arm64`(arm64) 게시. 커밋 `429f595` 빌드.
- [x] arm64 anaconda ISO와 qcow2 빌드 성공 (Actions run `28999368347`).
- [x] 2026-07-09 Apple Silicon UTM에서 arm64 ISO 클린 설치, 재부팅, 로그인, `bootc status`가 `ghcr.io/head77x/oais-arm64:latest` (digest `sha256:a6461e54...`).
- [x] 그 계열에서 tty1 자동 로그인 뒤 sway가 뜨고 화면이 그려진 적이 있다. 당시 화면은 지금 지운 웹 셸이었다. 검은 화면, Firefox가 로그인 페이지를 같은 창에 흡수한 문제는 `docs/DECISIONS.md`에 있고, 그때 넣은 수정(tmpfiles, 별도 브라우저 창, Alt+Tab, Alt+F4)은 이 트리에 남아 있다.

## 다음에 실기에서 볼 것

1. `main`(`3a55a50`, PR #10)의 `build.yml` → `build-disk.yml`이 녹색인지. 이미지 빌드는 `downloads.cursor.com`에서 RPM을 받는다. 이 저장소에서 그 빌드를 돌리지는 않았다.
2. amd64와 arm64 ISO를 각각 설치하고 재부팅한다.
3. 첫 화면이 Grok Bot인지, 패널이 없는지. 플레이스홀더 페이지가 보이면 RPM이 이미지에 안 들어간 것이다.
4. `Alt+Space`로 fuzzel이 뜨는지. `Alt+G`가 Grok Bot으로 돌아오는지. UTM에서 Super가 안 먹으면 Alt를 쓴다.
5. `~grokbot/.local/share/grokbot/shell.log`에 앱이 죽지 않았는지 (`Ctrl+Alt+F2`).
6. `http` 링크가 별도 Firefox 창으로 열리는지. `Alt+F4`로 닫고 `Alt+G`로 돌아오는지.
