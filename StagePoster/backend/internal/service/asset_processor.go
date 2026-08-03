package service

import (
	"context"
	"encoding/json"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"os"
	"sync"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
)

// AssetProcessor handles asynchronous processing of uploaded assets.
type AssetProcessor struct {
	repository *repository.Repository
	queue      chan processJob
	shutdown   chan struct{}
	wg         sync.WaitGroup
	started    bool
}

type processJob struct {
	AssetID string
	Kind    domain.AssetKind
}

func NewAssetProcessor(
	repositoryInstance *repository.Repository,
	workerCount int,
) *AssetProcessor {
	if workerCount <= 0 {
		workerCount = 2
	}

	p := &AssetProcessor{
		repository: repositoryInstance,
		queue:      make(chan processJob, 256),
		shutdown:   make(chan struct{}),
	}

	for i := 0; i < workerCount; i++ {
		p.wg.Add(1)
		go p.worker(i)
	}

	p.started = true

	return p
}

func (p *AssetProcessor) Enqueue(ctx context.Context, assetID string, kind domain.AssetKind) error {
	if !p.started {
		return nil
	}

	select {
	case p.queue <- processJob{AssetID: assetID, Kind: kind}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	default:
		return p.processAsset(ctx, assetID, kind)
	}
}

func (p *AssetProcessor) Shutdown(ctx context.Context) error {
	if !p.started {
		return nil
	}

	close(p.shutdown)

	done := make(chan struct{})
	go func() {
		p.wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p *AssetProcessor) worker(id int) {
	defer p.wg.Done()

	for {
		select {
		case job, ok := <-p.queue:
			if !ok {
				return
			}
			_ = p.processAsset(context.Background(), job.AssetID, job.Kind)

		case <-p.shutdown:
			return
		}
	}
}

func (p *AssetProcessor) processAsset(
	ctx context.Context,
	assetID string,
	kind domain.AssetKind,
) error {
	now := time.Now().UTC()

	if err := p.repository.UpdateAssetProcessStatus(
		ctx,
		assetID,
		domain.AssetProcessStatusProcessing,
		"",
		&now,
		"",
		"",
		// 处理中途读到的必须还是 pending。这里以前写 unsupported，于是在
		// processing 和最终结果之间存在一个窗口，API 对一张马上就会判定为
		// ready 的透明图断言"抠图不支持"。
		domain.AssetCutout{
			Status: domain.AssetCutoutStatusPending,
		},
	); err != nil {
		return fmt.Errorf("mark asset processing: %w", err)
	}

	var maskPath string
	var analysisJSON string
	var processErr error

	cutout := domain.AssetCutout{
		Status: domain.AssetCutoutStatusUnsupported,
	}

	switch kind {
	case domain.AssetKindLogo:
		cutout, processErr = p.inspectCutout(ctx, assetID)

	case domain.AssetKindPerson:
		cutout, processErr = p.inspectCutout(ctx, assetID)

	case domain.AssetKindReference:
		_, analysisJSON, processErr = p.processReference(ctx, assetID)
	}

	status := domain.AssetProcessStatusReady
	processError := ""
	if processErr != nil {
		status = domain.AssetProcessStatusFailed
		processError = processErr.Error()
	}

	processedAt := &now
	if status == domain.AssetProcessStatusFailed {
		processedAt = nil
	}

	return p.repository.UpdateAssetProcessStatus(
		ctx,
		assetID,
		status,
		processError,
		processedAt,
		maskPath,
		analysisJSON,
		cutout,
	)
}

// inspectCutout 报告抠图 / 透明化的真实状态。
//
// 这里替换掉了原来的 generateMask：那个函数把源文件逐字节复制成
// mask_<id>.png 就宣告成功，谁都没消费过它，合成器根本看不到蒙版。现在不再
// 伪造蒙版，而是做一件真能做的事 —— 实测 alpha 通道。
//
// 合成器只按已有 alpha 叠加（xDraw.Over），自己不抠背景。所以一个不透明的
// logo 会以矩形压在海报上，这件事必须让调用方看得见。
func (p *AssetProcessor) inspectCutout(
	ctx context.Context,
	assetID string,
) (domain.AssetCutout, error) {
	asset, err := p.repository.GetAsset(ctx, assetID)
	if err != nil {
		return domain.AssetCutout{
			Status: domain.AssetCutoutStatusUnsupported,
		}, err
	}

	hasAlpha, err := imageHasAlpha(asset.StoragePath)
	if err != nil {
		return domain.AssetCutout{
			Status: domain.AssetCutoutStatusFailed,
		}, fmt.Errorf("inspect alpha channel: %w", err)
	}

	status := domain.AssetCutoutStatusOpaque
	if hasAlpha {
		status = domain.AssetCutoutStatusReady
	}

	return domain.AssetCutout{
		Status:   status,
		HasAlpha: hasAlpha,
	}, nil
}

// imageHasAlpha 解码图片并查找任何非全不透明的像素。
// 逐像素扫描，遇到第一个透明像素就返回，最坏情况才走满整张图。
func imageHasAlpha(path string) (bool, error) {
	file, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer file.Close()

	decoded, _, err := image.Decode(file)
	if err != nil {
		return false, err
	}

	if opaque, ok := decoded.(interface{ Opaque() bool }); ok {
		// Go 标准库的多数图像类型提供 Opaque()，比逐像素快得多。
		return !opaque.Opaque(), nil
	}

	bounds := decoded.Bounds()

	for y := bounds.Min.Y; y < bounds.Max.Y; y++ {
		for x := bounds.Min.X; x < bounds.Max.X; x++ {
			if _, _, _, alpha := decoded.At(x, y).RGBA(); alpha < 0xffff {
				return true, nil
			}
		}
	}

	return false, nil
}

func (p *AssetProcessor) processReference(
	ctx context.Context,
	assetID string,
) ([]string, string, error) {
	asset, err := p.repository.GetAsset(ctx, assetID)
	if err != nil {
		return nil, "", err
	}

	colors, analysis, err := analyzeReference(asset)
	if err != nil {
		return nil, "", err
	}

	analysisJSON := ""
	if analysis != nil {
		raw, _ := json.Marshal(analysis)
		analysisJSON = string(raw)
	}

	return colors, analysisJSON, nil
}

// analyzeReference analyzes color and composition of a reference image.
func analyzeReference(asset domain.Asset) ([]string, map[string]any, error) {
	file, err := os.Open(asset.StoragePath)
	if err != nil {
		return nil, nil, fmt.Errorf("open reference for analysis: %w", err)
	}
	defer file.Close()

	colors := extractDominantColors(file)
	analysis := map[string]any{
		"aspectRatio":    float64(asset.Width) / float64(asset.Height),
		"dominantColors": colors,
		"width":          asset.Width,
		"height":         asset.Height,
	}

	return colors, analysis, nil
}

// extractDominantColors extracts dominant colors from an image file.
func extractDominantColors(r io.Reader) []string {
	// Placeholder: integrate with go-colorful or similar for production.
	return nil
}
