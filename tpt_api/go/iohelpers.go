package tptapi

import "os"

// writeFileImpl 是包内 helper（与 algorithms_test.go 的 writeFile 配对）。
func writeFileImpl(path string, b []byte) error {
	return os.WriteFile(path, b, 0o644)
}
