// -*- coding: utf-8 -*-
package main

import (
	"strings"
	"testing"
)

func TestGenerateYAMLBasics(t *testing.T) {
	y := GenerateYAML(18955, 1000)
	for _, want := range []string{
		`server: "0.0.0.0"`,
		`port: 18955`,
		`cycle: 1000`,
		`namespace_index: 2`,
		`nodes:`,
	} {
		if !strings.Contains(y, want) {
			t.Errorf("YAML 应包含 %q", want)
		}
	}
}

func TestGenerateYAMLNodeComposition(t *testing.T) {
	y := GenerateYAML(18955, 1000)
	if got := strings.Count(y, "change: true"); got != 13 {
		t.Errorf("应有 13 个 change:true，实际 %d", got)
	}
	if got := strings.Count(y, "writable: true"); got != 13 {
		t.Errorf("应有 13 个 writable:true，实际 %d", got)
	}
	// change=false 必带 default（Python config_loader 强制校验）
	if got := strings.Count(y, "default:"); got != 13 {
		t.Errorf("应有 13 个 default 行，实际 %d", got)
	}
	if got := strings.Count(y, "- name:"); got != 26 {
		t.Errorf("应有 26 个节点条目，实际 %d", got)
	}
}

func TestGenerateYAMLDefaultRendering(t *testing.T) {
	y := GenerateYAML(18955, 1000)
	// DateTime / String 加引号：避免 PyYAML 解析成时间戳对象 / 吃掉空串
	if !strings.Contains(y, "default: '2025-01-01T00:00:00+00:00'") {
		t.Error("DateTime 默认值应加单引号")
	}
	if !strings.Contains(y, "default: 'ua2'") {
		t.Error("String 默认值应加单引号")
	}
	// Boolean / 数值原样
	if !strings.Contains(y, "default: false") {
		t.Error("Boolean 默认值应为 false")
	}
	if !strings.Contains(y, "default: 0.0") {
		t.Error("Double 默认值应为 0.0")
	}
}

func TestGenerateYAMLNamePrefixes(t *testing.T) {
	y := GenerateYAML(18955, 1000)
	for _, want := range []string{`"ua2_boolean_r_"`, `"ua2_boolean_w_"`, `"ua2_datetime_r_"`, `"ua2_datetime_w_"`} {
		if !strings.Contains(y, want) {
			t.Errorf("YAML 应包含 name %s", want)
		}
	}
}

func TestGenerateYAMLParamsInjected(t *testing.T) {
	y := GenerateYAML(20000, 500)
	if !strings.Contains(y, "port: 20000") || !strings.Contains(y, "cycle: 500") {
		t.Error("端口/周期参数应注入 YAML")
	}
}
