// factory.go - OPC UA 源端 client 工厂,实现 verify.SourceClientFactory。
//
// verify.Service 经此创建 SourceClient,不直接依赖 opcua 实现(依赖方向:opcua -> verify)。
package opcua

import "ua_test_gui/internal/verify"

// Factory 实现 verify.SourceClientFactory。
type Factory struct{}

// NewSourceClient 创建未连接的 OPC UA 源端 client。
func (Factory) NewSourceClient(endpoint string, namespaceIndex int) verify.SourceClient {
	return NewUaSourceClient(endpoint, namespaceIndex)
}
