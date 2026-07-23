package tptapi

import "io"

// io_ReadAll 是为测试用的薄包装，避免每个 _test.go 文件重复 import。
func io_ReadAll(r io.Reader) ([]byte, error) { return io.ReadAll(r) }
