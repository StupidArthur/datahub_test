// store.go - SQLite 持久化(验证 run + tag 级结果),实现 verify.ResultStore。
//
// runtime-safety 横切规则:
//   - 增量持久化:每跑完一个 tag 立即 AddTagResult,crash 只丢当前 tag,已跑全保留
//   - 崩溃恢复:runs.progress 记已验证 tag 数,DoneTags 查已落库 tag,续跑跳过
//
// 驱动 modernc.org/sqlite(纯 go 无 cgo,保 wails exe 体积)。
// 依赖方向:sqlite -> verify(import RunRecord/VerifyTagResult 类型,实现 ResultStore 接口)。
package sqlite

import (
	"database/sql"
	"encoding/json"
	"time"

	_ "modernc.org/sqlite"

	"ua_test_gui/internal/verify"
)

// Store SQLite 持久化句柄。
type Store struct {
	db *sql.DB
}

const storeSchema = `
CREATE TABLE IF NOT EXISTS runs (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	started_at TEXT NOT NULL,
	finished_at TEXT,
	status TEXT NOT NULL,
	env TEXT,
	mock_key TEXT,
	total INTEGER DEFAULT 0,
	passed INTEGER DEFAULT 0,
	failed INTEGER DEFAULT 0,
	progress INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tag_results (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	run_id INTEGER NOT NULL,
	tag_name TEXT,
	type TEXT,
	rt_before TEXT,
	src_before TEXT,
	write_val TEXT,
	rt_after TEXT,
	ok INTEGER,
	msg TEXT,
	ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tag_results_run ON tag_results(run_id);
`

// OpenStore 打开/建库。path 为 sqlite 文件路径。
func OpenStore(path string) (*Store, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(storeSchema); err != nil {
		db.Close()
		return nil, err
	}
	s := &Store{db: db}
	if err := s.ensureAutomationSchema(); err != nil {
		db.Close()
		return nil, err
	}
	return s, nil
}

// Close 关闭。
func (s *Store) Close() error { return s.db.Close() }

// CreateRun 新建一条 run,返回 id。
func (s *Store) CreateRun(env, mockKey string, total int) int64 {
	now := time.Now().Format(time.RFC3339)
	res, err := s.db.Exec(
		`INSERT INTO runs(started_at, status, env, mock_key, total) VALUES(?, 'running', ?, ?, ?)`,
		now, env, mockKey, total)
	if err != nil {
		return 0
	}
	id, _ := res.LastInsertId()
	return id
}

// AddTagResult 增量写入一条 tag 结果(每跑完一个 tag 立即调)。
func (s *Store) AddTagResult(runID int64, tr verify.VerifyTagResult) error {
	now := time.Now().Format(time.RFC3339)
	ok := 0
	if tr.OK {
		ok = 1
	}
	_, err := s.db.Exec(
		`INSERT INTO tag_results(run_id, tag_name, type, rt_before, src_before, write_val, rt_after, ok, msg, ts)
		 VALUES(?,?,?,?,?,?,?,?,?,?)`,
		runID, tr.TagName, tr.Type,
		string(tr.RtBefore), string(tr.SrcBefore), string(tr.WriteVal), string(tr.RtAfter),
		ok, tr.Msg, now)
	return err
}

// UpdateRunProgress 更新已验证 tag 数(断点续跑用)。
func (s *Store) UpdateRunProgress(runID int64, progress int) {
	s.db.Exec(`UPDATE runs SET progress=? WHERE id=?`, progress, runID)
}

// FinishRun 标记 run 完成。
func (s *Store) FinishRun(runID int64, passed, failed int) {
	now := time.Now().Format(time.RFC3339)
	s.db.Exec(`UPDATE runs SET finished_at=?, status='finished', passed=?, failed=? WHERE id=?`,
		now, passed, failed, runID)
}

// DoneTags 返回某 run 已落库的 tag 名集合(续跑跳过用)。
func (s *Store) DoneTags(runID int64) map[string]bool {
	out := map[string]bool{}
	rows, err := s.db.Query(`SELECT tag_name FROM tag_results WHERE run_id=?`, runID)
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var name string
		rows.Scan(&name)
		out[name] = true
	}
	return out
}

// ListRuns 列出所有 run(新在前)。
func (s *Store) ListRuns() []verify.RunRecord {
	rows, err := s.db.Query(
		`SELECT id, started_at, finished_at, status, env, mock_key, total, passed, failed, progress
		 FROM runs ORDER BY id DESC`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []verify.RunRecord
	for rows.Next() {
		var r verify.RunRecord
		rows.Scan(&r.ID, &r.StartedAt, &r.FinishedAt, &r.Status, &r.Env, &r.MockKey,
			&r.Total, &r.Passed, &r.Failed, &r.Progress)
		out = append(out, r)
	}
	return out
}

// GetRunDetail 取单 run + 其全部 tag 结果。
func (s *Store) GetRunDetail(runID int64) (verify.RunRecord, []verify.VerifyTagResult, error) {
	var r verify.RunRecord
	err := s.db.QueryRow(
		`SELECT id, started_at, finished_at, status, env, mock_key, total, passed, failed, progress
		 FROM runs WHERE id=?`, runID).
		Scan(&r.ID, &r.StartedAt, &r.FinishedAt, &r.Status, &r.Env, &r.MockKey,
			&r.Total, &r.Passed, &r.Failed, &r.Progress)
	if err != nil {
		return r, nil, err
	}
	rows, err := s.db.Query(
		`SELECT tag_name, type, rt_before, src_before, write_val, rt_after, ok, msg
		 FROM tag_results WHERE run_id=? ORDER BY id`, runID)
	if err != nil {
		return r, nil, err
	}
	defer rows.Close()
	var results []verify.VerifyTagResult
	for rows.Next() {
		var tr verify.VerifyTagResult
		var rtBefore, srcBefore, writeVal, rtAfter string
		var ok int
		rows.Scan(&tr.TagName, &tr.Type, &rtBefore, &srcBefore, &writeVal, &rtAfter, &ok, &tr.Msg)
		tr.RtBefore = toRaw(rtBefore)
		tr.SrcBefore = toRaw(srcBefore)
		tr.WriteVal = toRaw(writeVal)
		tr.RtAfter = toRaw(rtAfter)
		tr.OK = ok == 1
		results = append(results, tr)
	}
	return r, results, nil
}

func toRaw(s string) json.RawMessage {
	if s == "" {
		return nil
	}
	return json.RawMessage(s)
}
