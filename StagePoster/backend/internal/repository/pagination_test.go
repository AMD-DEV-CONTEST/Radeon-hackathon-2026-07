package repository

import (
	"context"
	"fmt"
	"path/filepath"
	"testing"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func newPaginationRepo(
	t *testing.T,
) *Repository {
	t.Helper()

	repositoryInstance, err := OpenSQLite(
		context.Background(),
		filepath.Join(
			t.TempDir(),
			"stageposter-pagination.db",
		),
	)
	if err != nil {
		t.Fatalf("OpenSQLite error: %v", err)
	}

	t.Cleanup(func() {
		_ = repositoryInstance.Close()
	})

	return repositoryInstance
}

func seedJobs(
	t *testing.T,
	repositoryInstance *Repository,
	count int,
) {
	t.Helper()

	ctx := context.Background()
	base := time.Now().UTC().Add(
		-time.Duration(count) * time.Minute,
	)

	for index := 0; index < count; index++ {
		created := base.Add(
			time.Duration(index) * time.Minute,
		)

		if err := repositoryInstance.CreateJob(
			ctx,
			domain.Job{
				ID: fmt.Sprintf(
					"job_%02d",
					index,
				),
				WorkflowKey:     "poster-text",
				WorkflowVersion: "1.0.0",
				Prompt: fmt.Sprintf(
					"prompt %d",
					index,
				),
				Status:    domain.JobStatusQueued,
				CreatedAt: created,
				UpdatedAt: created,
			},
		); err != nil {
			t.Fatalf(
				"create job %d: %v",
				index,
				err,
			)
		}
	}
}

// 分页以前不存在：只有 LIMIT，没有 OFFSET。这条钉住 offset 真的推进了窗口，
// 而且两页之间不重不漏。
func TestListJobsPagination(
	t *testing.T,
) {
	repositoryInstance := newPaginationRepo(t)
	seedJobs(t, repositoryInstance, 25)

	ctx := context.Background()

	total, err := repositoryInstance.CountJobs(ctx)
	if err != nil {
		t.Fatalf("count jobs: %v", err)
	}

	if total != 25 {
		t.Fatalf("expected total 25, got %d", total)
	}

	first, err := repositoryInstance.ListJobs(
		ctx,
		domain.NormalizePage(10, 0),
	)
	if err != nil {
		t.Fatalf("list first page: %v", err)
	}

	second, err := repositoryInstance.ListJobs(
		ctx,
		domain.NormalizePage(10, 10),
	)
	if err != nil {
		t.Fatalf("list second page: %v", err)
	}

	last, err := repositoryInstance.ListJobs(
		ctx,
		domain.NormalizePage(10, 20),
	)
	if err != nil {
		t.Fatalf("list last page: %v", err)
	}

	if len(first) != 10 ||
		len(second) != 10 ||
		len(last) != 5 {
		t.Fatalf(
			"unexpected page sizes: %d/%d/%d",
			len(first),
			len(second),
			len(last),
		)
	}

	seen := map[string]int{}

	for _, page := range [][]domain.Job{
		first,
		second,
		last,
	} {
		for _, job := range page {
			seen[job.ID]++
		}
	}

	if len(seen) != 25 {
		t.Fatalf(
			"pages do not cover every job: %d distinct",
			len(seen),
		)
	}

	for id, times := range seen {
		if times != 1 {
			t.Fatalf(
				"job %s appeared %d times across pages",
				id,
				times,
			)
		}
	}

	// offset 越过表尾必须是空页，不是报错也不是回到第一页。
	beyond, err := repositoryInstance.ListJobs(
		ctx,
		domain.NormalizePage(10, 500),
	)
	if err != nil {
		t.Fatalf("list beyond end: %v", err)
	}

	if len(beyond) != 0 {
		t.Fatalf(
			"expected empty page past end, got %d",
			len(beyond),
		)
	}
}

// ListMeta.HasMore 是客户端判断要不要继续翻页的依据。
func TestListMetaHasMore(
	t *testing.T,
) {
	t.Parallel()

	cases := []struct {
		name    string
		meta    domain.ListMeta
		hasMore bool
	}{
		{
			name: "first page of three",
			meta: domain.NewListMeta(
				domain.NormalizePage(10, 0),
				10,
				25,
			),
			hasMore: true,
		},
		{
			name: "last partial page",
			meta: domain.NewListMeta(
				domain.NormalizePage(10, 20),
				5,
				25,
			),
			hasMore: false,
		},
		{
			name: "exactly consumed",
			meta: domain.NewListMeta(
				domain.NormalizePage(10, 20),
				10,
				30,
			),
			hasMore: false,
		},
		{
			name: "empty table",
			meta: domain.NewListMeta(
				domain.NormalizePage(10, 0),
				0,
				0,
			),
			hasMore: false,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := testCase.meta.HasMore(); got != testCase.hasMore {
				t.Fatalf(
					"HasMore() = %v, want %v",
					got,
					testCase.hasMore,
				)
			}
		})
	}
}

