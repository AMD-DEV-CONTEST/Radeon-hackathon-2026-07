package domain

// 分页此前根本不存在：列表接口只认 limit，repository 里也只有 LIMIT，没有
// OFFSET，也没有任何 COUNT(*)。客户端拿到的 count 是当前页的行数，没办法知道
// 后面还有没有数据，翻页也无从下手。
const (
	DefaultPageLimit = 20
	MaxPageLimit     = 100
)

// Page 是归一化之后的分页窗口。构造只走 NormalizePage，避免每个 repository
// 各自重复夹取逻辑（之前 API 层和 repository 层各夹一次，超范围的 limit 被
// 静默改成默认值，调用方完全看不出被截断了）。
type Page struct {
	Limit  int `json:"limit"`
	Offset int `json:"offset"`
}

// NormalizePage 夹取分页参数。limit 超出范围取默认值，offset 为负取 0。
func NormalizePage(
	limit int,
	offset int,
) Page {
	if limit <= 0 || limit > MaxPageLimit {
		limit = DefaultPageLimit
	}

	if offset < 0 {
		offset = 0
	}

	return Page{
		Limit:  limit,
		Offset: offset,
	}
}

// ListMeta 是所有列表信封共用的分页字段。
//
// count 保留原语义（当前页行数），沿用已有客户端的字段名；total 是新加的表内
// 总行数。CLAUDE.md 曾把信封写成 items + total，而代码返回的是 count —— 现在
// 两个字段都在，文档也已改成如实描述。
type ListMeta struct {
	Count  int `json:"count"`
	Total  int `json:"total"`
	Limit  int `json:"limit"`
	Offset int `json:"offset"`
}

// NewListMeta 由页窗口和实际返回的行数构造元信息。
func NewListMeta(
	page Page,
	count int,
	total int,
) ListMeta {
	return ListMeta{
		Count:  count,
		Total:  total,
		Limit:  page.Limit,
		Offset: page.Offset,
	}
}

// HasMore 表示 offset+count 之后仍有行，方便客户端决定是否继续翻页。
func (meta ListMeta) HasMore() bool {
	return meta.Offset+meta.Count < meta.Total
}
