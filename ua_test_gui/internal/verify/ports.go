// ports.go - 验证依赖的外部能力接口(由 adapters 实现,verify 只依赖接口)。
//
// 依赖方向:adapters/opcua、adapters/sqlite -> verify(实现接口);verify 不反向依赖 adapter。
package verify

import "context"

// SourceClient 源端(OPC UA)读写接口,由 adapters/opcua 实现。
// verify 经此接口读/写 mock 节点(绕过 TPT 直连源端)。
type SourceClient interface {
	Connect(ctx context.Context) error
	Close(ctx context.Context) error
	Read(ctx context.Context, name string) (any, error)
	Write(ctx context.Context, name string, value any) error
}

// ResultStore 验证结果持久化接口,由 adapters/sqlite 实现。
// runtime-safety:每跑完一个 tag 立即 AddTagResult,crash 只丢当前 tag;DoneTags 支持续跑。
type ResultStore interface {
	CreateRun(env, mockKey string, total int) int64
	AddTagResult(runID int64, tr VerifyTagResult) error
	UpdateRunProgress(runID int64, progress int)
	FinishRun(runID int64, passed, failed int)
	DoneTags(runID int64) map[string]bool
	ListRuns() []RunRecord
	GetRunDetail(runID int64) (RunRecord, []VerifyTagResult, error)
	Close() error
}

// SourceClientFactory 源端 client 工厂接口,由 adapters/opcua 实现。
// verify.Service 经此创建 SourceClient,不直接依赖 opcua 实现(依赖方向:opcua -> verify)。
type SourceClientFactory interface {
	NewSourceClient(endpoint string, namespaceIndex int) SourceClient
}
