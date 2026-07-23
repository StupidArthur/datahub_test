// helpers.go - datahub_extra.go 使用的辅助函数(文件 IO、multipart、下载)。
package subject

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// bodyNull 返回用于 POST 但 body 为 {} 的请求体(对齐某些端点只接空 data)。
func bodyNull() map[string]any {
	return map[string]any{}
}

// truncate 截断字符串用于错误信息。
func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}

// joinStrings 用 sep 拼接字符串列表。
func joinStrings(ss []string, sep string) string {
	return strings.Join(ss, sep)
}

// baseName 取文件名的 basename(去路径)。
func baseName(path string) string {
	return filepath.Base(path)
}

// readFile 读文件全部内容。
func readFile(path string) ([]byte, error) {
	return os.ReadFile(path)
}

// writeFile 写文件。
func writeFile(path string, data []byte) error {
	return os.WriteFile(path, data, 0o644)
}

// multipartWriter 简易 multipart/form-data 写入器。
type multipartWriter struct {
	w        *multipartBody
	boundary string
}

type multipartBody struct {
	*bytes.Buffer
}

func (mb *multipartBody) Close() error { return nil }

func newMultipart(body *bytes.Buffer, boundary string) *multipartBody {
	return &multipartBody{Buffer: body}
}

// newMultipartWriter 构造一个 multipart/form-data 写入器。
func newMultipartWriter(buf *bytes.Buffer, boundary string) *multipartWriter {
	return &multipartWriter{w: newMultipart(buf, boundary), boundary: boundary}
}

// writeField 写普通字段。
func (m *multipartWriter) writeField(name, value string) {
	fmt.Fprintf(m.w, "--%s\r\n", m.boundary)
	fmt.Fprintf(m.w, "Content-Disposition: form-data; name=\"%s\"\r\n\r\n", name)
	fmt.Fprintf(m.w, "%s\r\n", value)
}

// writeFile 写文件字段。
func (m *multipartWriter) writeFile(field, filename, contentType string, data []byte) {
	fmt.Fprintf(m.w, "--%s\r\n", m.boundary)
	fmt.Fprintf(m.w, "Content-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n", field, filename)
	fmt.Fprintf(m.w, "Content-Type: %s\r\n\r\n", contentType)
	m.w.Write(data)
	fmt.Fprintf(m.w, "\r\n")
}

// close 写结尾 boundary。
func (m *multipartWriter) close() {
	fmt.Fprintf(m.w, "--%s--\r\n", m.boundary)
}

// downloadRequest 下载二进制内容(导出文件等),返回 raw bytes。
// 与 request() 不同:不假设响应是 JSON;若 content-type 包含 json 则视为错误。
func (c *TptClient) downloadRequest(method, path string, body any, wrap bool) ([]byte, error) {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")
	var jsonBody any
	if wrap && body != nil {
		jsonBody = map[string]any{"data": body}
	} else {
		jsonBody = body
	}
	var reqBody io.Reader
	if jsonBody != nil {
		b, err := marshalJSON(jsonBody)
		if err != nil {
			return nil, fmt.Errorf("请求序列化失败: %w", err)
		}
		reqBody = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, u, reqBody)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		data, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("http %d: %s", resp.StatusCode, truncate(string(data), 200))
	}
	ct := resp.Header.Get("content-type")
	if strings.Contains(ct, "json") {
		// 服务端返回 JSON 错误而非文件
		data, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("期望文件但收到 JSON: %s", truncate(string(data), 200))
	}
	return io.ReadAll(resp.Body)
}

// marshalJSON 单独封一层便于测试/替换。
func marshalJSON(v any) ([]byte, error) {
	return json.Marshal(v)
}