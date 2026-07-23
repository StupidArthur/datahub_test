// Package main 演示 tptapi 的 TPT admin 用户管理用法。
//
// 运行：go run ./examples/users
// 需要环境变量：TPT_BASE_URL / TPT_USER / TPT_PASSWORD / TPT_TENANT_ID
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/yzc/tpt_api"
)

func main() {
	baseURL := envOr("TPT_BASE_URL", "https://supcontpt.supcon.com")
	username := envOr("TPT_USER", "admin")
	password := os.Getenv("TPT_PASSWORD")
	tenantID := os.Getenv("TPT_TENANT_ID")

	c := tptapi.NewClient(baseURL)
	ctx := context.Background()

	if err := c.Login(ctx, username, password, tenantID); err != nil {
		log.Fatalf("登录失败: %v", err)
	}
	fmt.Println("登录成功, token 前 8 位:", c.Token()[:8])

	// 1) 分页列用户
	resp, err := c.ListUsers(ctx, 1, 10, "", "", "-createTime")
	if err != nil {
		log.Fatalf("列用户失败: %v", err)
	}
	fmt.Printf("共 %d 条，本页 %d 条：\n", resp.Total, len(resp.Records))
	for _, u := range resp.Records {
		fmt.Printf("  id=%d username=%s nickName=%s email=%s\n", u.ID, u.Username, u.NickName, u.Email)
	}

	// 2) 关键词搜索（nickname/username/phone/email 跨字段模糊）
	keyword := "test"
	resp, err = c.ListUsers(ctx, 1, 10, "", keyword, "-createTime")
	if err != nil {
		log.Fatalf("搜索失败: %v", err)
	}
	fmt.Printf("含 %q 的用户共 %d 条\n", keyword, resp.Total)

	// 3) 创建 + 重置密码（示例：用户名 test_001）
	draft := tptapi.UserDraft{
		Username: "test_001",
		Password: "Init@2026",
		NickName: "测试用户001",
		Email:    "test_001@example.com",
	}
	if _, err := c.CreateUser(ctx, draft); err != nil {
		log.Fatalf("创建用户失败: %v", err)
	}
	fmt.Println("用户创建成功")

	// 4) 反查 ID + 重置密码
	all, err := c.GetAllUsers(ctx, "", "-createTime", 200)
	if err != nil {
		log.Fatalf("GetAllUsers 失败: %v", err)
	}
	for _, u := range all {
		if u.Username == "test_001" {
			if _, err := c.ResetPassword(ctx, u.ID, "NewPwd@2026"); err != nil {
				log.Fatalf("重置密码失败: %v", err)
			}
			fmt.Printf("用户 %s (id=%d) 密码已重置\n", u.Username, u.ID)
		}
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
