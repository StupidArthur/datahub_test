// service_test.go - PickLocalIP / mockPorts 纯函数测试。
package env

import "testing"

func TestMockPorts(t *testing.T) {
	ports := mockPorts()
	want := PortEnd - PortStart + 1
	if len(ports) != want {
		t.Fatalf("len=%d want=%d", len(ports), want)
	}
	if ports[0] != PortStart || ports[len(ports)-1] != PortEnd {
		t.Errorf("range=%d..%d want=%d..%d", ports[0], ports[len(ports)-1], PortStart, PortEnd)
	}
}

func TestPickLocalIP(t *testing.T) {
	cases := []struct {
		name string
		ips  []string
		want string
	}{
		{"空", nil, ""},
		{"10 优先(即便在后)", []string{"192.168.1.1", "172.16.0.1", "10.10.58.153"}, "10.10.58.153"},
		{"无 10 则 172", []string{"192.168.1.1", "172.16.0.1"}, "172.16.0.1"},
		{"无 10/172 取首个", []string{"192.168.1.1", "8.8.8.8"}, "192.168.1.1"},
		{"仅一个", []string{"10.0.0.1"}, "10.0.0.1"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := PickLocalIP(c.ips); got != c.want {
				t.Errorf("got %q want %q", got, c.want)
			}
		})
	}
}
