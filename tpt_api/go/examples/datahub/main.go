// Package main 演示 tptapi 的 ibd-data-hub tag + 历史值用法。
//
// 运行：go run ./examples/datahub
// 需要环境变量：DATAHUB_BASE_URL / DATAHUB_USER / DATAHUB_PASSWORD
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/yzc/tpt_api"
)

func main() {
	baseURL := envOr("DATAHUB_BASE_URL", "http://10.10.58.179:31501")
	c := tptapi.NewClient(baseURL)
	ctx := context.Background()

	if err := c.Login(ctx, os.Getenv("DATAHUB_USER"), os.Getenv("DATAHUB_PASSWORD"), ""); err != nil {
		log.Fatalf("登录失败: %v", err)
	}
	fmt.Println("登录成功")

	// 1) 注册位号
	dsID := 2
	if _, err := c.AddTag(ctx, "demo.t_double", tptapi.DataTypes["DOUBLE"], 1, dsID,
		"0", "℃", false, 10, true, "演示位号", true); err != nil {
		log.Printf("[跳过] AddTag: %v（可能位号已存在）\n", err)
	} else {
		fmt.Println("位号注册成功")
	}

	// 2) 全量拉取（含所有 tagType，避免漏掉）
	all, err := c.GetAllTagsAllTypes(ctx, 2000, nil)
	if err != nil {
		log.Fatalf("GetAllTagsAllTypes 失败: %v", err)
	}
	fmt.Printf("全量位号 %d 个\n", len(all))

	// 3) 按名查
	if t := c.GetTagByName("demo.t_double"); t != nil {
		fmt.Printf("缓存命中: %v\n", t["tagName"])
	}

	// 4) 历史值导入（异步）—— 准备一个示例 xlsx
	xlsxPath := "examples/datahub/sample.xlsx"
	if _, err := os.Stat(xlsxPath); err == nil {
		var dsIDPtr *int
		v := 2
		dsIDPtr = &v
		resp, err := c.ImportTagValueHistory(ctx, xlsxPath, dsIDPtr, "", "", "", nil)
		if err != nil {
			log.Fatalf("导入失败: %v", err)
		}
		fmt.Printf("导入响应: status=%d code=%v isSuccess=%v\n", resp.StatusCode, resp.Code, resp.IsSuccess)
	} else {
		fmt.Printf("[跳过] %s 不存在，跳过导入演示\n", xlsxPath)
	}

	// 5) 历史值查询（验证）
	hist, err := c.GetAllHistory(ctx, []string{"demo.t_double"}, "2025-01-01 00:00:00", "2099-12-31 23:59:59",
		true, false, 2000)
	if err != nil {
		log.Fatalf("GetAllHistory 失败: %v", err)
	}
	fmt.Printf("demo.t_double 共 %d 个数据点\n", len(hist["demo.t_double"]))
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
