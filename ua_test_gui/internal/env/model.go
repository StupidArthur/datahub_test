// model.go - OS 环境检测数据模型 + mock 端口区间。
package env

// mock 端口预留区间(对齐 os_env.py PORT_RANGE 18960~18969)
const (
	PortStart = 18960
	PortEnd   = 18969 // 含
)

// PortStatus 单端口占用状态。
type PortStatus struct {
	Port    int    `json:"port"`
	InUse   bool   `json:"inUse"`
	PID     int    `json:"pid"`
	Process string `json:"process"`
}

// OsEnvReport OS 环境报告(供前端环境页展示)。
type OsEnvReport struct {
	Ports           []PortStatus `json:"ports"`
	LocalIPs        []string     `json:"localIps"`
	ConnectivityOK  bool         `json:"connectivityOk"`
	ConnectivityMsg string       `json:"connectivityMsg"`
}
