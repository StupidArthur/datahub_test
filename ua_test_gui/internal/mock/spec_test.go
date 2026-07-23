package mock

import "testing"

func TestBuildFunctionalCounts(t *testing.T) {
	s := BuildFunctional()
	if s.Key != "functional" {
		t.Errorf("Key=%q", s.Key)
	}
	if s.Port != PortFunctional {
		t.Errorf("Port=%d", s.Port)
	}
	// 13 类型 × 2 模式 × 10 = 260
	total := 0
	for _, n := range s.Nodes {
		total += n.Count
	}
	if total != 260 {
		t.Errorf("functional total=%d, want 260", total)
	}
}

func TestBuildPerformanceRatio(t *testing.T) {
	s := BuildPerformance(10000, 1000, 0.9)
	if s.Nodes[0].Count != 10000 {
		t.Errorf("poll count=%d, want 10000", s.Nodes[0].Count)
	}
	if s.Nodes[1].Count != 900 { // 1000*0.9
		t.Errorf("write double=%d, want 900", s.Nodes[1].Count)
	}
	if s.Nodes[2].Count != 100 { // 1000-900
		t.Errorf("write bool=%d, want 100", s.Nodes[2].Count)
	}
}

func TestBuildPerformanceDefaults(t *testing.T) {
	// 0/0/0 -> 默认 10000/1000/0.9
	s := BuildPerformance(0, 0, 0)
	if s.Nodes[0].Count != 10000 {
		t.Errorf("default poll=%d, want 10000", s.Nodes[0].Count)
	}
	if s.Nodes[1].Count != 900 {
		t.Errorf("default write double=%d, want 900", s.Nodes[1].Count)
	}
}

func TestBuildAbnormalBadLen(t *testing.T) {
	s := BuildAbnormal()
	// bad_len 5 档 + bad_val 13 类型 = 18 节点
	if len(s.Nodes) != 18 {
		t.Errorf("abnormal nodes=%d, want 18", len(s.Nodes))
	}
	// 前 5 个 bad_len:name 长度 = target-1(count=1 展开加 "1" 后 = target)
	wantLens := []int{8, 64, 128, 256, 512}
	for i, w := range wantLens {
		if len(s.Nodes[i].Name) != w-1 {
			t.Errorf("bad_len[%d] name len=%d, want %d", i, len(s.Nodes[i].Name), w-1)
		}
	}
}

func TestFindSpec(t *testing.T) {
	if _, ok := FindSpec("functional"); !ok {
		t.Error("functional not found")
	}
	if _, ok := FindSpec("nope"); ok {
		t.Error("nope should not be found")
	}
}

func TestAllSpecsCount(t *testing.T) {
	if len(AllSpecs()) != 4 {
		t.Errorf("specs=%d, want 4", len(AllSpecs()))
	}
}

func TestEndpointFor(t *testing.T) {
	got := EndpointFor("10.10.58.153", 18960)
	want := "opc.tcp://10.10.58.153:18960/ua_mocker/"
	if got != want {
		t.Errorf("EndpointFor=%q, want %q", got, want)
	}
}

func TestTagSpecsFromMock(t *testing.T) {
	s := BuildFunctional()
	specs := TagSpecsFromMock(s, 10)
	// 260 节点展开 + 1 heartbeat = 261
	if len(specs) != 261 {
		t.Errorf("tag specs=%d, want 261", len(specs))
	}
	// 末尾 heartbeat
	last := specs[len(specs)-1]
	if last.Name != "mock_hb1" {
		t.Errorf("heartbeat=%q, want mock_hb1", last.Name)
	}
	if last.MockerType != "Int32" {
		t.Errorf("heartbeat type=%q, want Int32", last.MockerType)
	}
	// frequency<=0 -> 默认 10
	specs0 := TagSpecsFromMock(s, 0)
	if specs0[0].Frequency != 10 {
		t.Errorf("default freq=%d, want 10", specs0[0].Frequency)
	}
}
