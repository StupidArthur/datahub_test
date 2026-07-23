// util.go - binding 层公共工具。
package bindings

import (
	"fmt"
	"io"
	"os"

	"ua_test_gui/internal/automation"
)

// RecoverPanic 在 defer 中调用,捕获 panic 转 error(配合命名返回值 err)。
// 替代原 App.recoverErr:错误经 (T, error) 返回,前端 Promise reject。
func RecoverPanic(err *error) {
	if r := recover(); r != nil {
		*err = fmt.Errorf("panic: %v", r)
	}
}

// readFileChunk 分页读文件。
func readFileChunk(path string, offset int64, limit int) (automation.LogChunk, error) {
	chunk := automation.LogChunk{}
	if limit <= 0 || limit > 1024*1024 {
		limit = 64 * 1024
	}
	f, err := os.Open(path)
	if err != nil {
		return chunk, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return chunk, err
	}
	size := st.Size()
	if offset < 0 {
		offset = 0
	}
	if offset >= size {
		chunk.Offset = offset
		chunk.Next = offset
		chunk.EOF = true
		return chunk, nil
	}
	buf := make([]byte, limit)
	n, rerr := f.ReadAt(buf, offset)
	if rerr != nil && rerr != io.EOF {
		return chunk, rerr
	}
	chunk.Offset = offset
	chunk.Content = string(buf[:n])
	chunk.Next = offset + int64(n)
	chunk.EOF = rerr == io.EOF || chunk.Next >= size
	return chunk, nil
}
