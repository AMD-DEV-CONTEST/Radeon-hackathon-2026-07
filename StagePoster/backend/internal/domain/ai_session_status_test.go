package domain

import "testing"

// 三个终态必须是同一个字符串。会话曾经返回 "cancelled"（英式双 l），海报和
// 任务返回 "canceled"，前端得为同一个概念写两个分支。
func TestCanceledSpellingIsUnified(
	t *testing.T,
) {
	t.Parallel()

	if string(AISessionStatusCanceled) !=
		string(PosterStatusCanceled) {
		t.Fatalf(
			"session %q != poster %q",
			AISessionStatusCanceled,
			PosterStatusCanceled,
		)
	}

	if string(AISessionStatusCanceled) !=
		string(JobStatusCanceled) {
		t.Fatalf(
			"session %q != job %q",
			AISessionStatusCanceled,
			JobStatusCanceled,
		)
	}

	if AISessionStatusCanceled != "canceled" {
		t.Fatalf(
			"wire value drifted: %q",
			AISessionStatusCanceled,
		)
	}
}

// 库里的旧行还带着双 l。归一化失效的话，一个已取消的会话会被判成仍在进行，
// 前端就永远轮询不到终态。
func TestNormalizeAISessionStatus(
	t *testing.T,
) {
	t.Parallel()

	if got := NormalizeAISessionStatus(
		AISessionStatusLegacyCanceled,
	); got != AISessionStatusCanceled {
		t.Fatalf(
			"legacy spelling not folded: %q",
			got,
		)
	}

	if !AISessionStatusLegacyCanceled.Terminal() {
		t.Fatal(
			"legacy cancelled must still count as terminal",
		)
	}

	// 归一化不能碰其他状态。
	for _, status := range []AISessionStatus{
		AISessionStatusCollectingBrief,
		AISessionStatusAwaitingPlanSelection,
		AISessionStatusGeneratingCandidates,
		AISessionStatusAwaitingCandidateSelection,
		AISessionStatusLooping,
		AISessionStatusNeedsUserInput,
		AISessionStatusCompletedWithWarnings,
		AISessionStatusSucceeded,
		AISessionStatusFailed,
		AISessionStatusCanceled,
	} {
		if got := NormalizeAISessionStatus(
			status,
		); got != status {
			t.Fatalf(
				"NormalizeAISessionStatus(%q) = %q",
				status,
				got,
			)
		}
	}
}
