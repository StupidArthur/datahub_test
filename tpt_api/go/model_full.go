// model.go - 被测对象(datahub/TPT)数据模型 + 端点/枚举常量。
//
// TptClient 是已登录的 TPT 后台 HTTP 客户端(对齐 AlgAPI);字段不导出,仅经方法访问。
// 端点契约见 datahub.go。
package tptapi

import (
	"encoding/json"
	"net/http"
	"time"
)

// 登录端点 + 业务成功码 + 账号类型(对齐 tpt_api/errors.py)
const (
	loginPath        = "/tpt-admin/system-manager/umsAdmin/login"
	successCode      = "00000"
	loginAccountType = "0"
)

// datahub 端点常量(对齐 datahub.py 顶部)
const (
	dataHubBase                  = "/ibd-data-hub-web-v2.2/api"
	epTagAdd                     = dataHubBase + "/tag-info/add"
	epTagUpdate                  = dataHubBase + "/tag-info/update"
	epTagBatchUpdate             = dataHubBase + "/tag-info/batchUpdate"
	epTagPage                    = dataHubBase + "/tag-info/page"
	epTagBatchDeleteLogic        = dataHubBase + "/tag-info/batchDeleteLogic"
	epTagBatchDelete             = dataHubBase + "/tag-info/batchDelete"
	epTagExport                  = dataHubBase + "/tag-info/export"
	epTagImportStream            = dataHubBase + "/tag-info/importTagInfoStream"
	epTagGetNotUsed              = dataHubBase + "/tag-info/getNotUsedBaseTagInfoContinue"
	epTagBatchAdd                = dataHubBase + "/tag-info/batchAdd"
	epTagGroupGet                = dataHubBase + "/tag-group/get"
	epTagGroupAdd                = dataHubBase + "/tag-group/add"
	epTagGroupUpdate             = dataHubBase + "/tag-group/update"
	epTagGroupBatchDelete        = dataHubBase + "/tag-group/batchDelete"
	epTagGroupTree               = dataHubBase + "/tag-group/groupTree"
	epTagGroupBatchAddRelation   = dataHubBase + "/tag-group/batchAddRelation"
	epTagGroupBatchDelRelation   = dataHubBase + "/tag-group/batchDelRelation"
	epTagGroupQueryWithQuality   = dataHubBase + "/tag-group/queryWithQuality"
	epDsInfoPage                 = dataHubBase + "/ds-info/page"
	epDsInfoAdd                  = dataHubBase + "/ds-info/add"
	epDsInfoChangeState          = dataHubBase + "/ds-info/changeState"
	epDsInfoBatchDelete          = dataHubBase + "/ds-info/batchDelete"
	epDsInfoTest                 = dataHubBase + "/ds-info/test"
	epGetRTValue                 = dataHubBase + "/tag-value/getRTValue"
	epWriteTagValues             = dataHubBase + "/tag-value/writeTagValues"
	epGetHistoryValue            = dataHubBase + "/tag-value/getHistoryValue"
	epGetHistoryValueFromDB      = dataHubBase + "/tag-value/getHistoryValueFromDB"
	epCollectTagValue            = dataHubBase + "/tag-value/collectTagValue"
	epImportTagValue             = dataHubBase + "/tag-value/importTagValue"
	epImportTagValueHistory      = dataHubBase + "/tag-value/importTagValueHistory"
	epImportCSVTagValueHistory   = dataHubBase + "/tag-value/importCSVTagValueHistory"
)

// ds-info/test testType 枚举
const (
	DsTestEnumerate = 1 // 枚举位号(browse UA server)
	DsTestReadRT    = 2 // 位号实时值(读源端)
	DsTestReadRTDB  = 3 // 位号实时值(读库)
	DsTestHistory   = 4 // 历史值(需 beginTime/endTime)
	DsTestWrite     = 5 // 写值(需 tagValue)
)

// 特殊分组 ID(对齐 datahub.py 注释:1=回收站,2=收藏)
const (
	GroupRoot      = "0"
	GroupRecycle   = "1"
	GroupFavorites = "2"
)

// 平台枚举常量(对齐 tpt_api/types.py)
const (
	DataTypeBoolean = 1
	DataTypeSByte   = 2
	DataTypeByte    = 3
	DataTypeInt16   = 4
	DataTypeUInt16  = 5
	DataTypeInt32   = 6
	DataTypeUInt32  = 7
	DataTypeInt64   = 8
	DataTypeUInt64  = 9
	DataTypeFloat   = 10
	DataTypeDouble  = 11
	DataTypeString  = 12
	DataTypeDateTime = 13

	TagTypeOnce = 1 // 一次位号
	TagTypeVirt = 4 // 虚位号

	// 平台接受字符串形式(对齐 datahub.add_ds_info 注释)
	dsTypeRealTimeDB     = "1"
	dsSubTypeOpcUaServer = "4"
)

