package domain

import (
	"encoding/json"
	"fmt"
	"strings"
)

// StringList 是一个既接受 JSON 数组又接受单个字符串的字符串列表。
//
// 复审提示词里要求这些字段是数组，模型大多数时候照做，但偶尔会回
//
//	"negativePromptAdditions": "purple, neon, text"
//
// 而不是
//
//	"negativePromptAdditions": ["purple", "neon", "text"]
//
// 之前这会让整个复审响应解码失败，finalize 直接 502 —— 一次已经花掉几十秒 GPU
// 的复审，因为一个逗号和方括号的差别被整份丢掉。模型输出的形状本来就不稳定，
// 这属于解析层该吸收的差异，而不是该冒泡成 5xx 的错误。
type StringList []string

func (list *StringList) UnmarshalJSON(
	data []byte,
) error {
	trimmed := strings.TrimSpace(string(data))

	if trimmed == "" || trimmed == "null" {
		*list = nil
		return nil
	}

	// 正常情况：JSON 数组。
	if trimmed[0] == '[' {
		var values []string
		if err := json.Unmarshal(data, &values); err != nil {
			return err
		}

		*list = values
		return nil
	}

	// 退化情况：单个字符串。按逗号和中文逗号切开，空段丢掉。
	if trimmed[0] == '"' {
		var value string
		if err := json.Unmarshal(data, &value); err != nil {
			return err
		}

		*list = splitLooseList(value)
		return nil
	}

	return fmt.Errorf(
		"expected a JSON array or string, got %s",
		trimmed,
	)
}

// splitLooseList 把模型塞进一个字符串里的列表拆开。
func splitLooseList(
	value string,
) StringList {
	fields := strings.FieldsFunc(value, func(r rune) bool {
		return r == ',' || r == '，' || r == ';' || r == '；' ||
			r == '\n'
	})

	items := make(StringList, 0, len(fields))

	for _, field := range fields {
		field = strings.TrimSpace(field)
		if field != "" {
			items = append(items, field)
		}
	}

	if len(items) == 0 {
		return nil
	}

	return items
}
