// spec.go - 4 套 ua_mocker 位号方案构建 + TagSpec 展开。
//
// 生成的 YAML 满足 ua_mocker/config_loader.py 校验:
//   - 顶层必填 server/port/cycle/namespace_index/nodes
//   - node 必填 name/type/count/change/writable
//   - change=false 必须有 default
package mock

import (
	"fmt"
	"strings"
)

// badLenTargets 异常测试位号名长度档(对齐 mock_manager.py BAD_LEN_TARGETS)。
var badLenTargets = []int{8, 64, 128, 256, 512}

// modeNodes 每类型每模式 1 个 spec:prefix_{type}_{mode}_ ,count 展开为 _1..N。
// r=轮询(change=true 自动变,不可写);w=可写(change=false 静止,需 default)。
func modeNodes(prefix string, count int) []UaNodeSpec {
	var nodes []UaNodeSpec
	for _, t := range allTypes {
		// r: 轮询(自动变,不可写)
		nodes = append(nodes, UaNodeSpec{
			Name: fmt.Sprintf("%s_%s_r_", prefix, t), Type: t, Count: count,
			Change: true, Writable: false,
		})
		// w: 可写(静止,靠写值变;change=false 必须 default)
		nodes = append(nodes, UaNodeSpec{
			Name: fmt.Sprintf("%s_%s_w_", prefix, t), Type: t, Count: count,
			Change: false, Writable: true, Default: DefaultFor(t),
		})
	}
	return nodes
}

// BuildFunctional 功能遍历:13 类型 × 2 模式 × 10 = 260 位号。
func BuildFunctional() MockSpec {
	return MockSpec{
		Key: "functional", Name: "功能遍历", Port: PortFunctional, CycleMs: HeartbeatCycleMs,
		Nodes: modeNodes("mock", 10), HeartbeatTag: "mock_hb",
		Desc: "13 类型 × 2 模式(轮询/可写) × 10 = 260 位号,遍历读写全类型",
	}
}

// BuildReconnect 断线重连:260 位号,起停此 server 测 TPT 断线重连。
func BuildReconnect() MockSpec {
	return MockSpec{
		Key: "reconnect", Name: "断线重连", Port: PortReconnect, CycleMs: HeartbeatCycleMs,
		Nodes: modeNodes("connect", 10), HeartbeatTag: "connect_hb",
		Desc: "13 × 2 × 10 = 260 位号;起停此 server 测 TPT 断线重连",
	}
}

// BuildPerformance 性能测试:pollN 轮询 Double + writeN 可写(Double:Bool = ratio:1-ratio)。
func BuildPerformance(pollN, writeN int, writeDoubleRatio float64) MockSpec {
	if pollN <= 0 {
		pollN = 10000
	}
	if writeN <= 0 {
		writeN = 1000
	}
	if writeDoubleRatio <= 0 {
		writeDoubleRatio = 0.9
	}
	nDouble := int(float64(writeN) * writeDoubleRatio)
	nBool := writeN - nDouble
	nodes := []UaNodeSpec{
		{Name: "perf_Double_r_", Type: "Double", Count: pollN, Change: true, Writable: false},
		{Name: "perf_Double_w_", Type: "Double", Count: nDouble, Change: false, Writable: true, Default: 0.0},
		{Name: "perf_Boolean_w_", Type: "Boolean", Count: nBool, Change: false, Writable: true, Default: false},
	}
	return MockSpec{
		Key: "performance", Name: "性能测试", Port: PortPerformance, CycleMs: HeartbeatCycleMs,
		Nodes: nodes, HeartbeatTag: "perf_hb",
		Desc: fmt.Sprintf("轮询 Double×%d + 可写 Double×%d/Bool×%d", pollN, nDouble, nBool),
	}
}

// BuildAbnormal 异常测试:bad_len 5 档(名长 8/64/128/256/512) + bad_val 13 类型可写。
func BuildAbnormal() MockSpec {
	var nodes []UaNodeSpec
	// bad_len:5 档位号名长度。count=1 展开为 name1,故 name 长度 = target-1
	for _, target := range badLenTargets {
		base := "badlen"
		name := base + strings.Repeat("x", target-1-len(base))
		nodes = append(nodes, UaNodeSpec{
			Name: name, Type: "Double", Count: 1, Change: true, Writable: false,
		})
	}
	// bad_val:13 类型各 1 个可写节点
	for _, t := range allTypes {
		nodes = append(nodes, UaNodeSpec{
			Name: fmt.Sprintf("bad_val_%s_", t), Type: t, Count: 1,
			Change: false, Writable: true, Default: DefaultFor(t),
		})
	}
	return MockSpec{
		Key: "abnormal", Name: "异常测试", Port: PortAbnormal, CycleMs: HeartbeatCycleMs,
		Nodes: nodes, HeartbeatTag: "bad_hb",
		Desc: fmt.Sprintf("bad_len 5 档(名长 %v) + bad_val 13 类型可写 = %d 位号", badLenTargets, len(nodes)),
	}
}

// AllSpecs 返回 4 套 mock 方案。
func AllSpecs() []MockSpec {
	return []MockSpec{
		BuildFunctional(),
		BuildReconnect(),
		BuildPerformance(10000, 1000, 0.9),
		BuildAbnormal(),
	}
}

// FindSpec 按 key 查单套。
func FindSpec(key string) (MockSpec, bool) {
	for _, s := range AllSpecs() {
		if s.Key == key {
			return s, true
		}
	}
	return MockSpec{}, false
}

// EndpointFor 构造 OPC UA endpoint(对齐 ua_config_builder.endpoint_for)。
func EndpointFor(host string, port int) string {
	return fmt.Sprintf("opc.tcp://%s:%d/ua_mocker/", host, port)
}

// TagSpecsFromMock 从 MockSpec 展开 TagSpec 列表(展开 count + heartbeat {tag}1)。
func TagSpecsFromMock(spec MockSpec, frequency int) []TagSpec {
	if frequency <= 0 {
		frequency = 10
	}
	var specs []TagSpec
	for _, n := range spec.Nodes {
		for _, nid := range ExpandNodeIDs(n.Name, n.Count) {
			specs = append(specs, TagSpec{
				Name: nid, MockerType: n.Type, Writable: n.Writable, Frequency: frequency,
			})
		}
	}
	// heartbeat 节点:展开为 {heartbeat_tag}1
	specs = append(specs, TagSpec{
		Name: spec.HeartbeatTag + "1", MockerType: "Int32", Writable: false, Frequency: frequency,
	})
	return specs
}
