// model.go - mock 方案数据模型(MockSpec / UaNodeSpec / TagSpec / MockRuntime / MockerConfig)。
package mock

// 端口规划(对齐 mock_manager.py)
const (
	PortFunctional  = 18960
	PortReconnect   = 18961
	PortPerformance = 18962
	PortAbnormal    = 18963

	HeartbeatType    = "Int32"
	HeartbeatCycleMs = 1000
)

// UaNodeSpec 一条 ua_mocker 节点定义(对齐 app_config.UaNodeSpec)。
//
// 兼容旧字段(Name/Type/Count/Change/Writable/Default);新增可选字段
// (Mode/SequenceStart/SequenceStep/FailRead/StatusCode/TimestampOffsetMs)用于
// plan.md 10.2 的扩展,旧 YAML 不带这些字段时使用零值即可。
type UaNodeSpec struct {
	Name                string
	Type                string
	Count               int
	Change              bool
	Writable            bool
	Default             any // Change=false 时必填
	Mode                string  // static|increment|toggle|sequence(空=按 Change 推断)
	SequenceStart       float64 // sequence/increment 起始值
	SequenceStep        float64 // sequence/increment 步长
	FailRead            bool    // 单节点异常(探索)
	StatusCode          int     // asyncua 可选 status code
	TimestampOffsetMs   int     // server/source timestamp 偏移
}

// MockSpec 一套 mock 方案(对齐 mock_manager.MockSpec)。
type MockSpec struct {
	Key          string // functional/reconnect/performance/abnormal
	Name         string // 中文用途
	Port         int
	CycleMs      int
	Nodes        []UaNodeSpec
	HeartbeatTag string // 展开为 {tag}1
	Desc         string
}

// Endpoint 返回 mock 的 OPC UA endpoint(本机视角)。
func (s MockSpec) Endpoint() string {
	return EndpointFor("127.0.0.1", s.Port)
}

// NodeCount 节点总数(展开 count 后)。
func (s MockSpec) NodeCount() int {
	n := 0
	for _, nd := range s.Nodes {
		if nd.Count < 1 {
			n++
		} else {
			n += nd.Count
		}
	}
	return n
}

// TagSpec 从 mock 展开的位号开通规格(供 provision/verify 使用)。
type TagSpec struct {
	Name       string `json:"name"`
	MockerType string `json:"mockerType"`
	Writable   bool   `json:"writable"`
	Frequency  int    `json:"frequency"`
}

// MockRuntime 一套 mock 的运行态(纯业务字段,可序列化;cmd/logFile 等实现细节由 adapter 持有)。
type MockRuntime struct {
	Spec       MockSpec `json:"spec"`
	PID        int      `json:"pid"`
	ConfigPath string   `json:"configPath"`
	LogPath    string   `json:"logPath"`
	Status     string   `json:"status"` // stopped / starting / ready / failed
	Reason     string   `json:"reason"` // failed 时的退出原因
	Endpoint   string   `json:"endpoint"`
}

// MockerConfig ua_mocker 运行环境配置(仓库路径 + python + 可选 exe)。
type MockerConfig struct {
	Repo   string `json:"repo"`   // ua_mocker 目录(含 main.py + config_loader.py)
	Python string `json:"python"` // python 可执行
	Exe    string `json:"exe"`    // ua_mocker.exe 路径(优先用;空=未配置)
}
