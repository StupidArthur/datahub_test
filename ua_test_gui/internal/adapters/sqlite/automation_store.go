// automation_store.go - automation 域的 SQLite 存储。
//
// 新表(plan.md 7):automation_runs / automation_case_results /
// automation_step_results / automation_events / automation_metrics /
// automation_evidence。
package sqlite

import (
	"database/sql"
	"encoding/json"
	"errors"
	"strings"

	"ua_test_gui/internal/automation"
)

// automationSchema 新增表 + 索引。
const automationSchema = `
CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    selected_cases_json TEXT NOT NULL,
    total INTEGER DEFAULT 0,
    progress INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    observed INTEGER DEFAULT 0,
    measured INTEGER DEFAULT 0,
    cleanup_failed INTEGER DEFAULT 0,
    current_case_id TEXT,
    current_step TEXT,
    pid INTEGER DEFAULT 0,
    exit_code INTEGER,
    run_dir TEXT,
    report_path TEXT,
    log_path TEXT,
    error_message TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_status ON automation_runs(status);
CREATE INDEX IF NOT EXISTS idx_automation_runs_created ON automation_runs(created_at);

CREATE TABLE IF NOT EXISTS automation_case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    summary TEXT,
    cleanup_status TEXT,
    cleanup_message TEXT,
    UNIQUE(run_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_automation_case_run ON automation_case_results(run_id);
CREATE INDEX IF NOT EXISTS idx_automation_case_status ON automation_case_results(run_id, status);

CREATE TABLE IF NOT EXISTS automation_step_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    step_id TEXT,
    title TEXT,
    status TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_automation_step_run ON automation_step_results(run_id, case_id);

CREATE TABLE IF NOT EXISTS automation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    case_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_events_run ON automation_events(run_id, id);

CREATE TABLE IF NOT EXISTS automation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT,
    name TEXT NOT NULL,
    value REAL,
    text_value TEXT,
    unit TEXT,
    labels_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_automation_metrics_run ON automation_metrics(run_id, case_id);

CREATE TABLE IF NOT EXISTS automation_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT,
    kind TEXT,
    path TEXT NOT NULL,
    title TEXT,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_automation_evidence_run ON automation_evidence(run_id, case_id);
`

// ensureAutomationSchema 自动迁移(被 EnsureSchema 调用)。
func (s *Store) ensureAutomationSchema() error {
	if s == nil || s.db == nil {
		return errors.New("store not opened")
	}
	_, err := s.db.Exec(automationSchema)
	return err
}

// CreateAutomationRun 插入新 run。
func (s *Store) CreateAutomationRun(r automation.TestRun) (int64, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return 0, err
	}
	selJSON, _ := json.Marshal(r.SelectedCases)
	res, err := s.db.Exec(
		`INSERT INTO automation_runs(run_key, status, created_at, selected_cases_json, total, run_dir, report_path, log_path, note)
		 VALUES(?,?,?,?,?,?,?,?,?)`,
		r.RunKey, string(r.Status), r.CreatedAt, string(selJSON), r.Total, r.RunDir, r.ReportPath, r.LogPath, r.Note,
	)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// UpdateAutomationRun 增量更新。
