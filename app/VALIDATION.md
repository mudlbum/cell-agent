# v0.5 validation — 2026-09-19

- Python: 74 tests passed in 30.875 seconds on Windows/Python 3.10. The process-owner crash test now sets its working directory explicitly, so discovery from the workspace root works.
- Browser modules: 14 Node tests passed (context limits, mobile worker lifecycle, Semi schema/limits).
- Real local browser: Semi sample saved/reloaded, export preview inspected; PC imported matching synthetic JSON, quarantined it, adopted it with evidence, and the autonomous worker produced a candidate using the real CPU model. IAB did not expose a download event, so saving/transferring a file on an actual phone is not verified.
- Real autonomous search: registered public topic “언어 모델”, obtained three Wikipedia source links and a candidate route. Real search-then-chat displayed a local-model answer with the fetched source URLs.
- Quality remains limited: the generated procedure used past-tense verification claims although no independent verification occurred; it remains a candidate. Search snippets are not fact-checking.
- Real LoRA run: 16 steps, 16 synthetic training examples and six held-out examples, 573,440 trainable parameters. Held-out mean loss 2.6861319 -> 2.6176361; two generated samples unchanged; preset proxy gate failed. Candidate NOT deployed. See LEARNING.ko.md.
- Pinned free runtime/model hashes verified. Runtime setup reuses byte-verified files while the existing model server is running, rather than trying to overwrite locked DLLs.
- Homepage: Higgsfield 5-second 720p film (1,182,601 bytes), play/pause checked, interactive network buttons checked, no console errors. 390px viewport has 375px document width, no video source loaded automatically. Actual Android/iOS/macOS execution not tested.
- Previous signed-peer tests still pass. No public relay/discovery deployment or federated weight training was performed. Paid LLM API was not used.

Older validation below describes earlier versions and is retained as history.

# v0.3 추가 검증 — 2026-09-19

- 기존 42개 테스트 통과. 추가 대화/공유 10개 테스트 통과 (합계 52개).
- 두 개의 독립 상태 폴더와 실제 HTTP 읽기 전용 피드에서 서명 패키지 전송, 격리, 후보 등록, 손상 후 재수신 복원 확인.
- 변조된 서명, 잘못된 발신자, manifest 롤백/동일 버전 충돌, 비공개 경로 노출, 차단된 피어, 검토 전 게시 거부 확인.
- 대화 저장·대화별 문맥 분리·시작 실패 시 고아 메시지 방지·첨부 경계 검사·키 비저장 테스트.
- 브라우저에서 기본 대화 화면, 데모 전송, 명령 승인, 완료 결과 표시 및 JS 오류 없음 확인.
- 유료 OpenAI API 호출은 실행하지 않았음. 공용 인터넷 피어 배포, macOS/Android/iOS 실행 검증은 하지 않았음.
- cryptography 40.0.2가 설치된 로컬 환경에서 Ed25519 교환 테스트. 배포 사용자는 유지보수되는 버전과 취약점 공지를 별도로 확인해야 함.

# Validation — Cell Agent 0.2 — 2026-09-19

## Current result

`python -X utf8 -m unittest -v test_control.py test_cell_agent.py`: **42 tests passed in 19.376 seconds** on Windows / Python 3.10.10.

`node --check ui/app.js` and Python compilation for all five runtime modules also passed.

New integration checks exercise actual Windows processes, not just mocks:

- Killing a supervised task stops its child process from updating a counter file; termination was confirmed within the test's 3-second bound.
- Abruptly terminating the process that owns a Windows Job Object stops the descendant counter writer through kill-on-close.
- Missing controller heartbeat stops the task and locks new execution.
- Emergency-stop latch survives a controller restart.
- Pausing is recorded separately from hard termination.
- A command approval is bound to its run and can be consumed only once; pending approvals are revoked on kill.
- A second controller using the same state directory is rejected.
- An actual demo worker creates two specialized cells, writes a Python helper, executes its three checks, and records memory and a route candidate.
- Route updates invalidate the applicability of old reviews; failures demote routes; agent-facing tools cannot submit operator reviews.
- A simulated interruption before file replacement leaves a recoverable write-ahead intent.
- HTTP endpoints reject missing authentication, foreign origins and incorrect Host headers; static assets include a restrictive CSP.

Browser UI checks on the actual localhost app:

- Loaded the Korean interface at the native narrow in-app viewport; no browser console errors were observed.
- Started and completed an offline demo.
- Started the counter-process stop experiment, pressed the emergency stop button, and observed stop lock plus disabled execution controls.
- Restarted the supervisor and observed the persistent stop lock.
- Used the RESUME dialog, started the approval-mode demo, paused it, approved the displayed Python command, resumed it, and observed completion.
- Viewed the knowledge-route, memory and procedure cards.
- Left the interface open, with no worker running and emergency-stop lock engaged.

No live OpenAI calls, paid searches, model training or intelligence benchmarks were performed. A passing deterministic demo establishes runtime behavior, not autonomous competence. No isolated-account/VM security boundary was established. Job Objects cannot revoke completed side effects or already-sent external requests, and do not contain every possible service-mediated action.

## Earlier v0.1 validation

Environment: Windows, Python 3.10.10. No third-party Python dependencies.

## Completed checks

- `python -X utf8 -m unittest -v test_cell_agent.py`: **22 tests passed**, 1.357 seconds on this run.
- `python -X utf8 cell_agent.py --demo`: exited 0. Created two child cells, generated and executed a Python function with three assertions, stored a memory and a candidate procedure.
- Demo run ID: `e89b356840aa4303`; 6 simulated model responses, 2 children, no API tokens.
- `python -X utf8 cell_agent.py --stats`: exited 0; empty normal state DB reported 36,864 bytes.
- `python -X utf8 cell_agent.py --compact`: exited 0 with no eligible normal-state events.

Tests include real temporary file mutations and conflict-aware rollback, actual child Python processes, concurrent child agents, shared call-budget contention, persistent memory deduplication, archive recovery contents, candidate invalidation, cancellation before commands, storage threshold checks, API-key environment exclusion, and mocked Responses request/continuation handling.

## Not established

- No OpenAI API key was present. Authentication, account model availability, real Responses/Web Search compatibility, live reasoning quality and API pricing were not tested.
- The demo uses a deterministic scripted provider. It is a runtime integration exercise, not evidence of emergent learning or intelligence.
- No neural model training, distillation, quantization, learned routing, independent capability benchmark, or long-term improvement experiment was performed.
- No Claude/local-model provider or GUI/computer-vision driver is included.
- Host process execution is not an OS sandbox. Command side effects have no general rollback guarantee.
- Budget checks are operational thresholds, not strict OS resource quotas or exact billing caps.

The shipped program is an inspectable first-stage prototype, not a production-hardened autonomous operating system.
