package tptapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// alg-manager 算法管理端点（与 alg_update/common/api.py + alg_update/alg_toolbox/algapi.go 1:1 对齐）。

const (
	// AlgoListPath 算法分页列表
	AlgoListPath = "/alg-manager-web-v2.2-tpt/api/algorithm/page/1"
	// AlgoReleasePath 发布 / 取消发布
	AlgoReleasePath = "/alg-manager-web-v2.2-tpt/api/algorithm/release"
	// AlgoEditPath 提交算法元数据
	AlgoEditPath = "/alg-manager-web-v2.2-tpt/api/algorithm/edit/1"
	// AlgoUploadPathMinIO 上传 zip 到 MinIO
	AlgoUploadPathMinIO = "/alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio"
)

// 默认资源类型常量。
const (
	ResourceTypeCPU = 1
	ResourceTypeGPU = 2
)

// Algorithm 是 list 接口返回的单条记录（字段集与平台返回一致，按需取用）。
type Algorithm map[string]any

// ListAlgorithms 获取算法列表（单页），对应 Python list_algorithms。
func (c *Client) ListAlgorithms(ctx context.Context, page, pageSize int, extend int, sort, createTimeBegin, createTimeEnd string) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"createTime_begin": createTimeBegin,
			"createTime_end":   createTimeEnd,
		},
		"requestBase": map[string]any{
			"page": fmt.Sprintf("%d-%d", page, pageSize),
			"sort": sort,
		},
	}
	// extend 作为 query param 拼到 URL 上（doRequest 暂不直接支持 url.Values）
	path := AlgoListPath + "?extend=" + fmt.Sprintf("%d", extend)

	var raw map[string]any
	if err := c.doRequest(ctx, http.MethodPost, path, body, &raw, false); err != nil {
		return nil, err
	}
	return raw, nil
}

// GetAllAlgorithms 自动翻页获取所有算法并缓存。
func (c *Client) GetAllAlgorithms(ctx context.Context, pageSize int, sort, createTimeBegin, createTimeEnd string) ([]Algorithm, error) {
	if pageSize < 1 {
		pageSize = 100
	}
	var all []Algorithm
	page := 1
	for {
		result, err := c.ListAlgorithms(ctx, page, pageSize, 0, sort, createTimeBegin, createTimeEnd)
		if err != nil {
			return nil, err
		}
		recordsRaw, _ := result["records"].([]any)
		if len(recordsRaw) == 0 {
			break
		}
		for _, r := range recordsRaw {
			if record, ok := r.(map[string]any); ok {
				all = append(all, record)
			}
		}
		if len(recordsRaw) < pageSize {
			break
		}
		page++
	}
	c.cache.reset(all)
	return all, nil
}

// GetBySourcePath 通过 sourcePath 获取缓存的算法信息。
func (c *Client) GetBySourcePath(sourcePath string) Algorithm {
	return c.cache.sourceMap[sourcePath]
}

// GetByID 通过 id 获取缓存的算法信息。
func (c *Client) GetByID(algoID float64) Algorithm {
	return c.cache.idMap[algoID]
}

// ReleaseAlgorithm 发布或取消发布算法。
//
//   - isRelease: 0=取消发布, 1=发布
//   - resourceType: 1=CPU, 2=GPU
func (c *Client) ReleaseAlgorithm(ctx context.Context, algoID float64, isRelease, cores, resourceType, numReplicas int) error {
	body := map[string]any{
		"id":           algoID,
		"isRelease":    isRelease,
		"cores":        cores,
		"resourceType": resourceType,
		"numReplicas":  numReplicas,
	}
	var out OperationStatus
	return c.doRequest(ctx, http.MethodPost, AlgoReleasePath, body, &out, false)
}

