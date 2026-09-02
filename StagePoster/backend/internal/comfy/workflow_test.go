package comfy

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// 真实工作流的最小骨架：一个正向文本编码、一个负向文本编码、一个采样器。
const testWorkflow = `{
	"57:30": {
		"inputs": {"clip_name": "qwen_3_4b.safetensors"},
		"class_type": "CLIPLoader",
		"_meta": {"title": "加载CLIP"}
	},
	"57:27": {
		"inputs": {"text": "placeholder", "clip": ["57:30", 0]},
		"class_type": "CLIPTextEncode",
		"_meta": {"title": "CLIP文本编码"}
	},
	"57:34": {
		"inputs": {"text": "placeholder", "clip": ["57:30", 0]},
		"class_type": "CLIPTextEncode",
		"_meta": {"title": "CLIP文本编码 negative 负向"}
	},
	"57:3": {
		"inputs": {
			"seed": 0,
			"steps": 8,
			"cfg": 2,
			"positive": ["57:27", 0],
			"negative": ["57:34", 0]
		},
		"class_type": "KSampler",
		"_meta": {"title": "K采样器"}
	}
}`

func writeTestWorkflow(
	t *testing.T,
	body string,
) string {
	t.Helper()

	path := filepath.Join(t.TempDir(), "workflow.json")

	if err := os.WriteFile(
		path,
		[]byte(body),
		0o600,
	); err != nil {
		t.Fatalf("write workflow: %v", err)
	}

	return path
}

func buildTestWorkflow(
	t *testing.T,
	template *Template,
	negativePrompt string,
) map[string]any {
	t.Helper()

	built, err := template.Build(
		"positive text",
		negativePrompt,
		42,
		ReferenceControl{},
	)
	if err != nil {
		t.Fatalf("build workflow: %v", err)
	}

	return built
}

func nodeInput(
	t *testing.T,
	workflow map[string]any,
	nodeID string,
	key string,
) any {
	t.Helper()

	node, ok := workflow[nodeID].(map[string]any)
	if !ok {
		t.Fatalf("node %s missing", nodeID)
	}

	inputs, ok := node["inputs"].(map[string]any)
	if !ok {
		t.Fatalf("node %s has no inputs", nodeID)
	}

	return inputs[key]
}

// 负向提示词以前被算出来、存进库、在 API 里返回，但根本没提交给 ComfyUI。
// 这条钉住它真的写进了工作流。
func TestNegativePromptReachesWorkflow(
	t *testing.T,
) {
	t.Parallel()

	template, err := LoadTemplate(
		writeTestWorkflow(t, testWorkflow),
		"57:27",
		"57:34",
		"57:3",
		0,
	)
	if err != nil {
		t.Fatalf("load template: %v", err)
	}

	if !template.NegativePromptEffective() {
		t.Fatalf(
			"negative prompt reported ineffective at cfg=%v",
			template.EffectiveCFG(),
		)
	}

	built := buildTestWorkflow(
		t,
		template,
		"solid white panel, text",
	)

	if got := nodeInput(
		t,
		built,
		"57:34",
		"text",
	); got != "solid white panel, text" {
		t.Fatalf("negative text not bound: %v", got)
	}

	if got := nodeInput(
		t,
		built,
		"57:27",
		"text",
	); got != "positive text" {
		t.Fatalf("positive text not bound: %v", got)
	}

	// Build 在克隆之后直接写 Go 值，没有再过一次 JSON，所以 seed 仍是 int64。
	if got := nodeInput(t, built, "57:3", "seed"); got != int64(42) {
		t.Fatalf("seed not bound: %v", got)
	}
}

// cfg == 1 时引导项被约掉，负向分支对出图没有任何影响。绑上了也得如实报告
// 无效，否则又变成一个静默失效。
func TestNegativePromptInertAtCFGOne(
	t *testing.T,
) {
	t.Parallel()

	template, err := LoadTemplate(
		writeTestWorkflow(t, testWorkflow),
		"57:27",
		"57:34",
		"57:3",
		1,
	)
	if err != nil {
		t.Fatalf("load template: %v", err)
	}

	if template.EffectiveCFG() != 1 {
		t.Fatalf(
			"cfg override ignored: %v",
			template.EffectiveCFG(),
		)
	}

	if template.NegativePromptEffective() {
		t.Fatal(
			"cfg=1 must report negative prompts as ineffective",
		)
	}

	built := buildTestWorkflow(t, template, "unwanted text")

	if got := nodeInput(t, built, "57:3", "cfg"); got != float64(1) {
		t.Fatalf("cfg not applied to sampler: %v", got)
	}
}

// cfg 为 0 表示沿用工作流 JSON 里的值，不覆盖。
func TestCFGZeroKeepsWorkflowValue(
	t *testing.T,
) {
	t.Parallel()

	template, err := LoadTemplate(
		writeTestWorkflow(t, testWorkflow),
		"57:27",
		"57:34",
		"57:3",
		0,
	)
	if err != nil {
		t.Fatalf("load template: %v", err)
	}

	if template.EffectiveCFG() != 2 {
		t.Fatalf(
			"expected workflow cfg 2, got %v",
			template.EffectiveCFG(),
		)
	}

	built := buildTestWorkflow(t, template, "")

	if got := nodeInput(t, built, "57:3", "cfg"); got != float64(2) {
		t.Fatalf("workflow cfg mutated: %v", got)
	}
}

// 出厂工作流必须自带可用的负向链路，否则线上又回到"算了但不生效"。
func TestShippedWorkflowHasEffectiveNegativePrompt(
	t *testing.T,
) {
	t.Parallel()

	path := filepath.Join(
		"..",
		"..",
		"..",
		"workflows",
		"z_image_poster_v1.json",
	)

	raw, err := os.ReadFile(path)
	if err != nil {
		t.Skipf("shipped workflow unavailable: %v", err)
	}

	var workflow map[string]any
	if err := json.Unmarshal(raw, &workflow); err != nil {
		t.Fatalf("decode shipped workflow: %v", err)
	}

	template, err := LoadTemplate(path, "57:27", "57:34", "57:3", 0)
	if err != nil {
		t.Fatalf("load shipped workflow: %v", err)
	}

	if !template.NegativePromptEffective() {
		t.Fatalf(
			"shipped workflow cannot apply negative prompts "+
				"(cfg=%v)",
			template.EffectiveCFG(),
		)
	}

	// 采样器的 negative 必须指向文本编码节点，不能再是 ConditioningZeroOut。
	sampler, _ := workflow["57:3"].(map[string]any)
	inputs, _ := sampler["inputs"].(map[string]any)
	negative, _ := inputs["negative"].([]any)

	if len(negative) == 0 || negative[0] != "57:34" {
		t.Fatalf(
			"sampler negative input not wired to 57:34: %v",
			negative,
		)
	}
}
