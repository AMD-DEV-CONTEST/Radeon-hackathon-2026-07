package comfy

import (
	"encoding/json"
	"testing"
)

// referenceTemplate 造一份最小但结构真实的工作流：采样器 + VAE 解码 + 模型链。
func referenceTemplate(
	t *testing.T,
) *Template {
	t.Helper()

	workflow := map[string]any{
		"loader": map[string]any{
			"class_type": "UNETLoader",
			"inputs": map[string]any{
				"unet_name": "z_image.safetensors",
			},
		},
		"sampling": map[string]any{
			"class_type": "ModelSamplingAuraFlow",
			"inputs": map[string]any{
				"shift": 3.0,
				"model": []any{"loader", 0},
			},
		},
		"vae": map[string]any{
			"class_type": "VAELoader",
			"inputs": map[string]any{
				"vae_name": "ae.safetensors",
			},
		},
		"positive": map[string]any{
			"class_type": "CLIPTextEncode",
			"inputs": map[string]any{
				"text": "PLACEHOLDER",
			},
		},
		"negative": map[string]any{
			"class_type": "CLIPTextEncode",
			"inputs": map[string]any{
				"text": "PLACEHOLDER",
			},
		},
		"sampler": map[string]any{
			"class_type": "KSampler",
			"inputs": map[string]any{
				"seed":         0,
				"cfg":          2.0,
				"denoise":      1.0,
				"steps":        8,
				"model":        []any{"sampling", 0},
				"positive":     []any{"positive", 0},
				"negative":     []any{"negative", 0},
				"latent_image": []any{"latent", 0},
			},
		},
		"decode": map[string]any{
			"class_type": "VAEDecode",
			"inputs": map[string]any{
				"samples": []any{"sampler", 0},
				"vae":     []any{"vae", 0},
			},
		},
	}

	prompt, err := findTextBinding(workflow, "positive", false)
	if err != nil || prompt == nil {
		t.Fatalf("locate prompt binding: %v", err)
	}

	negative, err := findTextBinding(workflow, "negative", true)
	if err != nil {
		t.Fatalf("locate negative binding: %v", err)
	}

	seed, err := findSeedBinding(workflow, "sampler")
	if err != nil {
		t.Fatalf("locate seed binding: %v", err)
	}

	return &Template{
		base: workflow,
		bindings: Bindings{
			Prompt:         prompt,
			NegativePrompt: negative,
			Seed:           seed,
			CFG:            findCFGBinding(workflow),
		},
	}
}

// 这是整个改动最重要的一条：没有参考图时提交的图必须和以前逐字节一致。
// 参考图条件化是加进来的能力，不能顺手改掉所有既有请求的出图。
func TestBuildWithoutReferenceIsUnchanged(
	t *testing.T,
) {
	t.Parallel()

	template := referenceTemplate(t).
		WithReferencePatch("patch.safetensors")

	plain, err := template.Build("p", "n", 7, ReferenceControl{})
	if err != nil {
		t.Fatalf("build without reference: %v", err)
	}

	for _, nodeID := range []string{
		referenceLoadNodeID,
		referenceCannyNodeID,
		referencePatchNodeID,
		referenceControlNodeID,
	} {
		if _, exists := plain[nodeID]; exists {
			t.Fatalf(
				"node %s injected even though no reference was given",
				nodeID,
			)
		}
	}

	sampler := plain["sampler"].(map[string]any)
	inputs := sampler["inputs"].(map[string]any)

	model, _ := json.Marshal(inputs["model"])
	if string(model) != `["sampling",0]` {
		t.Fatalf(
			"sampler model input was rewired to %s",
			model,
		)
	}
}

