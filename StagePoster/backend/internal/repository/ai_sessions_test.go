package repository

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func TestAISessionPersistence(
	t *testing.T,
) {
	ctx := context.Background()

	repositoryInstance, err := OpenSQLite(
		ctx,
		filepath.Join(
			t.TempDir(),
			"stageposter-test.db",
		),
	)
	if err != nil {
		t.Fatalf(
			"OpenSQLite error: %v",
			err,
		)
	}
	defer repositoryInstance.Close()

	now := time.Now().UTC()

	session := domain.AISessionRecord{
		ID:     "session_test",
		Status: domain.AISessionStatusCollectingBrief,
		Brief: domain.AISessionBrief{
			Event: domain.EventBrief{
				Title:  "Abyssal Kingdom",
				Artist: "Maverick",
			},
			Visual: domain.VisualBrief{
				Theme:      "dark gothic kingdom",
				MusicGenre: "gothic metal",
				Mood: []string{
					"epic",
					"mysterious",
				},
			},
		},
		CreatedAt: now,
		UpdatedAt: now,
	}

	if err := repositoryInstance.CreateAISession(
		ctx,
		session,
	); err != nil {
		t.Fatalf(
			"CreateAISession error: %v",
			err,
		)
	}

	stored, err := repositoryInstance.GetAISession(
		ctx,
		session.ID,
	)
	if err != nil {
		t.Fatalf(
			"GetAISession error: %v",
			err,
		)
	}

	if stored.ID != session.ID {
		t.Fatalf(
			"unexpected session ID %q",
			stored.ID,
		)
	}

	if stored.Brief.Event.Title !=
		"Abyssal Kingdom" {
		t.Fatalf(
			"unexpected title %q",
			stored.Brief.Event.Title,
		)
	}

	message := domain.AIMessageRecord{
		ID:        "message_test",
		SessionID: session.ID,
		Role:      domain.AIMessageRoleUser,
		Content:   "我要一个暗黑哥特海报",
		CreatedAt: now,
	}

	if err := repositoryInstance.CreateAIMessage(
		ctx,
		message,
	); err != nil {
		t.Fatalf(
			"CreateAIMessage error: %v",
			err,
		)
	}

	messages, err := repositoryInstance.ListAIMessages(
		ctx,
		session.ID,
		20,
	)
	if err != nil {
		t.Fatalf(
			"ListAIMessages error: %v",
			err,
		)
	}

	if len(messages) != 1 {
		t.Fatalf(
			"expected 1 message, got %d",
			len(messages),
		)
	}

	plans := []domain.DesignPlan{
		{
			ID:             "black-throne",
			Name:           "黑色王座",
			Concept:        "黑色王座与巨大羽翼",
			PositivePrompt: "black gothic throne",
			NegativePrompt: "text, watermark",
		},
		{
			ID:             "gothic-frame",
			Name:           "哥特画框",
			Concept:        "哥特画框与深渊",
			PositivePrompt: "gothic frame",
			NegativePrompt: "text, watermark",
		},
		{
			ID:             "abyss-wings",
			Name:           "深渊羽翼",
			Concept:        "深渊与巨型羽翼",
			PositivePrompt: "abyssal wings",
			NegativePrompt: "text, watermark",
		},
	}

	if err := repositoryInstance.ReplaceAIDesignPlans(
		ctx,
		session.ID,
		plans,
	); err != nil {
		t.Fatalf(
			"ReplaceAIDesignPlans error: %v",
			err,
		)
	}

	storedPlans, err :=
		repositoryInstance.ListAIDesignPlans(
			ctx,
			session.ID,
		)
	if err != nil {
		t.Fatalf(
			"ListAIDesignPlans error: %v",
			err,
		)
	}

	if len(storedPlans) != 3 {
		t.Fatalf(
			"expected 3 plans, got %d",
			len(storedPlans),
		)
	}

	if err := repositoryInstance.SelectAIDesignPlan(
		ctx,
		session.ID,
		"black-throne",
	); err != nil {
		t.Fatalf(
			"SelectAIDesignPlan error: %v",
			err,
		)
	}

	selected, err :=
		repositoryInstance.GetAIDesignPlan(
			ctx,
			session.ID,
			"black-throne",
		)
	if err != nil {
		t.Fatalf(
			"GetAIDesignPlan error: %v",
			err,
		)
	}

	if !selected.Selected {
		t.Fatal("expected selected plan")
	}
}

// 库里已经有一批 status='cancelled' 的旧行。迁移要把它们改成单 l，
// 读取侧也要兜住——否则已取消的会话在 API 里显示成仍在进行。
func TestAISessionLegacyCanceledSpelling(
	t *testing.T,
) {
	ctx := context.Background()

	repositoryInstance, err := OpenSQLite(
		ctx,
		filepath.Join(
			t.TempDir(),
			"stageposter-legacy.db",
		),
	)
	if err != nil {
		t.Fatalf("OpenSQLite error: %v", err)
	}
	defer repositoryInstance.Close()

	now := time.Now().UTC()

	session := domain.AISessionRecord{
		ID:        "session_legacy",
		Status:    domain.AISessionStatusCollectingBrief,
		CreatedAt: now,
		UpdatedAt: now,
	}

	if err := repositoryInstance.CreateAISession(
		ctx,
		session,
	); err != nil {
		t.Fatalf("CreateAISession error: %v", err)
	}

	// 模拟旧二进制写下的行。
	if _, err := repositoryInstance.db.ExecContext(
		ctx,
		`UPDATE ai_sessions SET status = ? WHERE id = ?`,
		string(domain.AISessionStatusLegacyCanceled),
		session.ID,
	); err != nil {
		t.Fatalf("seed legacy status: %v", err)
	}

	// 读取侧归一化：迁移还没再跑，Get 也必须返回单 l。
	stored, err := repositoryInstance.GetAISession(
		ctx,
		session.ID,
	)
	if err != nil {
		t.Fatalf("GetAISession error: %v", err)
	}

	if stored.Status != domain.AISessionStatusCanceled {
		t.Fatalf(
			"read path did not normalize: %q",
			stored.Status,
		)
	}

	if !stored.Status.Terminal() {
		t.Fatal("canceled session must be terminal")
	}

	// 迁移是幂等的，并且真的改了落库的值。
	if err := repositoryInstance.MigrateAISessions(
		ctx,
	); err != nil {
		t.Fatalf("MigrateAISessions error: %v", err)
	}

	var raw string

	if err := repositoryInstance.db.QueryRowContext(
		ctx,
		`SELECT status FROM ai_sessions WHERE id = ?`,
		session.ID,
	).Scan(&raw); err != nil {
		t.Fatalf("read raw status: %v", err)
	}

	if raw != string(domain.AISessionStatusCanceled) {
		t.Fatalf(
			"migration left stored status as %q",
			raw,
		)
	}
}
