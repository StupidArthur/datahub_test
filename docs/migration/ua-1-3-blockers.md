# UA-1-3 Migration Status

## All 8 cases now have executable pytest implementations

All eight cases defined in `ua_test_harness/test_cases/UA-1-3.md` have
been migrated to `tests/integration/ua1/test_recovery_and_reconnect.py`.

### Migrated with full normal assertions

- UA-1-3-01 disconnect detection latency
- UA-1-3-02 reconnect recovery latency
- UA-1-3-06 short disconnect recovery
- UA-1-3-07 long disconnect recovery (window shortened to 30s)
- UA-1-3-08 offline tag registration survives restart

### Migrated with performance statistics (no thresholds)

- UA-1-3-03 5-round disconnect/reconnect reliability:
  - Collects 8 groups of metrics (alive_down, quality_down, alive_up, quality_up,
    value_still, value_change, history_still, history_grow) over 5 full rounds
  - Computes min / max / mean per group
  - Only asserts: 5 rounds complete, all metrics present and non-negative
  - No performance threshold assertions (no baseline available yet)

### Migrated with dynamic xfail (spec pending)

These two cases execute fully but end with `pytest.xfail(...)` because the
product semantics for offline write operations are not yet defined:

- UA-1-3-04 offline writeTagValues history semantics
  - Stops mocker, waits for offline, executes write_tag_values, queries history
  - Records all observations before xfail
- UA-1-3-05 offline write-back after reconnect
  - Stops mocker, writes value, restarts mocker, reconnects, reads RT value
  - Records RT value + quality before xfail

Both use `@pytest.mark.spec_pending` marker (registered in pyproject.toml).

## Inventory

- 419 legacy cases total
- 28 migrated (24 from original slice + 4 from UA-1-3 completion)
- 391 missing