// DataTypeNames 数据类型码 -> 名称(对齐 datahub.add_tag 注释)
var DataTypeNames = map[int]string{
	1: "BOOLEAN", 2: "S_BYTE", 3: "BYTE", 4: "SHORT", 5: "U_SHORT",
	6: "INT", 7: "U_INT", 8: "LONG", 9: "U_LONG",
	10: "FLOAT", 11: "DOUBLE", 12: "STRING", 13: "DATE_TIME",
}

// SubjectUrl 截断后的被测对象 URL。
type SubjectUrl struct {
	Raw      string `json:"raw"`
	Protocol string `json:"protocol"` // http / https
	BaseURL  string `json:"baseUrl"`  // 协议://host:port
	TenantID string `json:"tenantId"` // 可空(单租户)
}

// TptClient 已登录的 TPT 后台 HTTP 客户端(对齐 AlgAPI)。
// token + cookie 在每次请求带上;datahub 端点方法见 datahub.go。
type TptClient struct {
	baseURL  string
	token    string
	tokenExp time.Time
	https    bool
	tenantID string
	http     *http.Client
}

// Expired 报告 token 是否已过期或即将过期(预留 5 分钟缓冲)。
func (c *TptClient) Expired() bool {
	if c == nil || c.token == "" {
		return true
	}
	if c.tokenExp.IsZero() {
		return false
	}
	return time.Until(c.tokenExp) < 5*time.Minute
}

// TptAPIError 平台业务错误(非 00000)。
type TptAPIError struct {
	Code string
	Msg  string
}

func (e *TptAPIError) Error() string { return "[" + e.Code + "] " + e.Msg }

// RtValuePoint 位号实时值点。TagValue 用 RawMessage 保留原值(类型随 dataType)。
type RtValuePoint struct {
	TagName   string          `json:"tagName"`
	TagValue  json.RawMessage `json:"tagValue"`
	TagTime   string          `json:"tagTime"`
	AppTime   string          `json:"appTime"`
	Quality   int             `json:"quality"`
	DataType  int             `json:"dataType"`
	DsID      int             `json:"dsId"`
	IsSuccess bool            `json:"isSuccess"`
	Message   string          `json:"message"`
}

// DsInfo 数据源记录(对齐 types.DsInfo,只保留必要字段)。
type DsInfo struct {
	ID        int    `json:"id"`
	Name      string `json:"name"`
	DsName    string `json:"dsName"`
	DsType    int    `json:"dsType"`
	DsSubType int    `json:"dsSubType"`
	DsTarUrl  string `json:"dsTarUrl"`
	DsStatus  int    `json:"dsStatus"`
	Alive     bool   `json:"alive"`
}

// TagRecord 位号记录。
type TagRecord struct {
	ID          int    `json:"id"`
	TagName     string `json:"tagName"`
	TagBaseName string `json:"tagBaseName"`
	DataType    int    `json:"dataType"`
	DsID        int    `json:"dsId"`
}

// AddTagParams AddTag 入参。零值字段在 AddTag 内补默认(对齐 datahub.add_tag 默认)。
// 限值字段(0 表示不发送):仅当值 > 0 时才加入请求 body。
type AddTagParams struct {
	TagName         string
	DataType        int
	TagType         int
	DsID            int
	GroupID         string
	Unit            string
	OnlyRead        bool
	Frequency       int
	TagBaseName     string // 默认 = TagName;绑 OPC UA 数据源约定 "1_{node}"
	TagDesc         string // 默认 = "{TagName} 描述"
	HiEU            *float64 // 量程上限(可选)
	LoEU            *float64 // 量程下限(可选)
	LimitUp         *float64 // 高限
	LimitUpUp       *float64 // 高高限
	LimitUpUpUp     *float64 // 高高高限
	LimitDown       *float64 // 低限
	LimitDownDown   *float64 // 低低限
	LimitDownDownDown *float64 // 低低低限
	// NeedPush/IsVector 固定 true(对齐 python 默认),不暴露
}

// WriteTagValuesResult 平台 writeTagValues 响应。
type WriteTagValuesResult struct {
	TagNames []string          `json:"tagNames"` // 成功回写的位号名
	FailMsg  map[string]string `json:"failMsg"`  // 失败位号及原因
}
