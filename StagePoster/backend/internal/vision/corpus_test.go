package vision

import (
	"image"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// TestCorpus 在本机真实候选图上跑一遍不变式。
//
// 默认跳过：这些文件只存在于持久化目录，CI 或别人的机器上没有，让 go test ./...
// 依赖它们就变成了随环境失败的测试。要跑就显式开：
//
//	VISION_CORPUS=1 go test ./internal/vision/ -run TestCorpus -v
//
// 这条测试的价值在于它抓到过合成用例抓不到的东西 —— 244 张图里恰好有一张的
// 主体框是整幅画布，把 384 格全判成禁区。
func TestCorpus(t *testing.T) {
	if os.Getenv("VISION_CORPUS") == "" {
		t.Skip("set VISION_CORPUS=1 to run against the local candidate corpus")
	}

	root := os.Getenv("VISION_CORPUS_ROOT")
	if root == "" {
		root = "/workspace/persistence/stageposter/storage/jobs"
	}

	matches, err := filepath.Glob(
		filepath.Join(root, "*", "poster.png"),
	)
	if err != nil {
		t.Fatal(err)
	}

	if len(matches) == 0 {
		t.Skipf("no candidate images under %s", root)
	}

	sort.Strings(matches)

	zoneCounts := map[int]int{}
	subjectCounts := map[int]int{}

	for _, path := range matches {
		file, err := os.Open(path)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}

		decoded, _, err := image.Decode(file)
		file.Close()

		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}

		analysis, err := Analyze(decoded)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}

		name := filepath.Base(filepath.Dir(path))

		// 前端至少需要两块区域：一块排标题，一块排时间地点。只给一块会逼它
		// 把两组信息叠在一处。
		if len(analysis.TextSafeZones) < 2 {
			t.Errorf(
				"%s: only %d text safe zones (subjects=%v)",
				name,
				len(analysis.TextSafeZones),
				analysis.SubjectBounds,
			)
		}

		if len(analysis.TextSafeZones) > maxTextZones {
			t.Errorf(
				"%s: %d text safe zones exceeds the cap of %d",
				name,
				len(analysis.TextSafeZones),
				maxTextZones,
			)
		}

		zoneCounts[len(analysis.TextSafeZones)]++
		subjectCounts[len(analysis.SubjectBounds)]++

		limit := float64(maxSubjectCoveragePercent)/100 + 0.02

		for _, subject := range analysis.SubjectBounds {
			if subject.Area() > limit {
				t.Errorf(
					"%s: subject covers %.3f of the canvas: %+v",
					name,
					subject.Area(),
					subject,
				)
			}
		}

		for index, zone := range analysis.TextSafeZones {
			if zone.X < 0 || zone.Y < 0 ||
				zone.X+zone.W > 1.0001 ||
				zone.Y+zone.H > 1.0001 {
				t.Errorf(
					"%s: zone %d out of canvas: %+v",
					name,
					index,
					zone.VisualRect,
				)
			}

			for _, subject := range analysis.SubjectBounds {
				if overlaps(zone.VisualRect, subject) {
					t.Errorf(
						"%s: zone %+v overlaps subject %+v",
						name,
						zone.VisualRect,
						subject,
					)
				}
			}

			for other := index + 1; other < len(analysis.TextSafeZones); other++ {
				if overlaps(
					zone.VisualRect,
					analysis.TextSafeZones[other].VisualRect,
				) {
					t.Errorf(
						"%s: zones %d and %d overlap",
						name,
						index,
						other,
					)
				}
			}
		}

		if len(analysis.Palette) == 0 {
			t.Errorf("%s: empty palette", name)
		}

		if analysis.Source != SourcePixels {
			t.Errorf(
				"%s: source = %q before any VLM merge",
				name,
				analysis.Source,
			)
		}
	}

	t.Logf(
		"analyzed %d candidates: zones=%v subjects=%v",
		len(matches),
		zoneCounts,
		subjectCounts,
	)
}