func (s *Store) UpdateAutomationRun(runID int64, p automation.RunPatch) error {
	if err := s.ensureAutomationSchema(); err != nil {
		return err
	}
	sets := []string{}
	args := []any{}
	if p.Status != nil {
		sets = append(sets, "status=?")
		args = append(args, string(*p.Status))
	}
	if p.StartedAt != nil {
		sets = append(sets, "started_at=?")
		args = append(args, *p.StartedAt)
	}
	if p.FinishedAt != nil {
		sets = append(sets, "finished_at=?")
		args = append(args, *p.FinishedAt)
	}
	if p.Total != nil {
		sets = append(sets, "total=?")
		args = append(args, *p.Total)
	}
	if p.Progress != nil {
		sets = append(sets, "progress=?")
		args = append(args, *p.Progress)
	}
	if p.Passed != nil {
		sets = append(sets, "passed=?")
		args = append(args, *p.Passed)
	}
	if p.Failed != nil {
		sets = append(sets, "failed=?")
		args = append(args, *p.Failed)
	}
	if p.Errors != nil {
		sets = append(sets, "errors=?")
		args = append(args, *p.Errors)
	}
	if p.Skipped != nil {
		sets = append(sets, "skipped=?")
		args = append(args, *p.Skipped)
	}
	if p.Blocked != nil {
		sets = append(sets, "blocked=?")
		args = append(args, *p.Blocked)
	}
	if p.Observed != nil {
		sets = append(sets, "observed=?")
		args = append(args, *p.Observed)
	}
	if p.Measured != nil {
		sets = append(sets, "measured=?")
		args = append(args, *p.Measured)
	}
	if p.CleanupFailed != nil {
		sets = append(sets, "cleanup_failed=?")
		args = append(args, *p.CleanupFailed)
	}
	if p.CurrentCaseID != nil {
		sets = append(sets, "current_case_id=?")
		args = append(args, *p.CurrentCaseID)
	}
	if p.CurrentStep != nil {
		sets = append(sets, "current_step=?")
		args = append(args, *p.CurrentStep)
	}
	if p.PID != nil {
		sets = append(sets, "pid=?")
		args = append(args, *p.PID)
	}
	if p.ExitCode != nil {
		sets = append(sets, "exit_code=?")
		args = append(args, *p.ExitCode)
	}
	if p.ReportPath != nil {
		sets = append(sets, "report_path=?")
		args = append(args, *p.ReportPath)
	}
	if p.LogPath != nil {
		sets = append(sets, "log_path=?")
		args = append(args, *p.LogPath)
	}
	if p.ErrorMessage != nil {
		sets = append(sets, "error_message=?")
		args = append(args, *p.ErrorMessage)
	}
	if len(sets) == 0 {
		return nil
	}
	q := "UPDATE automation_runs SET " + strings.Join(sets, ",") + " WHERE id=?"
	args = append(args, runID)
	_, err := s.db.Exec(q, args...)
	return err
}

// GetAutomationRun 取单 run。
func (s *Store) GetAutomationRun(runID int64) (automation.TestRun, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return automation.TestRun{}, err
	}
	row := s.db.QueryRow(
		`SELECT id, run_key, status, created_at, started_at, finished_at, selected_cases_json,
		 total, progress, passed, failed, errors, skipped, blocked, observed, measured, cleanup_failed,
		 current_case_id, current_step, pid, exit_code, run_dir, report_path, log_path, error_message, note
		 FROM automation_runs WHERE id=?`, runID)
	var r automation.TestRun
	var sel sql.NullString
	var startedAt, finishedAt, currentCase, currentStep, runDir, reportPath, logPath, errMsg, note sql.NullString
	var ec sql.NullInt64
	if err := row.Scan(&r.ID, &r.RunKey, &r.Status, &r.CreatedAt, &startedAt, &finishedAt, &sel,
		&r.Total, &r.Progress, &r.Passed, &r.Failed, &r.Errors, &r.Skipped, &r.Blocked, &r.Observed, &r.Measured, &r.CleanupFailed,
		&currentCase, &currentStep, &r.PID, &ec, &runDir, &reportPath, &logPath, &errMsg, &note); err != nil {
		return r, err
	}
	r.StartedAt = nullStr(startedAt)
	r.FinishedAt = nullStr(finishedAt)
	r.CurrentCaseID = nullStr(currentCase)
	r.CurrentStep = nullStr(currentStep)
	r.RunDir = nullStr(runDir)
	r.ReportPath = nullStr(reportPath)
	r.LogPath = nullStr(logPath)
	r.ErrorMessage = nullStr(errMsg)
	r.Note = nullStr(note)
	if ec.Valid {
		v := int(ec.Int64)
		r.ExitCode = &v
	}
	if sel.Valid {
		_ = json.Unmarshal([]byte(sel.String), &r.SelectedCases)
	}
	return r, nil
}

