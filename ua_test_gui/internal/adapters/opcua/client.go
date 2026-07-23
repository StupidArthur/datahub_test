// client.go - OPC UA 源端 client(gopcua 封装),实现 verify.SourceClient。
//
// 绕过 TPT,用于:验证 mock 节点存在/可读/可写、写源端值查 TPT 传播、就绪探针(Discover)。
// 对齐 python ua_test_harness/opcua/client.py(asyncua)。
// 依赖方向:opcua -> verify(实现 SourceClient 接口);不反向依赖 verify。
package opcua

import (
	"context"
	"fmt"

	"github.com/gopcua/opcua"
	"github.com/gopcua/opcua/ua"
)

// UaSourceClient OPC UA 源端 client(实现 verify.SourceClient)。
type UaSourceClient struct {
	endpoint string
	ns       int
	client   *opcua.Client
}

// UaNodeInfo Discover 返回的单节点信息。
type UaNodeInfo struct {
	BrowseName string `json:"browseName"`
	NodeID     string `json:"nodeId"`
	Value      any    `json:"value"`
}

// NewUaSourceClient 创建(未连接)。namespaceIndex 默认 1。
func NewUaSourceClient(endpoint string, namespaceIndex int) *UaSourceClient {
	if namespaceIndex <= 0 {
		namespaceIndex = 1
	}
	return &UaSourceClient{endpoint: endpoint, ns: namespaceIndex}
}

func (c *UaSourceClient) nodeID(name string) *ua.NodeID {
	return ua.NewStringNodeID(uint16(c.ns), name)
}

// Connect 建立连接(无安全模式,ua_mocker 不加密)。
func (c *UaSourceClient) Connect(ctx context.Context) error {
	if c.client != nil {
		return nil
	}
	cl, err := opcua.NewClient(c.endpoint, opcua.SecurityMode(ua.MessageSecurityModeNone))
	if err != nil {
		return err
	}
	if err := cl.Connect(ctx); err != nil {
		return err
	}
	c.client = cl
	return nil
}

// Close 关闭连接。
func (c *UaSourceClient) Close(ctx context.Context) error {
	if c.client == nil {
		return nil
	}
	err := c.client.Close(ctx)
	c.client = nil
	return err
}

func (c *UaSourceClient) ensureConnected(ctx context.Context) error {
	if c.client != nil {
		return nil
	}
	return c.Connect(ctx)
}

// Read 读单个节点值。
func (c *UaSourceClient) Read(ctx context.Context, name string) (any, error) {
	if err := c.ensureConnected(ctx); err != nil {
		return nil, err
	}
	req := &ua.ReadRequest{
		NodesToRead: []*ua.ReadValueID{
			{NodeID: c.nodeID(name), AttributeID: ua.AttributeIDValue},
		},
	}
	resp, err := c.client.Read(ctx, req)
	if err != nil {
		return nil, err
	}
	if len(resp.Results) == 0 {
		return nil, fmt.Errorf("读 %s 无结果", name)
	}
	dv := resp.Results[0]
	if dv.Status != ua.StatusOK {
		return nil, fmt.Errorf("读 %s 状态 %s", name, dv.Status)
	}
	if dv.Value == nil {
		return nil, nil
	}
	return dv.Value.Value(), nil
}

// Write 写单个节点值。
func (c *UaSourceClient) Write(ctx context.Context, name string, value any) error {
	if err := c.ensureConnected(ctx); err != nil {
		return err
	}
	v, err := ua.NewVariant(value)
	if err != nil {
		return fmt.Errorf("值转 variant 失败: %w", err)
	}
	// DataValue.EncodingMask 必须显式置位:gopcua Encode 仅按 mask 决定是否写 Value,
	// 不调 UpdateMask 则 mask=0,Value 不被编码,服务端收到 VariantType=Null -> BadTypeMismatch。
	dv := &ua.DataValue{Value: v}
	dv.UpdateMask()
	req := &ua.WriteRequest{
		NodesToWrite: []*ua.WriteValue{
			{NodeID: c.nodeID(name), AttributeID: ua.AttributeIDValue, Value: dv},
		},
	}
	resp, err := c.client.Write(ctx, req)
	if err != nil {
		return err
	}
	if len(resp.Results) == 0 || resp.Results[0] != ua.StatusOK {
		return fmt.Errorf("写 %s 失败", name)
	}
	return nil
}

// ReadMany 批量读节点值,返回 {name: value 或 "<err: ...>"}。
func (c *UaSourceClient) ReadMany(ctx context.Context, names []string) (map[string]any, error) {
	if err := c.ensureConnected(ctx); err != nil {
		return nil, err
	}
	nodes := make([]*ua.ReadValueID, len(names))
	for i, n := range names {
		nodes[i] = &ua.ReadValueID{NodeID: c.nodeID(n), AttributeID: ua.AttributeIDValue}
	}
	req := &ua.ReadRequest{NodesToRead: nodes}
	resp, err := c.client.Read(ctx, req)
	if err != nil {
		return nil, err
	}
	out := make(map[string]any, len(names))
	for i, n := range names {
		if i >= len(resp.Results) {
			out[n] = "<err: 无结果>"
			continue
		}
		dv := resp.Results[i]
		if dv.Status != ua.StatusOK {
			out[n] = fmt.Sprintf("<err: %s>", dv.Status)
			continue
		}
		if dv.Value == nil {
			out[n] = nil
			continue
		}
		out[n] = dv.Value.Value()
	}
	return out, nil
}

// Discover 列出 Objects 文件夹下本 namespace 的节点。
// 用于就绪探针(pyworker):端口监听 ≠ UA server ready,Discover 成功且节点数吻合才真就绪。
func (c *UaSourceClient) Discover(ctx context.Context) ([]UaNodeInfo, error) {
	if err := c.ensureConnected(ctx); err != nil {
		return nil, err
	}
	req := &ua.BrowseRequest{
		NodesToBrowse: []*ua.BrowseDescription{{
			NodeID:          ua.NewNumericNodeID(0, 85), // ObjectsFolder
			BrowseDirection: ua.BrowseDirectionForward,
			ReferenceTypeID: ua.NewTwoByteNodeID(0), // null = 所有引用类型
			IncludeSubtypes: true,
			NodeClassMask:   0xFFFFFFFF,
			ResultMask:      0xFFFFFFFF,
		}},
	}
	resp, err := c.client.Browse(ctx, req)
	if err != nil {
		return nil, err
	}
	var infos []UaNodeInfo
	if len(resp.Results) == 0 {
		return infos, nil
	}
	for _, ref := range resp.Results[0].References {
		if ref.BrowseName.NamespaceIndex != uint16(c.ns) {
			continue
		}
		ni := UaNodeInfo{BrowseName: ref.BrowseName.Name}
		if ref.NodeID != nil {
			ni.NodeID = ref.NodeID.String()
		}
		infos = append(infos, ni)
	}
	return infos, nil
}
