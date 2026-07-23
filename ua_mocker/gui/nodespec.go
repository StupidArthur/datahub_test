// -*- coding: utf-8 -*-
/*
nodespec.go — 内置组态模型：ua_types 风格，13 种 OPC UA 类型 × 2 节点 = 26 节点。

组态构成与 ua2_types.yaml 一致：每类型 1 个自变化只读节点 + 1 个可写固定值节点。
本文件是 GUI 侧的组态"真源"：yamlgen 据此生成服务端 YAML，前端节点列表据此展示，
两处共用同一份规格，避免双份维护漂移。

对外接口：
  - ModeChange / ModeWritable：节点模式常量
  - NamespaceIndex：命名空间索引
  - NodeSpec：单节点规格
  - BuildNodeSpecs()：生成全部 26 个节点规格
*/
package main

// 节点模式：change = 自动变化只读；writable = 固定可写
const (
	ModeChange   = "change"
	ModeWritable = "writable"
)

// 命名空间索引，与 ua2_types.yaml 保持一致
const NamespaceIndex = 2

// 命名约定（沿用 ua2_types.yaml）：ua2_<type>_r_1 / ua2_<type>_w_1。
// Python 服务以 name 前缀 + 下标(1..count)拼 NodeId，故 YAML 中 name 为去掉末尾下标的前缀。
const (
	namePrefix = "ua2_"
	readInfix  = "_r_"
	writeInfix = "_w_"
	nodeIndex  = "1" // 每类型固定 1 个节点
)

// NodeSpec 单节点规格。
// Default 以字符串承载各类型默认值（展示与 YAML 渲染两用）；change 节点无默认值，为空串。
type NodeSpec struct {
	NodeID  string `json:"nodeId"`
	Type    string `json:"type"`
	Mode    string `json:"mode"`
	Default string `json:"default"`
}

// typeEntry 类型表项：
//   - TypeName 与 Python 版 type_mapping.py 的 TYPE_MAP 键严格一致（Boolean/SByte/...）
//   - Slug 为节点名用的小写片段
//   - Default 为可写节点默认值，取值与 ua2_types.yaml 一致
var typeEntries = []struct {
	TypeName string
	Slug     string
	Default  string
}{
	{"Boolean", "boolean", "false"},
	{"SByte", "sbyte", "0"},
	{"Byte", "byte", "0"},
	{"Int16", "int16", "0"},
	{"UInt16", "uint16", "0"},
	{"Int32", "int32", "0"},
	{"UInt32", "uint32", "0"},
	{"Int64", "int64", "0"},
	{"UInt64", "uint64", "0"},
	{"Float", "float", "0.0"},
	{"Double", "double", "0.0"},
	{"String", "string", "ua2"},
	{"DateTime", "datetime", "2025-01-01T00:00:00+00:00"},
}

// BuildNodeSpecs 生成全部 26 个节点规格：每类型先 r（自变化）后 w（可写）。
func BuildNodeSpecs() []NodeSpec {
	specs := make([]NodeSpec, 0, len(typeEntries)*2)
	for _, e := range typeEntries {
		specs = append(specs,
			NodeSpec{
				NodeID: namePrefix + e.Slug + readInfix + nodeIndex,
				Type:   e.TypeName,
				Mode:   ModeChange,
			},
			NodeSpec{
				NodeID:  namePrefix + e.Slug + writeInfix + nodeIndex,
				Type:    e.TypeName,
				Mode:    ModeWritable,
				Default: e.Default,
			},
		)
	}
	return specs
}
