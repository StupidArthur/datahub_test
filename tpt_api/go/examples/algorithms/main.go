// Package main 演示 tptapi 的 alg-manager 算法管理用法。
//
// 运行：go run ./examples/algorithms
// 需要环境变量：ALG_BASE_URL / ALG_USER / ALG_PASSWORD
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/yzc/tpt_api"
)

func main() {
	baseURL := envOr("ALG_BASE_URL", "http://10.16.11.1:31501")
	c := tptapi.NewClient(baseURL)
	ctx := context.Background()

	if err := c.Login(ctx, os.Getenv("ALG_USER"), os.Getenv("ALG_PASSWORD"), ""); err != nil {
		log.Fatalf("登录失败: %v", err)
	}
	fmt.Println("登录成功")

	// 1) 拉全量算法
	all, err := c.GetAllAlgorithms(ctx, 100, "-createTime", "", "")
	if err != nil {
		log.Fatalf("GetAllAlgorithms 失败: %v", err)
	}
	fmt.Printf("共 %d 个算法：\n", len(all))
	for _, a := range all {
		fmt.Printf("  id=%v sourcePath=%s name=%v\n", a["id"], a["sourcePath"], a["name"])
	}

	// 2) 按 sourcePath 查
	if info := c.GetBySourcePath("spc_pid_identification_analysis.py"); info != nil {
		fmt.Printf("缓存命中: %v (id=%v)\n", info["sourcePath"], info["id"])
	}

	// 3) 上传 + 编辑（如果本地有 zip）
	zipPath := "resource/spc_pid_identification_analysis.zip"
	if _, err := os.Stat(zipPath); err == nil {
		up, err := c.UploadFile(ctx, zipPath, 1)
		if err != nil {
			log.Fatalf("上传失败: %v", err)
		}
		fmt.Printf("上传响应: %v\n", up)
		if _, err := c.EditAlgorithm(ctx, "spc_pid_identification_analysis.py", 0); err != nil {
			log.Fatalf("EditAlgorithm 失败: %v", err)
		}
		fmt.Println("EditAlgorithm 成功")
	} else {
		fmt.Printf("[跳过] %s 不存在，跳过 UploadFile/EditAlgorithm\n", zipPath)
	}

	// 4) 匹配本地 resource/ 目录
	matched, err := c.MatchLocalFiles("resource")
	if err != nil {
		log.Fatalf("MatchLocalFiles 失败: %v", err)
	}
	existCount, missCount := 0, 0
	for _, m := range matched {
		if m["isExist"].(bool) {
			existCount++
		} else {
			missCount++
		}
	}
	fmt.Printf("本地资源匹配: %d 个已存在，%d 个未在平台\n", existCount, missCount)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
