// typemap.go - ua_mocker 类型 <-> TPT dataType 映射 + 节点名展开 + 默认值。
package mock

import (
	"fmt"
	"strings"
)

// mockerTypeToTPT ua_mocker 类型名 -> TPT dataType code(对齐 type_map.MOCKER_TYPE_TO_TPT)。
// 2026-07-10 实测 String=12、DateTime=13 已支持。
var mockerTypeToTPT = map[string]int{
	"Boolean": 1, "SByte": 2, "Byte": 3, "Int16": 4, "UInt16": 5,
	"Int32": 6, "UInt32": 7, "Int64": 8, "UInt64": 9,
	"Float": 10, "Double": 11, "String": 12, "DateTime": 13,
}

// allTypes ua_mocker 全部 13 类型名。
var allTypes = []string{
	"Boolean", "SByte", "Byte", "Int16", "UInt16",
	"Int32", "UInt32", "Int64", "UInt64",
	"Float", "Double", "String", "DateTime",
}

// SupportedTypes TPT 支持的全部 13 类型(2026-07-10 起包含 String/DateTime)。
var SupportedTypes = []string{
	"Boolean", "SByte", "Byte", "Int16", "UInt16",
	"Int32", "UInt32", "Int64", "UInt64",
	"Float", "Double", "String", "DateTime",
}

// AllTypes 返回全部 13 类型(只读视图)。
func AllTypes() []string { return allTypes }

// TptDataType 返回 mocker 类型对应的 TPT dataType;不支持返回 (0,false)。
func TptDataType(mockerType string) (int, bool) {
	dt, ok := mockerTypeToTPT[strings.TrimSpace(mockerType)]
	return dt, ok
}

// ExpandNodeIDs 展开 ua_mocker 约定的位号名:name + i, i=1..count -> name1..nameN。
func ExpandNodeIDs(name string, count int) []string {
	if count < 1 {
		count = 1
	}
	out := make([]string, 0, count)
	for i := 1; i <= count; i++ {
		out = append(out, fmt.Sprintf("%s%d", name, i))
	}
	return out
}

// DefaultFor 返回 change=false 时的默认值(对齐 type_map.default_for)。
func DefaultFor(mockerType string) any {
	switch strings.TrimSpace(mockerType) {
	case "Boolean":
		return false
	case "Float", "Double":
		return 0.0
	case "String":
		return ""
	case "DateTime":
		return "2025-01-01T00:00:00Z"
	default: // SByte/Byte/Int*/UInt*
		return 0
	}
}
