package service

import (
	"context"
	"errors"
	"fmt"
	"log"
	"path/filepath"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/comfy"
	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// ErrReferenceControlUnavailable 表示请求带了参考图，但这套部署没装 ControlNet
// 权重。宁可明确报错，也不要默默丢掉参考图然后返回一张跟它无关的图 —— 那正是
// 这个功能以前的样子。
var ErrReferenceControlUnavailable = errors.New(
	"reference image conditioning is not available on this deployment",
)

// resolveReferenceControl 把请求里的参考图素材变成可提交的 ControlNet 控制。
//
// 返回零值表示这次请求不带参考图，工作流保持原样。
func (s *PosterService) resolveReferenceControl(
	ctx context.Context,
	request domain.GenerateRequest,
) (comfy.ReferenceControl, error) {
	assetID := strings.TrimSpace(request.ReferenceAssetID)
	if assetID == "" {
		return comfy.ReferenceControl{}, nil
	}

	if !s.template.ReferenceControlAvailable() {
		return comfy.ReferenceControl{},
			ErrReferenceControlUnavailable
	}

	asset, err := s.repository.GetAsset(ctx, assetID)
	if err != nil {
		return comfy.ReferenceControl{}, fmt.Errorf(
			"resolve reference asset: %w",
			err,
		)
	}

	if strings.TrimSpace(asset.StoragePath) == "" {
		return comfy.ReferenceControl{}, fmt.Errorf(
			"reference asset %s has no stored file",
			assetID,
		)
	}

	// 名字带上 asset ID，这样 ComfyUI 的 input 目录里一张素材始终对应一个文件，
	// overwrite=true 就够了，不会越用越多。
	targetName := "stageposter-ref-" + asset.ID +
		filepath.Ext(asset.Filename)

	uploaded, err := s.client.UploadImage(
		ctx,
		asset.StoragePath,
		targetName,
	)
	if err != nil {
		return comfy.ReferenceControl{}, err
	}

	return comfy.ReferenceControl{
		ImageName: uploaded,
		Strength: domain.NormalizeControlStrength(
			request.ControlStrength,
		),
	}, nil
}

// recordReferenceUsage 落一条使用证据：这张参考图真的进了采样。
//
// 和 logo_overlay 一样，证据只在真的用上之后才写。落库失败不该毁掉一次已经
// 提交成功的生成，所以只记日志。
func (s *PosterService) recordReferenceUsage(
	ctx context.Context,
	assetID string,
	strength float64,
) {
	if strings.TrimSpace(assetID) == "" {
		return
	}

	if err := s.repository.MarkAssetUsedAcrossSessions(
		ctx,
		[]string{assetID},
		domain.AISessionAssetStageReferenceControl,
		fmt.Sprintf(
			"作为 Canny 结构参考接入 ControlNet，强度 %.2f",
			strength,
		),
	); err != nil {
		log.Printf(
			"asset %s: record reference control usage: %v",
			assetID,
			err,
		)
	}
}

// ReferenceControlState 报告参考图条件化是否可用，供 capabilities 用。
func (s *PosterService) ReferenceControlState() (
	available bool,
	patch string,
) {
	return s.template.ReferenceControlAvailable(),
		s.template.ReferencePatch()
}
