package domain

import (
	"encoding/json"
	"testing"
)

// 模型偶尔把该给数组的字段写成一个字符串。以前这会让整份复审响应解码失败，
// finalize 直接 502 —— 一次花了几十秒 GPU 的复审因为方括号被整份丢掉。
func TestStringListAcceptsStringOrArray(
	t *testing.T,
) {
	t.Parallel()

	cases := []struct {
		name string
		raw  string
		want []string
	}{
		{
			name: "proper array",
			raw:  `["purple","neon","text"]`,
			want: []string{"purple", "neon", "text"},
		},
		{
			name: "comma separated string",
			raw:  `"purple, neon, text"`,
			want: []string{"purple", "neon", "text"},
		},
		{
			name: "chinese comma",
			raw:  `"紫色，霓虹，文字"`,
			want: []string{"紫色", "霓虹", "文字"},
		},
		{
			name: "semicolon and newline",
			raw:  "\"purple; neon\\ntext\"",
			want: []string{"purple", "neon", "text"},
		},
		{
			name: "single item string",
			raw:  `"purple"`,
			want: []string{"purple"},
		},
		{
			name: "empty array",
			raw:  `[]`,
			want: []string{},
		},
		{
			name: "null",
			raw:  `null`,
			want: nil,
		},
		{
			name: "empty string",
			raw:  `""`,
			want: nil,
		},
		{
			// 只有分隔符：切完什么都不剩，不能留下空字符串项。
			name: "only separators",
			raw:  `",, ,"`,
			want: nil,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var list StringList

			if err := json.Unmarshal(
				[]byte(testCase.raw),
				&list,
			); err != nil {
				t.Fatalf("unmarshal %s: %v", testCase.raw, err)
			}

			if len(list) != len(testCase.want) {
				t.Fatalf(
					"got %#v, want %#v",
					[]string(list),
					testCase.want,
				)
			}

			for index := range testCase.want {
				if list[index] != testCase.want[index] {
					t.Fatalf(
						"item %d = %q, want %q",
						index,
						list[index],
						testCase.want[index],
					)
				}
			}
		})
	}
}

// 数字之类真正不该接受的形状仍要报错，别把校验一起放弃掉。
func TestStringListRejectsOtherShapes(
	t *testing.T,
) {
	t.Parallel()

	for _, raw := range []string{`42`, `{"a":1}`, `true`} {
		var list StringList

		if err := json.Unmarshal([]byte(raw), &list); err == nil {
			t.Fatalf("expected an error for %s", raw)
		}
	}
}

// 这是线上真实炸掉的那份响应形状：nextInstruction 里两个列表都是字符串。
func TestReviewNextInstructionSurvivesStringLists(
	t *testing.T,
) {
	t.Parallel()

	raw := `{
		"promptAdditions": "sharper throne, deeper shadows",
		"negativePromptAdditions": "purple, cyan, neon",
		"composerTemplate": "editorial_top"
	}`

	var instruction ReviewNextInstruction

	if err := json.Unmarshal(
		[]byte(raw),
		&instruction,
	); err != nil {
		t.Fatalf("decode next instruction: %v", err)
	}

	if len(instruction.NegativePromptAdditions) != 3 {
		t.Fatalf(
			"negativePromptAdditions = %#v",
			[]string(instruction.NegativePromptAdditions),
		)
	}

	if len(instruction.PromptAdditions) != 2 {
		t.Fatalf(
			"promptAdditions = %#v",
			[]string(instruction.PromptAdditions),
		)
	}

	if instruction.ComposerTemplate != "editorial_top" {
		t.Fatalf(
			"composerTemplate = %q",
			instruction.ComposerTemplate,
		)
	}
}