// ListAutomationRuns 列出。
func (s *Store) ListAutomationRuns(filter automation.ListRunsRequest) ([]automation.TestRun, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return nil, err
	}
	q := `SELECT id, run_key, status, created_at, started_at, finished_at, selected_cases_json,
		 total, progress, passed, failed, errors, skipped, blocked, observed, measured, cleanup_failed,
		 current_case_id, current_step, pid, exit_code, run_dir, report_path, log_path, error_message, note
		 FROM automation_runs WHERE 1=1`
	args := []any{}
	if filter.Status != "" {
		q += " AND status=?"
		args = append(args, filter.Status)
	}
	if filter.Keyword != "" {
		q += " AND (run_key LIKE ? OR note LIKE ?)"
		args = append(args, "%"+filter.Keyword+"%", "%"+filter.Keyword+"%")
	}
	q += " ORDER BY id DESC"
	if filter.Limit > 0 {
		q += " LIMIT ?"
		args = append(args, filter.Limit)
	}
	rows, err := s.db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []automation.TestRun{}
	for rows.Next() {
		var r automation.TestRun
		var sel sql.NullString
		var startedAt, finishedAt, currentCase, currentStep, runDir, reportPath, logPath, errMsg, note sql.NullString
		var ec sql.NullInt64
		if err := rows.Scan(&r.ID, &r.RunKey, &r.Status, &r.CreatedAt, &startedAt, &finishedAt, &sel,
			&r.Total, &r.Progress, &r.Passed, &r.Failed, &r.Errors, &r.Skipped, &r.Blocked, &r.Observed, &r.Measured, &r.CleanupFailed,
			&currentCase, &currentStep, &r.PID, &ec, &runDir, &reportPath, &logPath, &errMsg, &note); err != nil {
			return nil, err
		}
		r.StartedAt = nullStr(startedAt)
		r.FinishedAt = nullStr(finishedAt)
		r.CurrentCaseID = nullStr(currentCase)
		r.CurrentStep = nullStr(currentStep)
		r.RunDir = nullStr(runDir)
		r.ReportPath = nullStr(reportPath)
		r.LogPath = nullStr(logPath)
		r.ErrorMessage = nullStr(errMsg)
		r.Note = nullStr(note)
		if ec.Valid {
			v := int(ec.Int64)
			r.ExitCode = &v
		}
		if sel.Valid {
			_ = json.Unmarshal([]byte(sel.String), &r.SelectedCases)
		}
		out = append(out, r)
	}
	return out, nil
}

func nullStr(s sql.NullString) string {
	if !s.Valid {
		return ""
	}
	return s.String
}

// AddAutomationEvent 落库一条原始事件。
func (s *Store) AddAutomationEvent(ev automation.TestEvent) (int64, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return 0, err
	}
	res, err := s.db.Exec(
		`INSERT INTO automation_events(run_id, ts, event_type, case_id, payload_json) VALUES(?,?,?,?,?)`,
		ev.RunID, ev.Ts, ev.EventType, ev.CaseID, string(ev.Payload),
	)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// ListRunEvents 拉事件。
func (s *Store) ListRunEvents(runID int64, afterID int64, limit int) ([]automation.TestEvent, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 500 {
		limit = 200
	}
	rows, err := s.db.Query(
		`SELECT id, run_id, ts, event_type, case_id, payload_json FROM automation_events
		 WHERE run_id=? AND id>? ORDER BY id ASC LIMIT ?`,
		runID, afterID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []automation.TestEvent{}
	for rows.Next() {
		var ev automation.TestEvent
		var payload string
		if err := rows.Scan(&ev.ID, &ev.RunID, &ev.Ts, &ev.EventType, &ev.CaseID, &payload); err != nil {
			return nil, err
		}
		ev.Payload = json.RawMessage(payload)
		out = append(out, ev)
	}
	return out, nil
}

// UpsertCaseResult 插入或更新。
func (s *Store) UpsertCaseResult(cr automation.CaseResult) (int64, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return 0, err
	}
	// upsert by (run_id, case_id)
	res, err := s.db.Exec(
		`INSERT INTO automation_case_results(run_id, case_id, title, status, started_at, finished_at, duration_ms, summary, cleanup_status, cleanup_message)
		 VALUES(?,?,?,?,?,?,?,?,?,?)
		 ON CONFLICT(run_id, case_id) DO UPDATE SET
		   title=COALESCE(excluded.title, title),
		   status=COALESCE(excluded.status, status),
		   started_at=COALESCE(excluded.started_at, started_at),
		   finished_at=COALESCE(excluded.finished_at, finished_at),
		   duration_ms=COALESCE(excluded.duration_ms, duration_ms),
		   summary=COALESCE(excluded.summary, summary),
		   cleanup_status=COALESCE(excluded.cleanup_status, cleanup_status),
		   cleanup_message=COALESCE(excluded.cleanup_message, cleanup_message)`,
		cr.RunID, cr.CaseID, cr.Title, cr.Status, cr.StartedAt, cr.FinishedAt, cr.DurationMs, cr.Summary, cr.CleanupStatus, cr.CleanupMessage,
	)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	if id == 0 {
		_ = s.db.QueryRow(`SELECT id FROM automation_case_results WHERE run_id=? AND case_id=?`, cr.RunID, cr.CaseID).Scan(&id)
	}
	return id, nil
}

