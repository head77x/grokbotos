# Grok Bot이 앱을 만들고 올리는 길 / How Grok Bot builds and installs an app

검증: 2026-10-25, VM(TCG), main 이미지 + PR "apps.launch session env". 예제: [`examples/todo-webapp`](examples/todo-webapp/).

1. **소스 쓰기.** Grok Bot은 local-exec로 홈 아래 아무 폴더(예: `~/Projects/todo`)에 `manifest.json`, `index.html`, `app.js`, `style.css`, 아이콘을 쓴다. 인라인 스크립트는 CSP가 막으므로 JS는 파일로 둔다.
2. **설치.** `grokbot-os --json apps.install path=~/Projects/todo` (MCP: `apps_install`). 항상 동의 창이 뜬다(앱 이름, origin, 요청 scope). 같은 id로 다시 설치하면 업데이트이고 창에 이전 버전이 나온다. 설치는 아무 권한도 주지 않는다.
3. **실행.** `grokbot-os --json apps.launch id=todo` 또는 Dock/런처 아이콘. 앱은 `http://todo.app.localhost:7311`에서 자기 Firefox 프로필로 뜬다.
4. **데이터를 파일로.** 앱은 같은 origin의 `POST /v1/rpc`로 `files.read` / `files.write` / `files.mkdir`를 부른다.
   - 처음 부를 때 -32001이 오면 `permissions.request {scope:"files"}`, 쓰기는 `{scope:"files-write"}`로 동의 창을 띄운다.
   - `files.write` 파라미터는 `path`, `data`, `overwrite: true` (`content` 아님). `files.read` 결과는 `data`.
   - 경로는 홈 기준(`/Documents/Todo/todos.json`). 숨김 폴더(`.local` 등)는 files scope로 못 쓴다.
   - 읽기가 "no such file" 말고 다른 이유로 실패하면 빈 목록으로 덮어쓰지 말 것.
5. **브라우저 저장소**(IndexedDB, localStorage)도 앱 프로필에 남는다. 파일이 필요 없으면 scope 없이 이걸 써도 된다(메모 앱).

알려진 한계: 파일로 저장하려면 `files`/`files-write`(홈 폴더 전체) 권한이 필요하다. 앱 전용 데이터 폴더 scope는 아직 없다.
