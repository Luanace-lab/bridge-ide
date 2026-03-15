Browser detection lab fixtures for authorized local tests.

Files:
- `navigator_header_storage.html`: Baseline probe for navigator fields, query-param header hints, cookies, storage, IndexedDB, and service worker capability.
- `iframe_probe.html`: Same-origin iframe probe that loads the baseline page and captures both direct access and `postMessage` output.
- `worker_probe.html`: Worker and SharedWorker probe page.
- `worker_probe.worker.js`: Dedicated worker probe script.
- `shared_worker_probe.shared.js`: SharedWorker probe script.
- `popup_probe.html`: Popup probe page that opens the baseline page and waits for a `postMessage` result.
- `permissions_media_probe.html`: Probe page for permission API coherence, notification state, media device capabilities, and storage persistence surfaces.

Notes:
- These fixtures are static and ASCII-only.
- Header inspection is represented via `header_*` query parameters so local test servers can mirror request headers into the page without modifying the fixture files.
- The baseline page posts its probe result to `parent` and `opener` when embedded or opened as a popup.
