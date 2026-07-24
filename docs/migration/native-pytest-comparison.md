# Native pytest Migration Comparison

This document records, per Case, the comparison between the legacy
Harness handler (where it existed) and the new pytest nodeid. Use it
to understand the precise assertion changes during migration and the
real product behavior observed.

Status legend:
- PASS: case ran successfully against the real DataHub in past sessions
- OBSERVED: case ran but assertion was weak / not verified
- BLOCKED: case cannot be migrated due to product capability gap
- PENDING: case not yet run against real DataHub

Cleanup: every Case in this document includes a cleanup row. All
cleanup paths in pytest-native form trace to
`tests/support/cleanup.py` + `tests/support/rt_helpers.py`, which
ignore only "resource does not exist" errors and propagate everything
else.

---

## UA-1-1 连接建立

### UA-1-1-01 正常连接（URL 无 path）

- Old Markdown: `ua_test_harness/test_cases/UA-1-1.md` row UA-1-1-01
- Old Handler: `ua_test_harness/tests/ua_1/test_datasource.py::ua_1_1_01_url_no_path`
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_normal_connection_no_path`
- Old assertion: `assertTrue("ds_alive", ok)` (only alive=true)
- New assertion:
  - `wait_until` alive=true
  - RT value not None
  - RT quality != 0
  - DS + tag + tag-id cleanup with `delete_datasource_if_exists` /
    `delete_tag_if_exists`
- Old result: PASS (only alive verified)
- New result: PENDING (offline-clean / ready for real env)
- Cleanup result: helper updated to ignore only "not exist"; other errors propagate
- Differences: old handler stopped at alive=true; new handler verifies the full
  chain (alive, RT value, RT quality) and physical cleanup

### UA-1-1-02 正常连接（URL 有 path）

- Old Markdown: UA-1-1-02 row
- Old Handler: `ua_1_1_02_url_with_path` (only alive check)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_normal_connection_with_path`
- Old assertion: alive=true
- New assertion: alive=true + RT value not None + cleanup
- Old result: PASS (only alive)
- New result: PENDING
- Cleanup result: ok
- Differences: path format is now derived via `parse_mocker_endpoint`
  so the URL `opc.tcp://host:port/ua_mocker/` is built from the
  configured endpoint; both with-path and no-path are exercised
  against the same mocker

### UA-1-1-03 两种 URL 格式区别

- Old Markdown: UA-1-1-03 row
- Old Handler: `ua_1_1_03_two_urls` (only both alive)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_two_url_formats`
- Old assertion: both ds alive=true
- New assertion: both ds alive=true + each tag has RT value (independent
  collection)
- Old result: PASS
- New result: PENDING
- Cleanup result: both ds + both tags cleaned
- Differences: stronger independence check via per-ds tag RT

### UA-1-1-04 不可达地址

- Old Markdown: UA-1-1-04 row
- Old Handler: `ua_1_1_04_unreachable` (uses `opc.tcp://127.0.0.1:1/...`)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_unreachable_address`
- Old assertion: ds stays offline for ~20s
- New assertion: free-port dynamic probe; ds stays offline for 30s
  window; no `try/except AssertionError`
- Old result: PASS (with hard-coded port 1)
- New result: PENDING (port dynamically chosen; theoretically safer but
  not 100% guaranteed free)
- Cleanup result: ok
- Differences: dynamic port + longer observation window; hard-coded
  port 1 was unsafe

### UA-1-1-05 不可达变可达

- Old Markdown: UA-1-1-05 row
- Old Handler: `ua_1_1_05_offline_to_online` (notes endpoint never changes
  — handler admits the case was not faithful to the spec)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_offline_to_online`
- Old assertion: only endpoint-not-changed probe
- New assertion:
  - ds points to a free port not listening
  - ds becomes alive=false initially
  - mocker started on the same port
  - alive becomes true
  - tag RT appears
- Old result: OBSERVED (case does not actually test recovery)
- New result: PENDING
- Cleanup result: ok
- Differences: faithful to spec; mocker start is explicit at test function level

### UA-1-1-06 数据源有鉴权，不配凭据

- Old Markdown: UA-1-1-06 row
- Old Handler: `ua_1_1_06_auth_required_no_creds` (mock had no auth — case
  was unable to verify the spec)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_auth_required_no_creds`
- Old assertion: only alive check
- New assertion: enable with auth mocker + no creds → ds stays offline
  for 10s
- Old result: PASS (mock had no auth)
- New result: PENDING (mock has real UserNameIdentityToken auth now)
- Cleanup result: ok
- Differences: real auth backend; must observe whether DataHub's OPC UA
  client honors the server's auth challenge

### UA-1-1-07 数据源有鉴权，配正确凭据

