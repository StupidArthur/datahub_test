// -*- coding: utf-8 -*-
package main

import "testing"

func TestBuildNodeSpecsCount(t *testing.T) {
	specs := BuildNodeSpecs()
	if len(specs) != 26 {
		t.Fatalf("应为 26 个节点，实际 %d", len(specs))
	}
}

func TestBuildNodeSpecsTypeCoverage(t *testing.T) {
	specs := BuildNodeSpecs()
	perType := map[string]map[string]int{}
	for _, s := range specs {
		if perType[s.Type] == nil {
			perType[s.Type] = map[string]int{}
		}
		perType[s.Type][s.Mode]++
	}
	// 13 类型 × (1 change + 1 writable)
	if len(perType) != 13 {
		t.Errorf("应覆盖 13 种类型，实际 %d", len(perType))
	}
	for typ, modes := range perType {
		if modes[ModeChange] != 1 || modes[ModeWritable] != 1 {
			t.Errorf("类型 %s 应为 1 change + 1 writable，实际 %v", typ, modes)
		}
	}
}

func TestBuildNodeSpecsDefaults(t *testing.T) {
	for _, s := range BuildNodeSpecs() {
		if s.Mode == ModeChange && s.Default != "" {
			t.Errorf("change 节点 %s 不应有默认值", s.NodeID)
		}
		if s.Mode == ModeWritable && s.Default == "" {
			t.Errorf("writable 节点 %s 必须有默认值", s.NodeID)
		}
	}
}

func TestBuildNodeSpecsNaming(t *testing.T) {
	specs := BuildNodeSpecs()
	// 首两条应为 Boolean 的 r/w 节点，命名沿用 ua2_types 约定
	if specs[0].NodeID != "ua2_boolean_r_1" {
		t.Errorf("首节点命名异常: %s", specs[0].NodeID)
	}
	if specs[1].NodeID != "ua2_boolean_w_1" {
		t.Errorf("次节点命名异常: %s", specs[1].NodeID)
	}
	// 末两条应为 DateTime
	if specs[24].NodeID != "ua2_datetime_r_1" || specs[25].NodeID != "ua2_datetime_w_1" {
		t.Errorf("末两条应为 DateTime: %s / %s", specs[24].NodeID, specs[25].NodeID)
	}
}