// UploadFile 上传 zip 文件到 MinIO（POST /alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio）。
//
// built_in 默认 1，返回上传结果 dict。
func (c *Client) UploadFile(ctx context.Context, filePath string, builtIn int) (map[string]any, error) {
	u := c.baseURL + "/" + strings.TrimLeft(AlgoUploadPathMinIO, "/")

	f, err := os.Open(filePath)
	if err != nil {
		return nil, fmt.Errorf("open file: %w", err)
	}
	defer f.Close()

	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	part, err := writer.CreateFormFile("file", filepath.Base(filePath))
	if err != nil {
		return nil, fmt.Errorf("create form file: %w", err)
	}
	if _, err := io.Copy(part, f); err != nil {
		return nil, fmt.Errorf("copy file: %w", err)
	}
	if err := writer.Close(); err != nil {
		return nil, fmt.Errorf("close multipart: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u+fmt.Sprintf("?built_in=%d", builtIn), &buf)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, fmt.Errorf("decode response: %w (raw: %s)", err, truncate(string(raw), 200))
	}
	return data, nil
}

// EditAlgorithm 提交算法信息（需先上传文件），从缓存中读取算法信息并自动拼接 type 字段。
//
// sourcePath / algoID 至少传一个。
func (c *Client) EditAlgorithm(ctx context.Context, sourcePath string, algoID float64) (map[string]any, error) {
	var info Algorithm
	if sourcePath != "" {
		info = c.GetBySourcePath(sourcePath)
		if info == nil {
			return nil, fmt.Errorf("未找到算法: source_path=%s", sourcePath)
		}
	} else {
		info = c.GetByID(algoID)
		if info == nil {
			return nil, fmt.Errorf("未找到算法: algo_id=%v", algoID)
		}
	}

	algoInfo := make(Algorithm, len(info)+1)
	for k, v := range info {
		algoInfo[k] = v
	}
	categoryOne, _ := algoInfo["categoryOne"].(float64)
	if categoryOne == 0 {
		categoryOne = 1
	}
	categoryTwo, _ := algoInfo["categoryTwo"].(float64)
	algoInfo["type"] = fmt.Sprintf("%v-%v", categoryOne, categoryTwo)

	algorithmJSON, err := json.Marshal(algoInfo)
	if err != nil {
		return nil, fmt.Errorf("marshal algo: %w", err)
	}

	u := c.baseURL + "/" + strings.TrimLeft(AlgoEditPath, "/")

	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	h := make(map[string][]string)
	h["Content-Disposition"] = []string{fmt.Sprintf(`form-data; name="algorithm"; filename="blob"`)}
	h["Content-Type"] = []string{"application/json"}
	fieldWriter, err := writer.CreatePart(h)
	if err != nil {
		return nil, fmt.Errorf("create part: %w", err)
	}
	if _, err := fieldWriter.Write(algorithmJSON); err != nil {
		return nil, fmt.Errorf("write json part: %w", err)
	}
	if err := writer.Close(); err != nil {
		return nil, fmt.Errorf("close multipart: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, &buf)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	return parseEditResp(raw)
}

func parseEditResp(raw []byte) (map[string]any, error) {
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, fmt.Errorf("decode response: %w (raw: %s)", err, truncate(string(raw), 200))
	}
	code, _ := data["code"].(string)
	if code != SuccessCode {
		msg, _ := data["msg"].(string)
		return nil, &ErrAPI{Code: code, Msg: msg}
	}
	if content, ok := data["content"].(map[string]any); ok {
		return content, nil
	}
	return data, nil
}

// MatchLocalFiles 用本地文件名匹配平台 sourcePath。
//
// 匹配到的条目包含算法全部字段 + name + isExist=true；未匹配的条目只有 name + isExist=false。
func (c *Client) MatchLocalFiles(resourceDir string) ([]map[string]any, error) {
	localFiles, err := ListLocalResources(resourceDir)
	if err != nil {
		return nil, err
	}
	var result []map[string]any
	for _, f := range localFiles {
		if info, ok := c.cache.sourceMap[f]; ok {
			item := make(map[string]any, len(info)+2)
			for k, v := range info {
				item[k] = v
			}
			item["name"] = f
			item["isExist"] = true
			if cores, ok := item["cores"].(float64); ok {
				item["cores"] = int(cores)
			}
			result = append(result, item)
		} else {
			result = append(result, map[string]any{
				"name":     f,
				"isExist":  false,
			})
		}
	}
	return result, nil
}

// ListLocalResources 读取指定目录下所有 .zip 和 .py 文件名（带后缀）。
func ListLocalResources(dirPath string) ([]string, error) {
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if strings.HasSuffix(name, ".zip") || strings.HasSuffix(name, ".py") {
			files = append(files, name)
		}
	}
	return files, nil
}