// ListCaseResults 列出。
func (s *Store) ListCaseResults(runID int64) ([]automation.CaseResult, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return nil, err
	}
	rows, err := s.db.Query(
		`SELECT id, run_id, case_id, title, status, started_at, finished_at, duration_ms, summary, cleanup_status, cleanup_message
		 FROM automation_case_results WHERE run_id=? ORDER BY id ASC`, runID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []automation.CaseResult{}
	for rows.Next() {
		var cr automation.CaseResult
		if err := rows.Scan(&cr.ID, &cr.RunID, &cr.CaseID, &cr.Title, &cr.Status, &cr.StartedAt, &cr.FinishedAt, &cr.DurationMs, &cr.Summary, &cr.CleanupStatus, &cr.CleanupMessage); err != nil {
			return nil, err
		}
		out = append(out, cr)
	}
	return out, nil
}

// AddStepResult 落步骤。
func (s *Store) AddStepResult(sr automation.StepResult) (int64, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return 0, err
	}
	res, err := s.db.Exec(
		`INSERT INTO automation_step_results(run_id, case_id, step_id, title, status, started_at, finished_at, duration_ms, message)
		 VALUES(?,?,?,?,?,?,?,?,?)`,
		sr.RunID, sr.CaseID, sr.StepID, sr.Title, sr.Status, sr.StartedAt, sr.FinishedAt, sr.DurationMs, sr.Message,
	)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// AddMetric 落指标。
func (s *Store) AddMetric(m automation.Metric) (int64, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return 0, err
	}
	lab, _ := json.Marshal(m.Labels)
	res, err := s.db.Exec(
		`INSERT INTO automation_metrics(run_id, case_id, name, value, text_value, unit, labels_json) VALUES(?,?,?,?,?,?,?)`,
		m.RunID, m.CaseID, m.Name, m.Value, m.TextValue, m.Unit, string(lab),
	)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// ListMetrics 拉指标。
func (s *Store) ListMetrics(runID int64) ([]automation.Metric, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return nil, err
	}
	rows, err := s.db.Query(
		`SELECT id, run_id, case_id, name, value, text_value, unit, labels_json FROM automation_metrics WHERE run_id=? ORDER BY id ASC`,
		runID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []automation.Metric{}
	for rows.Next() {
		var m automation.Metric
		var val sql.NullFloat64
		var lab string
		if err := rows.Scan(&m.ID, &m.RunID, &m.CaseID, &m.Name, &val, &m.TextValue, &m.Unit, &lab); err != nil {
			return nil, err
		}
		if val.Valid {
			v := val.Float64
			m.Value = &v
		}
		if lab != "" {
			_ = json.Unmarshal([]byte(lab), &m.Labels)
		}
		out = append(out, m)
	}
	return out, nil
}

// AddEvidence 落证据。
func (s *Store) AddEvidence(e automation.Evidence) (int64, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return 0, err
	}
	meta, _ := json.Marshal(e.Meta)
	res, err := s.db.Exec(
		`INSERT INTO automation_evidence(run_id, case_id, kind, path, title, metadata_json) VALUES(?,?,?,?,?,?)`,
		e.RunID, e.CaseID, e.Kind, e.Path, e.Title, string(meta),
	)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// ListEvidence 拉证据。
func (s *Store) ListEvidence(runID int64) ([]automation.Evidence, error) {
	if err := s.ensureAutomationSchema(); err != nil {
		return nil, err
	}
	rows, err := s.db.Query(
		`SELECT id, run_id, case_id, kind, path, title, metadata_json FROM automation_evidence WHERE run_id=? ORDER BY id ASC`,
		runID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []automation.Evidence{}
	for rows.Next() {
		var e automation.Evidence
		var meta string
		if err := rows.Scan(&e.ID, &e.RunID, &e.CaseID, &e.Kind, &e.Path, &e.Title, &meta); err != nil {
			return nil, err
		}
		if meta != "" {
			_ = json.Unmarshal([]byte(meta), &e.Meta)
		}
		out = append(out, e)
	}
	return out, nil
}

// MarkInterruptedRuns 启动时把 RUNNING 标记为 INTERRUPTED,除非 PID 仍活动。
func (s *Store) MarkInterruptedRuns(activePID int) error {
	if err := s.ensureAutomationSchema(); err != nil {
		return err
	}
	if activePID > 0 {
		_, err := s.db.Exec(`UPDATE automation_runs SET status='INTERRUPTED' WHERE status='RUNNING' AND pid<>?`, activePID)
		return err
	}
	_, err := s.db.Exec(`UPDATE automation_runs SET status='INTERRUPTED' WHERE status='RUNNING'`)
	return err
}