- Old Markdown: UA-1-1-07 row
- Old Handler: `ua_1_1_07_auth_ok` (passes no creds — same problem)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_auth_correct_creds`
- New assertion: ds alive=true (BLOCKED: DataHub does not consume
  dsExtInfo for OPC UA auth) → marked
  `@pytest.mark.xfail(strict=True, ...)`
- Old result: OBSERVED
- New result: BLOCKED (xfail strict)
- Cleanup result: helper-driven; the case fails before reaching cleanup
- Differences: see `docs/migration/ua-1-1-blockers.md`

### UA-1-1-08 数据源无鉴权，配了凭据

- Old Markdown: UA-1-1-08 row
- Old Handler: `ua_1_1_08_auth_ignored` (no auth in mock anyway)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_no_auth_extra_creds`
- New assertion: extra creds on unauthenticated endpoint → ds alive=true
  + RT works
- Old result: PASS
- New result: PENDING
- Cleanup result: ok
- Differences: real unauth mocker; verifies creds don't break anonymous
  connection

### UA-1-1-09 不配好值质量码

- Old Markdown: UA-1-1-09 row
- Old Handler: `ua_1_1_09_quality_default` (only alive)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_quality_default`
- New assertion: RT quality == 192 (observed product default)
- Old result: OBSERVED
- New result: PENDING
- Cleanup result: ok
- Differences: explicit quality assertion; risk: `goodQualityCode` field
  name also exists in legacy code (see UA-1-1-10)

### UA-1-1-10 配置正常好值（192）

- Old Markdown: UA-1-1-10 row
- Old Handler: `ua_1_1_10_quality_192` (no real quality check; comment
  "goodQuality field: plan 未给出 schema")
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_quality_192`
- New assertion: payload includes `dsExtInfo.goodQuality="192"`; RT
  quality == 192
- Old result: OBSERVED
- New result: PENDING
- Cleanup result: ok
- Differences: explicit payload + RT quality check; note both
  `goodQuality` and `goodQualityCode` field names (see blockers)

### UA-1-1-11 配置非标准好值（0）

