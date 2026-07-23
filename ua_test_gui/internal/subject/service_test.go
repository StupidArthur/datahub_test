// service_test.go - ParseSubjectURL 纯函数测试:协议截断 / path 丢弃 / 租户解析 / 错误场景。
package subject

import "testing"

func TestParseSubjectURL(t *testing.T) {
	cases := []struct {
		name    string
		raw     string
		wantErr bool
		want    SubjectUrl
	}{
		{"http+port+path截断", "http://10.10.58.153:31501/tpt-admin/", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://10.10.58.153:31501", TenantID: ""}},
		{"https+path截断", "https://host:9443/ibd-data-hub-web-v2.2/api", false,
			SubjectUrl{Protocol: "https", BaseURL: "https://host:9443", TenantID: ""}},
		{"query tenantId 优先", "http://h:80?tenantId=42", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h:80", TenantID: "42"}},
		{"query tenant_id", "http://h:80?tenant_id=43", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h:80", TenantID: "43"}},
		{"query tenant", "http://h?tenant=44", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h", TenantID: "44"}},
		{"path /tenant/{id}", "http://h/tenant/99/x", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h", TenantID: "99"}},
		{"单租户无 tenant", "http://h:80", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h:80", TenantID: ""}},
		{"tenantId 优先于 path", "http://h/tenant/99?tenantId=1", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h", TenantID: "1"}},
		{"缺协议", "10.10.58.153:31501", true, SubjectUrl{}},
		{"非 http 协议", "ftp://h/x", true, SubjectUrl{}},
		{"无 host", "http://", true, SubjectUrl{}},
		{"前后空格 trim", "  http://h:80  ", false,
			SubjectUrl{Protocol: "http", BaseURL: "http://h:80", TenantID: ""}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := ParseSubjectURL(c.raw)
			if (err != nil) != c.wantErr {
				t.Fatalf("err=%v wantErr=%v", err, c.wantErr)
			}
			if c.wantErr {
				return
			}
			if got.Protocol != c.want.Protocol || got.BaseURL != c.want.BaseURL || got.TenantID != c.want.TenantID {
				t.Errorf("got {proto=%s base=%s tenant=%s} want %+v", got.Protocol, got.BaseURL, got.TenantID, c.want)
			}
		})
	}
}
