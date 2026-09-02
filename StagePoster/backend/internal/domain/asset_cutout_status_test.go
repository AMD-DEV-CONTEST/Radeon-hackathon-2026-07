package domain

import "testing"

// 上传响应以前把 processStatus 和 cutout.status 都留成空字符串 —— 两个字段各自
// 都有枚举，空串不在任何一个里面，而前端第一次看到素材恰恰就是这份响应。
// pending 必须能穿过归一化活下来，否则刚入队的素材会被谎报成 unsupported，
// 而它下一秒就变成 ready。
func TestNormalizeAssetCutoutStatusKeepsPending(
	t *testing.T,
) {
	t.Parallel()

	cases := []struct {
		name  string
		input AssetCutoutStatus
		want  AssetCutoutStatus
	}{
		{
			name:  "pending survives",
			input: AssetCutoutStatusPending,
			want:  AssetCutoutStatusPending,
		},
		{
			name:  "ready survives",
			input: AssetCutoutStatusReady,
			want:  AssetCutoutStatusReady,
		},
		{
			name:  "opaque survives",
			input: AssetCutoutStatusOpaque,
			want:  AssetCutoutStatusOpaque,
		},
		{
			name:  "failed survives",
			input: AssetCutoutStatusFailed,
			want:  AssetCutoutStatusFailed,
		},
		{
			// 历史行的 cutout_status 是空的：那些素材确实没跑过抠图。
			name:  "empty folds to unsupported",
			input: AssetCutoutStatus(""),
			want:  AssetCutoutStatusUnsupported,
		},
		{
			name:  "unknown folds to unsupported",
			input: AssetCutoutStatus("halfway"),
			want:  AssetCutoutStatusUnsupported,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			got := NormalizeAssetCutoutStatus(testCase.input)

			if got != testCase.want {
				t.Fatalf(
					"NormalizeAssetCutoutStatus(%q) = %q, want %q",
					testCase.input,
					got,
					testCase.want,
				)
			}
		})
	}
}

// pending 和 unsupported 含义相反，不能是同一个值。
func TestCutoutPendingIsDistinctFromUnsupported(
	t *testing.T,
) {
	t.Parallel()

	if AssetCutoutStatusPending == AssetCutoutStatusUnsupported {
		t.Fatal(
			"pending (排队中，稍后会有结果) 不能等于 " +
				"unsupported (这步不会跑)",
		)
	}
}
