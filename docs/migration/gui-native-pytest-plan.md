# GUI Native pytest Backend Plan

This document maps the current GUI execution chain and the planned native
pytest backend slice. It exists to ensure the dual-track migration does
not silently change behavior for users who have not opted in.

## Current Legacy Chain (default, must remain functional)

```
Wails frontend (src/pages/TestRunsPage.tsx)
  └─ wailsjs/go bindings/AutomationBinding (frontend/src/lib/api.ts)
       └─ AutomationBinding.StartTestRun(req)             [bindings/automation.go]
            └─ automation.Service.StartTestRun(req)        [automation/runner.go]
                 ├─ ValidateCaseIDs against current Catalog
                 ├─ Write run-config.json (with creds snapshot, includes password)
                 ├─ Runner.Start(StartSpec{ PythonExe, RunnerArgs=["-m","ua_test_harness.cli","run","--config",cfgPath], ... })
                 │     └─ pytestrunner.Manager.Start             [adapters/pytestrunner/manager.go]
                 │           ├─ exec.CommandContext(pythonExe, runnerArgs...)
                 │           ├─ capture stdout (NDJSON) + stderr
                 │           ├─ consumeStdout → ParseEventLine → onEvent
                 │           │     └─ Service.onEvent → Store.AddAutomationEvent + EventProjection
                 │           ├─ consumeStderr → onLog
                 │           └─ waitProcess → cleanup
                 └─ emit Notifier.RunUpdated → Wails EventsEmit
```

Key files:

- `ua_test_gui/internal/automation/runner.go` — Service.StartTestRun,
  buildRunConfigJSONWith (note: writes cleartext password to
  `run-config.json` inside `~/.ua_test_gui/runs/<runId>/`; this is a
  known sensitivity flag for the migration team)
- `ua_test_gui/internal/automation/catalog.go` — LoadCatalogFromFile,
  FindCase, ValidateCaseIDs
- `ua_test_gui/internal/automation/event.go` — EventProjection (case
  status → RunPatch)
- `ua_test_gui/internal/automation/ports.go` — Store / Runner /
  StartSpec / ProcessInfo / EvEnvelope
- `ua_test_gui/internal/automation/paths.go` — run-dir / run-config / log
  path management
- `ua_test_gui/internal/adapters/pytestrunner/manager.go` — Python
  subprocess wrapper (legacy harness target)
- `ua_test_gui/internal/bindings/automation.go` — Wails-facing thin
  wrapper exposing the Service methods

## Frontend Consumption

- `frontend/src/pages/TestRunsPage.tsx` — lists runs, requests new run
  via `AutomationBinding.StartTestRun({ selectedCaseIds, ... })`
- `frontend/src/lib/api.ts` — imports generated wails bindings from
  `frontend/wailsjs/go/bindings/Automation*`

## Migration Boundaries (must not change in this phase)

- The legacy chain above remains the default execution path.
- The frontend does not change its default request shape.
- `automation.Service.StartTestRun` continues to write
  `run-config.json` and start `python -m ua_test_harness.cli run ...`.
- The Store / Catalog / Runner interfaces stay.

## Native pytest Mode Slice (incremental, opt-in)

Goal: a separate Go component that reads
`docs/test_cases/case-manifest.json`, runs `python -m pytest <nodeid>
--junitxml=<run-dir>/junit.xml`, parses JUnit, and exposes the result
through a parallel set of Wails bindings.

