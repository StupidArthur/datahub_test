// yaml.go - MockSpec -> ua_mocker YAML 生成(对齐 ua_config_builder.build_mocker_yaml)。
package mock

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// yamlNode ua_mocker YAML 的 node 结构。Default 用指针 + omitempty:
// change=true 时 nil -> 省略 default 键;change=false 时非 nil -> 输出(含 0/false)。
// 精确对齐 config_loader 校验(change=false 必须有 default)与 python yaml.safe_dump 行为。
type yamlNode struct {
	Name     string `yaml:"name"`
	Type     string `yaml:"type"`
	Count    int    `yaml:"count"`
	Change   bool   `yaml:"change"`
	Writable bool   `yaml:"writable"`
	Default  *any   `yaml:"default,omitempty"`
}

// yamlConfig ua_mocker YAML 顶层结构。
type yamlConfig struct {
	Server         string     `yaml:"server"`
	Port           int        `yaml:"port"`
	Cycle          int        `yaml:"cycle"`
	NamespaceIndex int        `yaml:"namespace_index"`
	Nodes          []yamlNode `yaml:"nodes"`
}

// BuildMockerYAML 把 MockSpec 写成 ua_mocker YAML,自动追加 heartbeat 节点。
// mock 监听 0.0.0.0(TPT 经 local_ip 连入)。
func BuildMockerYAML(spec MockSpec, outPath string) error {
	nodes := make([]yamlNode, 0, len(spec.Nodes)+1)
	for _, n := range spec.Nodes {
		yn := yamlNode{
			Name: n.Name, Type: n.Type, Count: n.Count,
			Change: n.Change, Writable: n.Writable,
		}
		if !n.Change {
			d := n.Default
			if d == nil {
				d = DefaultFor(n.Type)
			}
			yn.Default = &d
		}
		nodes = append(nodes, yn)
	}
	// heartbeat 节点:Int32 change=true,0~99 sawtooth(cycle=1000ms)
	nodes = append(nodes, yamlNode{
		Name: spec.HeartbeatTag, Type: HeartbeatType, Count: 1,
		Change: true, Writable: false,
	})
	cfg := yamlConfig{
		Server:         "0.0.0.0",
		Port:           spec.Port,
		Cycle:          spec.CycleMs,
		NamespaceIndex: 1,
		Nodes:          nodes,
	}
	if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
		return err
	}
	f, err := os.Create(outPath)
	if err != nil {
		return err
	}
	defer f.Close()
	enc := yaml.NewEncoder(f)
	enc.SetIndent(2)
	if err := enc.Encode(cfg); err != nil {
		return err
	}
	return enc.Close()
}
