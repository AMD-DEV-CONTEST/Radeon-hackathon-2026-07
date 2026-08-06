package ironlaw

import "testing"

// TestClassifyTask_ByTaskType: explicit task_type values map to a category
// directly when the type is a known category name. This is the fast path —
// if a caller already knows the category, we honor it.
func TestClassifyTask_ByTaskType(t *testing.T) {
	cases := []struct {
		taskType string
		want     TaskCategory
	}{
		{"coding", CategoryCoding},
		{"reasoning", CategoryReasoning},
		{"execution", CategoryExecution},
		{"ops_maintenance", CategoryOpsMaintenance},
		{"chat", CategoryChat},
		{"review", CategoryReview},
		// case-insensitive
		{"CODING", CategoryCoding},
		{"Review", CategoryReview},
	}
	for _, c := range cases {
		got := ClassifyTask(c.taskType, "any title", "any desc")
		if got != c.want {
			t.Fatalf("ClassifyTask(taskType=%q) = %q, want %q", c.taskType, got, c.want)
		}
	}
}

// TestClassifyTask_KeywordDetection: when task_type is empty or generic,
// classification falls back to keyword matching against the title +
// description, reusing the regexes already defined in pre_intake.go
// (reOpsMaintenance, reExecutionTask). This keeps one source of truth
// for "what counts as ops / execution" rather than re-defining patterns.
func TestClassifyTask_KeywordDetection(t *testing.T) {
	cases := []struct {
		name     string
		taskType string
		title    string
		desc     string
		want     TaskCategory
	}{
		{
			name:  "ops_via_systemctl_keyword",
			title: "重启 nginx",
			desc:  "用 systemctl restart nginx 重启服务",
			want:  CategoryOpsMaintenance,
		},
		{
			name:  "ops_via_disk_clean_keyword",
			title: "磁盘清理",
			desc:  "清理 /var/log 释放空间",
			want:  CategoryOpsMaintenance,
		},
		{
			name:  "execution_via_go_build",
			title: "编译二进制",
			desc:  "执行 go build -o bin/app ./cmd/app",
			want:  CategoryExecution,
		},
		{
			name:  "execution_via_npm_build",
			title: "前端构建",
			desc:  "npm run build 打包产物",
			want:  CategoryExecution,
		},
		{
			name:  "chat_via_chat_keyword_in_desc",
			title: "回复用户",
			desc:  "这是一条 chat 消息需要回复",
			want:  CategoryChat,
		},
		{
			name:  "review_via_review_keyword_in_title",
			title: "code review 这次提交",
			desc:  "检查 PR",
			want:  CategoryReview,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := ClassifyTask(c.taskType, c.title, c.desc)
			if got != c.want {
				t.Fatalf("ClassifyTask(%q,%q,%q) = %q, want %q",
					c.taskType, c.title, c.desc, got, c.want)
			}
		})
	}
}

// TestClassifyTask_DefaultFallback: a task with no recognizable signal
// falls back to CategoryCoding — matching intake.go's existing default
// (taskType == "" → "coding" at intake.go:387).
func TestClassifyTask_DefaultFallback(t *testing.T) {
	got := ClassifyTask("", "do something", "vague description with no keywords")
	if got != CategoryCoding {
		t.Fatalf("ClassifyTask(fallback) = %q, want %q (coding default)", got, CategoryCoding)
	}
}

// TestClassifyTask_ExecutionBeatsCoding: an "execution"-keyword task with
// task_type="coding" must still classify as execution — keyword detection
// overrides the generic default coding category because execution tasks
// need a shell-capable agent (per ILS-R008). This mirrors the intent of
// the existing reExecutionTask flag in pre_intake.go.
func TestClassifyTask_ExecutionBeatsCoding(t *testing.T) {
	got := ClassifyTask("coding", "build", "go build the binary")
	if got != CategoryExecution {
		t.Fatalf("ClassifyTask(coding + go build) = %q, want execution", got)
	}
}

// TestClassifyTask_OpsBeatsAll: ops/maintenance detection has the highest
// priority — ILS-R013 says such tasks must NOT enter the agent queue at
// all, so we must correctly flag them as ops even if the text also
// contains execution or coding signals.
func TestClassifyTask_OpsBeatsAll(t *testing.T) {
	got := ClassifyTask("coding", "rebuild after restart", "go build 然后 systemctl restart nginx")
	if got != CategoryOpsMaintenance {
		t.Fatalf("ClassifyTask(ops+exec mix) = %q, want ops (highest priority)", got)
	}
}