```
Wails frontend (NOT CHANGED in this phase)
  └─ new optional mode (future frontend work)
       └─ AutomationBinding.ListNativeTestCases()           [new]
       └─ AutomationBinding.RunNativeTestCases(caseIds)     [new]
       └─ AutomationBinding.CancelNativeTestRun(runID)      [new]
            └─ new automation.NativeService                   [internal/automation/native.go]
                 ├─ Manifest: load + validate case-manifest.json
                 ├─ Build pytest command via CommandBuilder
                 │     args: ["-m","pytest", nodeid1, nodeid2, "-v",
                 │           "--junitxml", junitPath]
                 │     env:  DATAHUB_BASE_URL, DATAHUB_USER, ...
                 │     ctx:  cancellable
                 ├─ exec.CommandContext (separate Runner to avoid
                 │   mixing with the legacy Runner interface)
                 ├─ JUnitParse(junitPath) → []CaseJUnitResult
                 └─ emit result via new NativeResult struct
```

Key files to add (no existing files are removed):

- `internal/automation/manifest.go` — Manifest struct, validation,
  loader (mirrors `case-manifest.json` schemaVersion=1)
- `internal/automation/manifest_test.go`
- `internal/automation/command.go` — BuildPytestCommand(nodeids,
  junitPath) pure function
- `internal/automation/command_test.go`
- `internal/automation/junit.go` — JUnit XML parser; minimal coverage
  of `<testsuite>` + `<testcase>` with status mapping
- `internal/automation/junit_test.go`
- `internal/automation/native.go` — NativeService exposing
  List/Run/Cancel against a separate Runner
- `internal/automation/native_test.go`
- `internal/adapters/nativepytest/runner.go` — separate subprocess
  Runner implementation (exec.CommandContext with context cancel; no
  shared state with pytestrunner)
- `internal/adapters/nativepytest/runner_test.go` — integration-style
  test that spawns a real pytest in a temp dir (using a minimal
  fixture pytest project)
- `internal/bindings/automation.go` — add the three new binding methods

## Dual-Track Mode Wiring

The container (`internal/app/container.go`) will gain an opt-in
`Mode` config (default `legacy`). Only when the operator (or future
frontend) explicitly switches does the NativeService get used.

- Default execution = unchanged; `StartTestRun` still writes
  `run-config.json` and starts `python -m ua_test_harness.cli run`
- Native mode adds an opt-in surface but never removes the legacy
  path
- The frontend is NOT wired in this phase; only the Go backend and
  unit tests

## JUnit XML Mapping

JUnit XML status mapping (from `<testcase>` `<failure>` /
`<error>` / `<skipped>`):

| XML                                      | manifest status |
|------------------------------------------|-----------------|
| no `<failure>`/`<error>`, no `<skipped>` | `passed`        |
| `<skipped message="..."/>`               | `skipped`       |
| `<skipped><reason>pytest.xfail</...>...` | `xfail`         |
| `<failure>`                              | `failed`        |
| `<error>`                                | `error`         |

`xpass` (XPASS) is represented in JUnit XML as `<skipped>` with a
reason indicating unexpected pass — distinguish via the reason text
prefix.

The parser does NOT consult the manifest for status; it only reads
the XML. Results are then matched back to manifest cases by `nodeid`
(classname + name combination).

## Safety Constraints

- `exec.CommandContext` is used; the context's cancel stops only the
  child process started by this code path
- nodeids are validated against the loaded manifest before being passed
  to pytest — no arbitrary string can become a process argument
- junit path is constrained under the run-dir (use `automation.SafeJoin`)
- credentials come from environment variables, not command line
  arguments
- no `cmd.exe /c` or `sh -c` shims

## Frontend Wiring (future phase, NOT in this commit)

The frontend will gain a mode selector. Until that lands:
- `case-manifest.json` is loaded by Go only on explicit `List` call
- No new Wails binding replaces the legacy ones
- No existing binding has its signature changed

## Tests Strategy

- Manifest loader: pure JSON parse + structural validation, no I/O
- Command builder: pure function, takes nodeids + paths, returns []string
- JUnit parser: pure, takes bytes, returns []CaseJUnitResult
- Runner integration: spawn real pytest in temp dir using a tiny
  fixture project; verify one pass + one fail + one xfail; verify
  cancel
- No real DataHub, no real integration tests, no real mocker long
  process in this slice