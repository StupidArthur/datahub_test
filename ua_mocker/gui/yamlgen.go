// -*- coding: utf-8 -*-
/*
yamlgen.go — 将内置组态渲染为 YAML 文本，供现有 Python 服务的 config_loader 消费。

对外接口：
  - GenerateYAML(port, cycleMs int) string

渲染约定（与 ua2_types.yaml 对齐）：
  - change=false 节点必带 default（Python 版 config_loader 强制校验）
  - String / DateTime 默认值加单引号：避免 PyYAML 把空串吃掉、把 ISO 时间解析成 datetime 对象
  - Boolean / 数值默认值原样输出（false / 0 / 0.0）
*/
package main

import (
	"fmt"
	"strings"
)

// 服务监听地址固定为全网卡，不开放界面调整（Mock 服务需要被外部客户端连入）
const serverHost = "0.0.0.0"

// yamlDefault 按类型渲染默认值的 YAML 字面量。
func yamlDefault(s NodeSpec) string {
	switch s.Type {
	case "String", "DateTime":
		// 单引号标量；YAML 单引号内以两个单引号转义单引号
		return "'" + strings.ReplaceAll(s.Default, "'", "''") + "'"
	default:
		return s.Default
	}
}

// GenerateYAML 由 26 节点规格 + 端口/周期生成完整组态文本。
func GenerateYAML(port, cycleMs int) string {
	var b strings.Builder
	b.WriteString("# 由 UA Types Mock GUI 自动生成：13 类型 × (1 自变化 + 1 可写) = 26 节点\n")
	fmt.Fprintf(&b, "server: %q\n", serverHost)
	fmt.Fprintf(&b, "port: %d\n", port)
	fmt.Fprintf(&b, "cycle: %d\n", cycleMs)
	fmt.Fprintf(&b, "namespace_index: %d\n", NamespaceIndex)
	b.WriteString("nodes:\n")
	for _, s := range BuildNodeSpecs() {
		// Python 服务以 name + 下标拼 NodeId（见 server_main._node_id_string），
		// 故 name 为 NodeID 去掉末尾下标 "1"
		name := strings.TrimSuffix(s.NodeID, nodeIndex)
		fmt.Fprintf(&b, "  - name: %q\n", name)
		fmt.Fprintf(&b, "    type: %s\n", s.Type)
		b.WriteString("    count: 1\n")
		if s.Mode == ModeChange {
			b.WriteString("    change: true\n")
			b.WriteString("    writable: false\n")
		} else {
			b.WriteString("    change: false\n")
			b.WriteString("    writable: true\n")
			fmt.Fprintf(&b, "    default: %s\n", yamlDefault(s))
		}
	}
	return b.String()
}