// 越界的 limit 以前被 repository 静默改成 20，调用方看不出被截断。
// 归一化行为集中在 NormalizePage，这里钉住它。
func TestNormalizePageClamping(
	t *testing.T,
) {
	t.Parallel()

	cases := []struct {
		limit  int
		offset int
		want   domain.Page
	}{
		{0, 0, domain.Page{Limit: domain.DefaultPageLimit}},
		{-5, 0, domain.Page{Limit: domain.DefaultPageLimit}},
		{1000, 0, domain.Page{Limit: domain.DefaultPageLimit}},
		{50, -3, domain.Page{Limit: 50, Offset: 0}},
		{50, 100, domain.Page{Limit: 50, Offset: 100}},
		{
			domain.MaxPageLimit,
			0,
			domain.Page{Limit: domain.MaxPageLimit},
		},
	}

	for _, testCase := range cases {
		got := domain.NormalizePage(
			testCase.limit,
			testCase.offset,
		)

		if got != testCase.want {
			t.Fatalf(
				"NormalizePage(%d, %d) = %+v, want %+v",
				testCase.limit,
				testCase.offset,
				got,
				testCase.want,
			)
		}
	}
}

// used_in_stage / actually_used / usage_note 三列建好了、读取路径在解析，但从来
// 没有代码写过 —— 每行恒为 actually_used=0，API 对确实用过的素材主动断言"没用
// 过"。这条钉住写入路径，并确认重复调用幂等、阶段可累加。
func TestMarkAISessionAssetsUsed(
	t *testing.T,
) {
	repositoryInstance := newPaginationRepo(t)
	ctx := context.Background()

	now := time.Now().UTC()

	if err := repositoryInstance.CreateAISession(
		ctx,
		domain.AISessionRecord{
			ID:        "session_usage",
			Status:    domain.AISessionStatusCollectingBrief,
			CreatedAt: now,
			UpdatedAt: now,
		},
	); err != nil {
		t.Fatalf("create session: %v", err)
	}

	if err := repositoryInstance.CreateAsset(
		ctx,
		domain.Asset{
			ID:            "asset_logo",
			Kind:          domain.AssetKindLogo,
			OriginalName:  "logo.png",
			Filename:      "logo.png",
			MimeType:      "image/png",
			SizeBytes:     10,
			SHA256:        "abc",
			StoragePath:   "/tmp/logo.png",
			Width:         100,
			Height:        100,
			ProcessStatus: domain.AssetProcessStatusReady,
			CreatedAt:     now,
		},
	); err != nil {
		t.Fatalf("create asset: %v", err)
	}

	if err := repositoryInstance.BindAISessionAsset(
		ctx,
		"session_usage",
		"asset_logo",
		domain.AISessionAssetPurposeEventLogo,
	); err != nil {
		t.Fatalf("bind asset: %v", err)
	}

	assets, err := repositoryInstance.ListAISessionAssets(
		ctx,
		"session_usage",
	)
	if err != nil {
		t.Fatalf("list assets: %v", err)
	}

	if len(assets) != 1 {
		t.Fatalf("expected 1 asset, got %d", len(assets))
	}

	if assets[0].ActuallyUsed {
		t.Fatal("freshly bound asset must not claim usage")
	}

	// 两个不同阶段，且第二个重复一次。
	for _, stage := range []string{
		domain.AISessionAssetStageBrief,
		domain.AISessionAssetStageLogoOverlay,
		domain.AISessionAssetStageLogoOverlay,
	} {
		if err := repositoryInstance.MarkAISessionAssetsUsed(
			ctx,
			"session_usage",
			[]string{"asset_logo"},
			stage,
			"测试证据",
		); err != nil {
			t.Fatalf("mark used %s: %v", stage, err)
		}
	}

	assets, err = repositoryInstance.ListAISessionAssets(
		ctx,
		"session_usage",
	)
	if err != nil {
		t.Fatalf("list assets again: %v", err)
	}

	if !assets[0].ActuallyUsed {
		t.Fatal("actuallyUsed not persisted")
	}

	if len(assets[0].UsedInStage) != 2 {
		t.Fatalf(
			"expected 2 distinct stages, got %v",
			assets[0].UsedInStage,
		)
	}

	if assets[0].UsedInStage[0] != domain.AISessionAssetStageBrief ||
		assets[0].UsedInStage[1] != domain.AISessionAssetStageLogoOverlay {
		t.Fatalf(
			"stage order lost: %v",
			assets[0].UsedInStage,
		)
	}

	if assets[0].UsageNote != "测试证据" {
		t.Fatalf("note not persisted: %q", assets[0].UsageNote)
	}
}

