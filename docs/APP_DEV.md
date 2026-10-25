# Grok Bot이 앱을 만들고 올리는 길 / How Grok Bot builds and installs an app

검증: 2026-10-25, VM(TCG), main 이미지 + PR "apps.launch session env". 예제: [`examples/todo-webapp`](examples/todo-webapp/).

1. **소스 쓰기.** Grok Bot은 local-exec로 홈 아래 아무 폴더(예: `~/Projects/todo`)에 `manifest.json`, `index.html`, `app.js`, `style.css`, 아이콘을 쓴다. 인라인 스크립트는 CSP가 막으므로 JS는 파일로 둔다.
2. **설치.** `grokbot-os --json apps.install path=~/Projects/todo` (MCP: `apps_install`). 항상 동의 창이 뜬다(앱 이름, origin, 요청 scope). 같은 id로 다시 설치하면 업데이트이고 창에 이전 버전이 나온다. 설치는 아무 권한도 주지 않는다.
3. **실행.** `grokbot-os --json apps.launch id=todo` 또는 Dock/런처 아이콘. 앱은 `http://todo.app.localhost:7311`에서 자기 Firefox 프로필로 뜬다.
4. **데이터는 앱 전용 폴더에.** 매니페스트에 `"grokbot": {"scopes": ["app-data"]}`를 쓰고 `<script src="/_grokbot/appdata.js"></script>`를 넣는다.
   - `GrokAppData.readJSON("todos.json", 기본값)`, `writeJSON`, `read`, `write`, `list`, `mkdir`, `remove(path, recursive)`. RPC로는 `appdata.read/write/list/mkdir/delete`.
   - 실제 위치: `~/.local/share/grokbot/app-data/<앱 id>/`. 경로는 이 폴더 기준이고 `..`, 심볼릭 링크 탈출은 거부된다. 파일 16 MB, 앱당 100 MB, 5000개까지.
   - 설치된 앱이면 동의 창 없이 바로 된다. 다른 앱은 이 폴더를 못 읽는다(호출한 origin으로 앱을 판단). 사용자가 Settings에서 거부하면 거부가 이긴다.
   - `apps.uninstall`은 이 폴더도 지운다(`keep_data=true`면 남김).
   - 사용자 문서(`~/Documents` 등)를 다뤄야 할 때만 `files`/`files-write`를 `permissions.request`로 따로 요청한다.
5. **브라우저 저장소**(IndexedDB, localStorage)도 앱 프로필에 남는다. 파일이 필요 없으면 scope 없이 이걸 써도 된다(메모 앱).

알려진 한계: app-data는 웹 앱(origin) 전용이다. 로컬 CLI/MCP 호출자는 이 scope로 거부된다.
