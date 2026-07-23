"""UA-2 shared baseline datasource provisioning."""
from ua_test_harness.provisioning.ua2_baseline import (
    BaselineError,
    Ua2Baseline,
    ensure_ua2_baseline,
    require_shared_datasource,
    teardown_ua2_baseline,
    SHARED_TYPES_DS_NAME,
    SHARED_EMPTY_DS_NAME,
)