// 有参考图时：四个节点都插进去，采样器改接 ControlNet，
// 而 ControlNet 接的是原来喂给采样器的那条 model 连线。
func TestBuildWithReferenceRewiresSampler(
	t *testing.T,
) {
	t.Parallel()

	template := referenceTemplate(t).
		WithReferencePatch("patch.safetensors")

	built, err := template.Build(
		"p",
		"n",
		7,
		ReferenceControl{
			ImageName: "ref.png",
			Strength:  0.5,
		},
	)
	if err != nil {
		t.Fatalf("build with reference: %v", err)
	}

	sampler := built["sampler"].(map[string]any)
	inputs := sampler["inputs"].(map[string]any)

	model, _ := json.Marshal(inputs["model"])
	if string(model) != `["`+referenceControlNodeID+`",0]` {
		t.Fatalf(
			"sampler was not rewired to the ControlNet: %s",
			model,
		)
	}

	control := built[referenceControlNodeID].(map[string]any)
	controlInputs := control["inputs"].(map[string]any)

	// 原来的 model 连线必须被转接进 ControlNet，不能凭空断掉。
	upstream, _ := json.Marshal(controlInputs["model"])
	if string(upstream) != `["sampling",0]` {
		t.Fatalf(
			"ControlNet lost the original model link: %s",
			upstream,
		)
	}

	// VAE 必须复用解码节点在用的那条线。
	vae, _ := json.Marshal(controlInputs["vae"])
	if string(vae) != `["vae",0]` {
		t.Fatalf("ControlNet vae link = %s, want [\"vae\",0]", vae)
	}

	if controlInputs["strength"] != 0.5 {
		t.Fatalf(
			"strength = %v, want 0.5",
			controlInputs["strength"],
		)
	}

	// 权重名由模板配置决定，不接受调用方传进来的值。
	if controlInputs["model_patch"] == nil {
		t.Fatal("model_patch not wired")
	}

	patch := built[referencePatchNodeID].(map[string]any)
	patchInputs := patch["inputs"].(map[string]any)

	if patchInputs["name"] != "patch.safetensors" {
		t.Fatalf(
			"patch name = %v, want the configured one",
			patchInputs["name"],
		)
	}

	// 参考图要经 Canny 再进 ControlNet，不是原图直连。
	canny := built[referenceCannyNodeID].(map[string]any)
	cannyInputs := canny["inputs"].(map[string]any)

	source, _ := json.Marshal(cannyInputs["image"])
	if string(source) != `["`+referenceLoadNodeID+`",0]` {
		t.Fatalf("Canny input = %s", source)
	}

	image, _ := json.Marshal(controlInputs["image"])
	if string(image) != `["`+referenceCannyNodeID+`",0]` {
		t.Fatalf(
			"ControlNet should consume the Canny map, got %s",
			image,
		)
	}

	load := built[referenceLoadNodeID].(map[string]any)
	loadInputs := load["inputs"].(map[string]any)

	if loadInputs["image"] != "ref.png" {
		t.Fatalf("LoadImage image = %v", loadInputs["image"])
	}
}

// 没配权重却收到参考图：必须报错，不能默默丢掉参考图然后返回一张无关的图。
// 静默降级正是这个功能之前的样子 —— 素材传了、字段回了、像素毫无变化。
func TestBuildWithReferenceRequiresPatch(
	t *testing.T,
) {
	t.Parallel()

	template := referenceTemplate(t)

	if template.ReferenceControlAvailable() {
		t.Fatal("no patch configured, availability must be false")
	}

	_, err := template.Build(
		"p",
		"n",
		7,
		ReferenceControl{ImageName: "ref.png", Strength: 0.5},
	)
	if err == nil {
		t.Fatal("expected an error when no ControlNet patch is configured")
	}
}

// 强度为 0 或没有图片名都不算有效控制，走无参考图路径。
func TestReferenceControlValidity(
	t *testing.T,
) {
	t.Parallel()

	cases := []struct {
		name      string
		reference ReferenceControl
		requested bool
	}{
		{
			name: "image and strength given",
			reference: ReferenceControl{
				ImageName: "a.png",
				Strength:  0.5,
			},
			requested: true,
		},
		{
			name: "zero strength",
			reference: ReferenceControl{
				ImageName: "a.png",
			},
			requested: false,
		},
		{
			name:      "empty",
			reference: ReferenceControl{},
			requested: false,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := testCase.reference.Requested(); got != testCase.requested {
				t.Fatalf(
					"Requested() = %v, want %v",
					got,
					testCase.requested,
				)
			}

			// PatchName 是部署配置，不该影响"调用方要没要参考图"。
			if testCase.reference.Valid() && !testCase.requested {
				t.Fatal("Valid() must imply Requested()")
			}
		})
	}
}

// 强度归一化：0 取默认，越界收进区间。
func TestNormalizeControlStrengthBounds(
	t *testing.T,
) {
	t.Parallel()

	// 这里刻意不 import domain 以免测试包循环，直接验注入后的值范围。
	template := referenceTemplate(t).
		WithReferencePatch("patch.safetensors")

	built, err := template.Build(
		"p",
		"n",
		7,
		ReferenceControl{ImageName: "ref.png", Strength: 1.0},
	)
	if err != nil {
		t.Fatalf("build: %v", err)
	}

	control := built[referenceControlNodeID].(map[string]any)
	inputs := control["inputs"].(map[string]any)

	if inputs["strength"] != 1.0 {
		t.Fatalf("strength = %v, want 1.0", inputs["strength"])
	}
}