- Old Markdown: UA-1-1-11 row
- Old Handler: `ua_1_1_11_quality_zero` (no real quality check)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_quality_zero`
- New assertion: payload includes `dsExtInfo.goodQuality="0"`; RT has a
  value (quality interpretation left to DataHub)
- Old result: OBSERVED
- New result: PENDING
- Cleanup result: ok
- Differences: explicit "value present" assertion; avoids Python
  truthiness treating 0 as unset

### UA-1-1-12 重复地址注册

- Old Markdown: UA-1-1-12 row
- Old Handler: `ua_1_1_12_duplicate_url` (catches any exception)
- New nodeid: `tests/integration/ua1/test_connection_establishment.py::test_duplicate_url_rejected`
- New assertion: `pytest.raises(TptAPIError)` + `code == "A0001"` +
  msg contains "duplicate"
- Old result: PASS
- New result: PENDING
- Cleanup result: helper-driven
- Differences: structured error code assertion instead of
  `try/except Exception`

---

## UA-1-2 启停控制

### UA-1-2-01 禁用运行中数据源

- Old Markdown: UA-1-2-01 row
- Old Handler: not implemented in legacy ua_1 test_datasource.py
- New nodeid: `tests/integration/ua1/test_lifecycle_control.py::test_disable_running_datasource`
- Old assertion: N/A
- New assertion:
  - RT values change before disable
  - alive becomes false
  - RT read raises `TptAPIError` (no fake data) — `assert_rt_unavailable`
- Old result: N/A
- New result: PENDING
- Cleanup result: module-scoped `connected_changing_tag` fixture cleans
  tag, ds, mocker
- Differences: spec said "RT quality 降级为 0"; real behavior is
  TptAPIError. Markers updated to reflect real behavior.

### UA-1-2-02 禁用后位号 RT 状态

- Old Markdown: UA-1-2-02 row
- Old Handler: N/A in ua_1/test_datasource.py
- New nodeid: `tests/integration/ua1/test_lifecycle_control.py::test_rt_state_after_disable`
- Old assertion: N/A
- New assertion: `assert_rt_unavailable(api, ctx.tag_name)` (must throw
  TptAPIError)
- Old result: N/A
- New result: PENDING
- Cleanup result: ok
- Differences: previous helper swallowed the error and returned a fake
  object. That was fixed in `tests/support/rt_helpers.py` to expose
  the real product behavior.

### UA-1-2-03 禁用后历史不再增长

- Old Markdown: UA-1-2-03 row
- Old Handler: not migrated previously
- New nodeid: `tests/integration/ua1/test_history_lifecycle.py::test_history_stops_after_disable`
- Old assertion: N/A
- New assertion:
  - baseline history count > 0
  - disable, wait alive=false + 5s grace
  - in [t_stable, t_stable+15s] window, history count does not grow
- Old result: N/A
- New result: PENDING
- Cleanup result: helper-driven
- Differences: poll-based comparison instead of single `query_history`
  total read

### UA-1-2-04 重新启用已禁用数据源

- Old Markdown: UA-1-2-04 row
- Old Handler: not migrated previously
- New nodeid: `tests/integration/ua1/test_lifecycle_control.py::test_reenable_disabled_datasource`
- New assertion: alive=true after re-enable + RT quality != 0 + values
  change across 2 reads
- Old result: N/A
- New result: PENDING
- Cleanup result: module-scoped fixture cleanup

### UA-1-2-05 启用后历史恢复增长

- Old Markdown: UA-1-2-05 row
- Old Handler: not migrated previously
- New nodeid: `tests/integration/ua1/test_history_lifecycle.py::test_history_resumes_after_enable`
- New assertion:
  - disable first
  - record t_re_enable
  - enable, wait alive=true + RT quality restored
  - in [t_re_enable, now] window, history count > 0
- Old result: N/A
- New result: PENDING
- Cleanup result: helper-driven

### UA-1-2-06 重复启用

- Old Markdown: UA-1-2-06 row
- New nodeid: `tests/integration/ua1/test_lifecycle_control.py::test_repeat_enable`
- New assertion: API does not throw + ds stays alive

### UA-1-2-07 重复禁用

- Old Markdown: UA-1-2-07 row
- New nodeid: `tests/integration/ua1/test_lifecycle_control.py::test_repeat_disable`
- New assertion: API does not throw + ds stays offline

### UA-1-2-08 多次启停循环

- Old Markdown: UA-1-2-08 row
- New nodeid: `tests/integration/ua1/test_lifecycle_control.py::test_multiple_start_stop_cycles`
- New assertion: 2 full cycles; disable phase asserts `assert_rt_unavailable`;
  enable phase asserts quality restored and values change
- Differences: previous spec said "quality=0 when disabled"; current
  behavior is `TptAPIError` — assertion updated.

---

## UA-1-3 断线与自动重连

### UA-1-3-01 断开后各项指标变化延迟

- New nodeid: `tests/integration/ua1/test_recovery_and_reconnect.py::test_disconnect_detection_latency`
- New assertion: poll-based timing for alive→false and RT unavailable;
  total time bounded by 180s
- Differences: poll-based instead of fixed sleep; uses free-port

### UA-1-3-02 重连后各项指标恢复延迟

- New nodeid: `tests/integration/ua1/test_recovery_and_reconnect.py::test_reconnect_recovery_latency`
- New assertion: restart mocker on same port; poll for alive→true and
  RT good quality

### UA-1-3-06 短暂断连恢复

- New nodeid: `tests/integration/ua1/test_recovery_and_reconnect.py::test_short_disconnect_recovery`
- New assertion: immediate restart + recovery verified

### UA-1-3-07 长时间断连后恢复

- New nodeid: `tests/integration/ua1/test_recovery_and_reconnect.py::test_long_disconnect_recovery`
- New assertion: 30s disconnect (spec is 120s; this slice uses 30s for
  pytest cycle discipline), recovery verified
- Cleanup result: stop_mocker only stops the PID we started;
  delete_tag_if_exists / delete_datasource_if_exists clean the rest

### UA-1-3-03/04/05/08

- See `docs/migration/ua-1-3-blockers.md`; not migrated in this phase.

---

## helper layer changes

- `tests/support/cleanup.py` — `delete_datasource_if_exists` /
  `delete_tag_if_exists` ignore only "not exist" / "不存在"; network and
  server errors propagate. Both helpers verify resource actually
  disappears (poll active list + recycle list for tags; poll active
  list for datasources).
- `tests/support/rt_helpers.py` (new) — three cleanly separated
  helpers:
  - `get_rt_point(api, tag_name)` propagates TptAPIError
  - `try_get_rt_point(api, tag_name)` swallows only "Tag Dose/Does
    Not Exist"
  - `assert_rt_unavailable(api, tag_name, timeout=0)` asserts throw
    with optional polling
- `tests/support/mocker_process.py` — unchanged; was already correct

## tpt_api changes

No production code changes. `tpt_api/datahub.py` already exposed
`add_ds_info(..., ds_ext_info=...)`, `get_history_value`,
`query_history_value`, and the `TptAPIError(code, msg)` exception
type. Unit tests in `tpt_api/python/tests/` continue to pass.

## ua_mocker changes

No code changes in this slice. The auth backend was already
implemented in a prior phase. The functional tests
(`ua_mocker/_test_*_config.yaml`) are not part of pytest; only the
configuration loader is exercised.

## GUI changes

- New `internal/adapters/nativepytest/` package with subprocess
  manager, JUnit XML parser, and command builder — all tested in
  isolation against a real pytest subprocess in a temp directory.
- New `internal/automation/manifest.go` for the case-manifest.json
  model + validation.
- New `internal/automation/native.go` NativeService with
  ListCases / RunNative / Cancel / Collect.
- New `internal/automation/bridge.go` PytestRunnerAdapter.
- New Wails bindings (ListNativeTestCases / RunNativeTestCases /
  CancelNativeTestRun / CollectNativeTestRun).
- Legacy chain untouched: default execution mode is still legacy.
- Frontend NOT modified in this slice (would be a future opt-in UI).