package service

import (
	"context"
	"errors"
	"io"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	"github.com/Ripped-sys/StagePoster/backend/internal/storage"
)

var ErrInvalidAssetKind = errors.New("invalid asset kind")

type AssetFile struct {
	Body         io.ReadCloser
	Filename     string
	OriginalName string
	ContentType  string
}

type AssetService struct {
	repository *repository.Repository
	store      *storage.AssetStore
}

func NewAssetService(
	repositoryInstance *repository.Repository,
	store *storage.AssetStore,
) *AssetService {
	return &AssetService{
		repository: repositoryInstance,
		store:      store,
	}
}

func (s *AssetService) Upload(
	ctx context.Context,
	kindValue string,
	originalName string,
	body io.Reader,
) (domain.AssetResponse, error) {
	kind := domain.AssetKind(
		strings.ToLower(strings.TrimSpace(kindValue)),
	)

	if !kind.Valid() {
		return domain.AssetResponse{}, ErrInvalidAssetKind
	}

	asset, err := s.store.Save(
		kind,
		originalName,
		body,
	)
	if err != nil {
		return domain.AssetResponse{}, err
	}

	// store.Save 只管落盘，不填处理状态。不显式写的话，上传响应里
	// processStatus 和 cutout.status 都是空字符串 —— 两个都不在各自的枚举里，
	// 前端拿到的第一份素材数据反而是无法解释的。真实状态是"已入队待处理"。
	asset.ProcessStatus = domain.AssetProcessStatusPending
	asset.Cutout.Status = domain.AssetCutoutStatusPending

	if err := s.repository.CreateAsset(ctx, asset); err != nil {
		_ = s.store.Delete(asset)
		return domain.AssetResponse{}, err
	}

	return assetResponse(asset), nil
}

func (s *AssetService) Get(
	ctx context.Context,
	assetID string,
) (domain.AssetResponse, error) {
	asset, err := s.repository.GetAsset(ctx, assetID)
	if err != nil {
		return domain.AssetResponse{}, err
	}

	return assetResponse(asset), nil
}

func (s *AssetService) List(
	ctx context.Context,
	page domain.Page,
) (domain.AssetListResponse, error) {
	assets, err := s.repository.ListAssets(ctx, page)
	if err != nil {
		return domain.AssetListResponse{}, err
	}

	total, err := s.repository.CountAssets(ctx)
	if err != nil {
		return domain.AssetListResponse{}, err
	}

	items := make(
		[]domain.AssetResponse,
		0,
		len(assets),
	)

	for _, asset := range assets {
		items = append(items, assetResponse(asset))
	}

	return domain.AssetListResponse{
		Items: items,
		ListMeta: domain.NewListMeta(
			page,
			len(items),
			total,
		),
	}, nil
}

func (s *AssetService) OpenContent(
	ctx context.Context,
	assetID string,
) (AssetFile, error) {
	asset, err := s.repository.GetAsset(ctx, assetID)
	if err != nil {
		return AssetFile{}, err
	}

	file, err := s.store.Open(asset)
	if err != nil {
		return AssetFile{}, err
	}

	return AssetFile{
		Body:         file,
		Filename:     asset.Filename,
		OriginalName: asset.OriginalName,
		ContentType:  asset.MimeType,
	}, nil
}

func assetResponse(
	asset domain.Asset,
) domain.AssetResponse {
	return domain.AssetResponse{
		ID:             asset.ID,
		Kind:           asset.Kind,
		OriginalName:   asset.OriginalName,
		Filename:       asset.Filename,
		MimeType:       asset.MimeType,
		SizeBytes:      asset.SizeBytes,
		SHA256:         asset.SHA256,
		Width:          asset.Width,
		Height:         asset.Height,
		ContentURL:     "/api/assets/" + asset.ID + "/content",
		ProcessStatus:  asset.ProcessStatus,
		ProcessError:   asset.ProcessError,
		ProcessedAt:    asset.ProcessedAt,
		MaskPath:       asset.MaskPath,
		Cutout:         asset.Cutout,
		AnalysisJSON:   asset.AnalysisJSON,
		DominantColors: asset.DominantColors,
		ProcessVersion: asset.ProcessVersion,
		CreatedAt:      asset.CreatedAt,
	}
}
