package api

import (
	"net/http"
	"strconv"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// parsePage 解析列表接口共用的 limit / offset。
//
// 以前每个列表处理器各自 strconv.Atoi 一个 limit，然后 repository 再夹一次范围，
// 越界的值被静默改成默认 20 —— 调用方拿到 20 行却以为拿到了 1000 行。现在越界
// 直接 400，客户端能立刻发现自己传错了。
func parsePage(
	writer http.ResponseWriter,
	request *http.Request,
) (domain.Page, bool) {
	query := request.URL.Query()

	limit := domain.DefaultPageLimit
	offset := 0

	if raw := query.Get("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil {
			writeError(
				writer,
				http.StatusBadRequest,
				"invalid limit",
			)
			return domain.Page{}, false
		}

		if parsed < 1 || parsed > domain.MaxPageLimit {
			writeError(
				writer,
				http.StatusBadRequest,
				"limit must be between 1 and "+
					strconv.Itoa(domain.MaxPageLimit),
			)
			return domain.Page{}, false
		}

		limit = parsed
	}

	if raw := query.Get("offset"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil {
			writeError(
				writer,
				http.StatusBadRequest,
				"invalid offset",
			)
			return domain.Page{}, false
		}

		if parsed < 0 {
			writeError(
				writer,
				http.StatusBadRequest,
				"offset must not be negative",
			)
			return domain.Page{}, false
		}

		offset = parsed
	}

	return domain.NormalizePage(limit, offset), true
}