// 素材没绑在会话上时必须静默跳过 —— 直接走海报接口的调用方根本没有会话，
// 这不是错误。
func TestMarkUnboundAssetIsNoop(
	t *testing.T,
) {
	repositoryInstance := newPaginationRepo(t)

	if err := repositoryInstance.MarkAISessionAssetsUsed(
		context.Background(),
		"session_missing",
		[]string{"asset_missing"},
		domain.AISessionAssetStageBrief,
		"",
	); err != nil {
		t.Fatalf("expected noop, got %v", err)
	}
}

// RecordComposedAssetUsage 按 poster_id 反查会话再落证据。直接调海报接口的
// 调用方没有会话，那种情况必须静默跳过；有会话时则要真的写进去。
func TestRecordComposedAssetUsage(
	t *testing.T,
) {
	repositoryInstance := newPaginationRepo(t)
	ctx := context.Background()
	now := time.Now().UTC()

	if err := repositoryInstance.CreateAsset(
		ctx,
		domain.Asset{
			ID:            "asset_overlay",
			Kind:          domain.AssetKindLogo,
			OriginalName:  "logo.png",
			Filename:      "logo.png",
			MimeType:      "image/png",
			SizeBytes:     10,
			SHA256:        "def",
			StoragePath:   "/tmp/logo.png",
			ProcessStatus: domain.AssetProcessStatusReady,
			CreatedAt:     now,
		},
	); err != nil {
		t.Fatalf("create asset: %v", err)
	}

	// 没有会话指向这张海报：静默跳过。
	if err := repositoryInstance.RecordComposedAssetUsage(
		ctx,
		"poster_orphan",
		[]string{"asset_overlay"},
	); err != nil {
		t.Fatalf("orphan poster should be a noop: %v", err)
	}

	if err := repositoryInstance.CreateAISession(
		ctx,
		domain.AISessionRecord{
			ID:        "session_overlay",
			Status:    domain.AISessionStatusLooping,
			CreatedAt: now,
			UpdatedAt: now,
		},
	); err != nil {
		t.Fatalf("create session: %v", err)
	}

	if err := repositoryInstance.BindAISessionAsset(
		ctx,
		"session_overlay",
		"asset_overlay",
		domain.AISessionAssetPurposeEventLogo,
	); err != nil {
		t.Fatalf("bind asset: %v", err)
	}

	// ai_sessions.poster_id 有外键，得先有真实的海报行。
	if err := repositoryInstance.CreatePoster(
		ctx,
		domain.PosterRecord{
			ID:           "poster_linked",
			Status:       domain.PosterStatusComposing,
			StyleKey:     "metal-gothic-v1",
			EventJSON:    "{}",
			BrandingJSON: "{}",
			VisualJSON:   "{}",
			GoalJSON:     "{}",
			CreatedAt:    now,
			UpdatedAt:    now,
		},
	); err != nil {
		t.Fatalf("create poster: %v", err)
	}

	// 把会话挂到海报上，模拟走 AI 会话生成的海报。
	session, err := repositoryInstance.GetAISession(
		ctx,
		"session_overlay",
	)
	if err != nil {
		t.Fatalf("get session: %v", err)
	}

	session.PosterID = "poster_linked"

	if err := repositoryInstance.UpdateAISession(
		ctx,
		session,
	); err != nil {
		t.Fatalf("link poster: %v", err)
	}

	if err := repositoryInstance.RecordComposedAssetUsage(
		ctx,
		"poster_linked",
		[]string{"asset_overlay"},
	); err != nil {
		t.Fatalf("record usage: %v", err)
	}

	assets, err := repositoryInstance.ListAISessionAssets(
		ctx,
		"session_overlay",
	)
	if err != nil {
		t.Fatalf("list assets: %v", err)
	}

	if len(assets) != 1 || !assets[0].ActuallyUsed {
		t.Fatalf("usage not recorded: %+v", assets)
	}

	if len(assets[0].UsedInStage) != 1 ||
		assets[0].UsedInStage[0] !=
			domain.AISessionAssetStageLogoOverlay {
		t.Fatalf(
			"expected logo_overlay stage, got %v",
			assets[0].UsedInStage,
		)
	}
}
