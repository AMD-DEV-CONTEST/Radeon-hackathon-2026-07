package comfy

import (
	"errors"
	"fmt"
)

// ReferenceControl 描述一次带参考图的生成。
//
// 之前参考图对出图完全没有影响：工作流只绑 prompt / negative / seed，参考图
// 只进了需求理解那次 VLM 调用，所以 actuallyUsed 永远是 false —— 那是诚实的。
// 现在参考图经 Canny 边缘图接进 Z-Image 的 ControlNet，真的参与采样。
type ReferenceControl struct {
	// ImageName 是参考图在 ComfyUI input 目录下的文件名，来自 /upload/image。
	ImageName string

	// Strength 是 ControlNet 强度。0 表示不施加控制。
	Strength float64

	// PatchName 是 models/model_patches 下的权重文件名。
	PatchName string
}

// 注入节点用带冒号前缀的 ID，避免和模板里的 "57:3" 这类 ID 撞。
const (
	referenceLoadNodeID    = "ref:load"
	referenceCannyNodeID   = "ref:canny"
	referencePatchNodeID   = "ref:patch"
	referenceControlNodeID = "ref:control"
)

// Canny 阈值。低阈值放宽一点能让参考图里较弱的边也进入控制信号，
// 对"照这个版式来"的用法更有用。
const (
	referenceCannyLowThreshold  = 0.4
	referenceCannyHighThreshold = 0.8
)

// Requested 报告调用方是否要求了参考图控制。
//
// 只看调用方能提供的两项。PatchName 是部署配置，由 Template 在 Build 时填入，
// 所以不能进这个判断 —— 否则永远为 false，参考图会被静默丢掉。
func (r ReferenceControl) Requested() bool {
	return r.ImageName != "" && r.Strength > 0
}

// Valid 报告这份控制是否已经补齐到可以注入工作流。
func (r ReferenceControl) Valid() bool {
	return r.Requested() && r.PatchName != ""
}

// applyReferenceControl 把 LoadImage -> Canny -> ZImageFunControlnet 插进工作流，
// 并把采样器的 model 输入改接到 ControlNet 的输出。
//
// 不改模板文件，而是在每次 Build 克隆出来的图上注入 —— 没有参考图的请求提交的
// 图和以前逐字节一致，不会因为这个功能回归。
func applyReferenceControl(
	workflow map[string]any,
	samplerNodeID string,
	reference ReferenceControl,
) error {
	sampler, ok := workflow[samplerNodeID].(map[string]any)
	if !ok {
		return fmt.Errorf(
			"reference control: sampler node %s not found",
			samplerNodeID,
		)
	}

	inputs, ok := sampler["inputs"].(map[string]any)
	if !ok {
		return fmt.Errorf(
			"reference control: sampler node %s has no inputs",
			samplerNodeID,
		)
	}

	modelSource, ok := inputs["model"]
	if !ok {
		return fmt.Errorf(
			"reference control: sampler node %s has no model input",
			samplerNodeID,
		)
	}

	vaeSource, err := findVAESource(workflow)
	if err != nil {
		return err
	}

	workflow[referenceLoadNodeID] = map[string]any{
		"class_type": "LoadImage",
		"inputs": map[string]any{
			"image": reference.ImageName,
		},
	}

	workflow[referenceCannyNodeID] = map[string]any{
		"class_type": "Canny",
		"inputs": map[string]any{
			"image":          []any{referenceLoadNodeID, 0},
			"low_threshold":  referenceCannyLowThreshold,
			"high_threshold": referenceCannyHighThreshold,
		},
	}

	workflow[referencePatchNodeID] = map[string]any{
		"class_type": "ModelPatchLoader",
		"inputs": map[string]any{
			"name": reference.PatchName,
		},
	}

	workflow[referenceControlNodeID] = map[string]any{
		"class_type": "ZImageFunControlnet",
		"inputs": map[string]any{
			// 原来喂给采样器的 model 连线原样转接进 ControlNet。
			"model":       modelSource,
			"model_patch": []any{referencePatchNodeID, 0},
			"vae":         vaeSource,
			"strength":    reference.Strength,
			"image":       []any{referenceCannyNodeID, 0},
		},
	}

	inputs["model"] = []any{referenceControlNodeID, 0}

	return nil
}

// findVAESource 复用 VAEDecode 已经在用的那条 vae 连线。
//
// 直接找 VAELoader 也行，但工作流也可能从 checkpoint loader 取 VAE。
// 抄解码节点的连线，拿到的一定是这条流水线实际使用的 VAE。
func findVAESource(
	workflow map[string]any,
) (any, error) {
	for _, nodeID := range sortedNodeIDs(workflow) {
		node, ok := workflow[nodeID].(map[string]any)
		if !ok {
			continue
		}

		if node["class_type"] != "VAEDecode" {
			continue
		}

		inputs, ok := node["inputs"].(map[string]any)
		if !ok {
			continue
		}

		if source, exists := inputs["vae"]; exists {
			return source, nil
		}
	}

	return nil, errors.New(
		"reference control: cannot find a VAE source " +
			"(no VAEDecode node with a vae input)",
	)
}
