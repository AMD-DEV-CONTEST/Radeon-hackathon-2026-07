package repository

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func (r *Repository) MigrateAISessions(
	ctx context.Context,
) error {
	statements := []string{
		`
		CREATE TABLE IF NOT EXISTS ai_sessions (
			id TEXT PRIMARY KEY,
			status TEXT NOT NULL,
			brief_json TEXT NOT NULL,

			selected_plan_id TEXT,
			poster_id TEXT,
			error_message TEXT,

			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,

			FOREIGN KEY(poster_id)
				REFERENCES poster_requests(id)
			ON DELETE SET NULL
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_ai_sessions_status_updated
		ON ai_sessions(status, updated_at DESC)
		`,
		`
		CREATE TABLE IF NOT EXISTS ai_messages (
			id TEXT PRIMARY KEY,
			session_id TEXT NOT NULL,
			role TEXT NOT NULL,
			content TEXT NOT NULL,
			created_at TEXT NOT NULL,

			FOREIGN KEY(session_id)
				REFERENCES ai_sessions(id)
			ON DELETE CASCADE
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_ai_messages_session_created
		ON ai_messages(session_id, created_at ASC)
		`,
		`
		CREATE TABLE IF NOT EXISTS ai_session_assets (
			session_id TEXT NOT NULL,
			asset_id TEXT NOT NULL,
			purpose TEXT NOT NULL,
			created_at TEXT NOT NULL,

			used_in_stage TEXT DEFAULT '',
			actually_used INTEGER NOT NULL DEFAULT 0,
			usage_note TEXT,

			PRIMARY KEY(session_id, asset_id),

			FOREIGN KEY(session_id)
				REFERENCES ai_sessions(id)
			ON DELETE CASCADE,

			FOREIGN KEY(asset_id)
				REFERENCES assets(id)
			ON DELETE CASCADE
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_ai_session_assets_session
		ON ai_session_assets(session_id, created_at ASC)
		`,
		`
		CREATE TABLE IF NOT EXISTS ai_design_plans (
			session_id TEXT NOT NULL,
			plan_id TEXT NOT NULL,
			plan_json TEXT NOT NULL,
			selected INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,

			PRIMARY KEY(session_id, plan_id),

			FOREIGN KEY(session_id)
				REFERENCES ai_sessions(id)
			ON DELETE CASCADE
		)
		`,
		`
		CREATE INDEX IF NOT EXISTS idx_ai_design_plans_session
		ON ai_design_plans(session_id, created_at ASC)
		`,
	}

	for _, statement := range statements {
		if _, err := r.db.ExecContext(
			ctx,
			statement,
		); err != nil {
			return fmt.Errorf(
				"run AI session migration: %w",
				err,
			)
		}
	}

	// Migrate existing table if it lacks the new columns (idempotent).
	alterStatements := []string{
		"ALTER TABLE ai_session_assets ADD COLUMN used_in_stage TEXT DEFAULT ''",
		"ALTER TABLE ai_session_assets ADD COLUMN actually_used INTEGER NOT NULL DEFAULT 0",
		"ALTER TABLE ai_session_assets ADD COLUMN usage_note TEXT",
	}

	for _, stmt := range alterStatements {
		if _, err := r.db.ExecContext(ctx, stmt); err != nil {
			if !strings.Contains(err.Error(), "duplicate column") &&
				!strings.Contains(err.Error(), "already exists") {
				return fmt.Errorf(
					"alter ai_session_assets: %w",
					err,
				)
			}
		}
	}

	// 终态拼写统一：会话曾经写 "cancelled"（英式双 l），海报和任务写
	// "canceled"。同一个 API 返回两种拼法，前端得写两个分支。已统一到单 l，
	// 这条把库里的旧行改过来。幂等。
	if _, err := r.db.ExecContext(
		ctx,
		`
		UPDATE ai_sessions
		SET status = ?
		WHERE status = ?
		`,
		string(domain.AISessionStatusCanceled),
		string(domain.AISessionStatusLegacyCanceled),
	); err != nil {
		return fmt.Errorf(
			"normalize canceled AI session status: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) CreateAISession(
	ctx context.Context,
	session domain.AISessionRecord,
) error {
	briefJSON, err := json.Marshal(session.Brief)
	if err != nil {
		return fmt.Errorf(
			"encode AI session brief: %w",
			err,
		)
	}

	_, err = r.db.ExecContext(
		ctx,
		`
		INSERT INTO ai_sessions (
			id,
			status,
			brief_json,
			selected_plan_id,
			poster_id,
			error_message,
			created_at,
			updated_at
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		`,
		session.ID,
		session.Status,
		string(briefJSON),
		nullableString(session.SelectedPlanID),
		nullableString(session.PosterID),
		nullableString(session.ErrorMessage),
		formatTime(session.CreatedAt),
		formatTime(session.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf(
			"insert AI session: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) GetAISession(
	ctx context.Context,
	sessionID string,
) (domain.AISessionRecord, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			id,
			status,
			brief_json,
			selected_plan_id,
			poster_id,
			error_message,
			created_at,
			updated_at
		FROM ai_sessions
		WHERE id = ?
		`,
		sessionID,
	)

	session, err := scanAISession(row)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.AISessionRecord{},
			ErrNotFound
	}

	if err != nil {
		return domain.AISessionRecord{},
			fmt.Errorf(
				"get AI session: %w",
				err,
			)
	}

	return session, nil
}

func (r *Repository) UpdateAISession(
	ctx context.Context,
	session domain.AISessionRecord,
) error {
	briefJSON, err := json.Marshal(session.Brief)
	if err != nil {
		return fmt.Errorf(
			"encode AI session brief: %w",
			err,
		)
	}

	session.UpdatedAt = time.Now().UTC()

	result, err := r.db.ExecContext(
		ctx,
		`
		UPDATE ai_sessions
		SET
			status = ?,
			brief_json = ?,
			selected_plan_id = ?,
			poster_id = ?,
			error_message = ?,
			updated_at = ?
		WHERE id = ?
		`,
		session.Status,
		string(briefJSON),
		nullableString(session.SelectedPlanID),
		nullableString(session.PosterID),
		nullableString(session.ErrorMessage),
		formatTime(session.UpdatedAt),
		session.ID,
	)
	if err != nil {
		return fmt.Errorf(
			"update AI session: %w",
			err,
		)
	}

	return requireAffected(result)
}

func (r *Repository) CreateAIMessage(
	ctx context.Context,
	message domain.AIMessageRecord,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO ai_messages (
			id,
			session_id,
			role,
			content,
			created_at
		)
		VALUES (?, ?, ?, ?, ?)
		`,
		message.ID,
		message.SessionID,
		message.Role,
		message.Content,
		formatTime(message.CreatedAt),
	)
	if err != nil {
		return fmt.Errorf(
			"insert AI message: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) ListAIMessages(
	ctx context.Context,
	sessionID string,
	limit int,
) ([]domain.AIMessageRecord, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}

	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			id,
			session_id,
			role,
			content,
			created_at
		FROM (
			SELECT
				id,
				session_id,
				role,
				content,
				created_at
			FROM ai_messages
			WHERE session_id = ?
			ORDER BY created_at DESC
			LIMIT ?
		)
		ORDER BY created_at ASC
		`,
		sessionID,
		limit,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list AI messages: %w",
			err,
		)
	}
	defer rows.Close()

	messages := make(
		[]domain.AIMessageRecord,
		0,
		limit,
	)

	for rows.Next() {
		var message domain.AIMessageRecord
		var createdAt string

		if err := rows.Scan(
			&message.ID,
			&message.SessionID,
			&message.Role,
			&message.Content,
			&createdAt,
		); err != nil {
			return nil, fmt.Errorf(
				"scan AI message: %w",
				err,
			)
		}

		message.CreatedAt, err = parseTime(createdAt)
		if err != nil {
			return nil, err
		}

		messages = append(messages, message)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate AI messages: %w",
			err,
		)
	}

	return messages, nil
}

func (r *Repository) BindAISessionAsset(
	ctx context.Context,
	sessionID string,
	assetID string,
	purpose domain.AISessionAssetPurpose,
) error {
	_, err := r.db.ExecContext(
		ctx,
		`
		INSERT INTO ai_session_assets (
			session_id,
			asset_id,
			purpose,
			created_at
		)
		VALUES (?, ?, ?, ?)
		ON CONFLICT(session_id, asset_id)
		DO UPDATE SET
			purpose = excluded.purpose
		`,
		sessionID,
		assetID,
		purpose,
		formatTime(time.Now().UTC()),
	)
	if err != nil {
		return fmt.Errorf(
			"bind AI session asset: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) ListAISessionAssets(ctx context.Context,
	sessionID string,
) ([]domain.AISessionAssetRecord, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			sa.session_id,
			sa.asset_id,
			sa.purpose,

			a.kind,
			a.original_name,
			a.mime_type,
			a.width,
			a.height,
			a.storage_path,

			sa.used_in_stage,
			sa.actually_used,
			sa.usage_note,

			sa.created_at
		FROM ai_session_assets sa
		JOIN assets a ON a.id = sa.asset_id
		WHERE sa.session_id = ?
		ORDER BY sa.created_at ASC
		`,
		sessionID,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list AI session assets: %w",
			err,
		)
	}
	defer rows.Close()

	var assets []domain.AISessionAssetRecord

	for rows.Next() {
		var asset domain.AISessionAssetRecord
		var createdAt string
		var usedInStage sql.NullString
		var usageNote sql.NullString

		if err := rows.Scan(
			&asset.SessionID,
			&asset.AssetID,
			&asset.Purpose,
			&asset.Kind,
			&asset.OriginalName,
			&asset.MimeType,
			&asset.Width,
			&asset.Height,
			&asset.StoragePath,
			&usedInStage,
			&asset.ActuallyUsed,
			&usageNote,
			&createdAt,
		); err != nil {
			return nil, fmt.Errorf(
				"scan AI session asset: %w",
				err,
			)
		}

		if usedInStage.Valid && usedInStage.String != "" {
			asset.UsedInStage = strings.Split(usedInStage.String, ",")
		}

		if usageNote.Valid {
			asset.UsageNote = usageNote.String
		}

		asset.CreatedAt, err = parseTime(createdAt)
		if err != nil {
			return nil, err
		}

		assets = append(assets, asset)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate AI session assets: %w",
			err,
		)
	}

	return assets, nil
}

func (r *Repository) ReplaceAIDesignPlans(
	ctx context.Context,
	sessionID string,
	plans []domain.DesignPlan,
) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf(
			"begin replace AI plans: %w",
			err,
		)
	}
	defer tx.Rollback()

	if _, err := tx.ExecContext(
		ctx,
		`
		DELETE FROM ai_design_plans
		WHERE session_id = ?
		`,
		sessionID,
	); err != nil {
		return fmt.Errorf(
			"clear AI plans: %w",
			err,
		)
	}

	now := time.Now().UTC()

	for _, plan := range plans {
		planJSON, err := json.Marshal(plan)
		if err != nil {
			return fmt.Errorf(
				"encode AI design plan %s: %w",
				plan.ID,
				err,
			)
		}

		if _, err := tx.ExecContext(
			ctx,
			`
			INSERT INTO ai_design_plans (
				session_id,
				plan_id,
				plan_json,
				selected,
				created_at
			)
			VALUES (?, ?, ?, 0, ?)
			`,
			sessionID,
			plan.ID,
			string(planJSON),
			formatTime(now),
		); err != nil {
			return fmt.Errorf(
				"insert AI design plan %s: %w",
				plan.ID,
				err,
			)
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf(
			"commit replace AI plans: %w",
			err,
		)
	}

	return nil
}

func (r *Repository) ListAIDesignPlans(
	ctx context.Context,
	sessionID string,
) ([]domain.AIDesignPlanRecord, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`
		SELECT
			session_id,
			plan_id,
			plan_json,
			selected,
			created_at
		FROM ai_design_plans
		WHERE session_id = ?
		ORDER BY created_at ASC, plan_id ASC
		`,
		sessionID,
	)
	if err != nil {
		return nil, fmt.Errorf(
			"list AI design plans: %w",
			err,
		)
	}
	defer rows.Close()

	var plans []domain.AIDesignPlanRecord

	for rows.Next() {
		plan, err := scanAIDesignPlan(rows)
		if err != nil {
			return nil, err
		}

		plans = append(plans, plan)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf(
			"iterate AI design plans: %w",
			err,
		)
	}

	return plans, nil
}

func (r *Repository) GetAIDesignPlan(
	ctx context.Context,
	sessionID string,
	planID string,
) (domain.AIDesignPlanRecord, error) {
	row := r.db.QueryRowContext(
		ctx,
		`
		SELECT
			session_id,
			plan_id,
			plan_json,
			selected,
			created_at
		FROM ai_design_plans
		WHERE session_id = ? AND plan_id = ?
		`,
		sessionID,
		planID,
	)

	plan, err := scanAIDesignPlan(row)

	if errors.Is(err, sql.ErrNoRows) {
		return domain.AIDesignPlanRecord{},
			ErrNotFound
	}

	if err != nil {
		return domain.AIDesignPlanRecord{},
			fmt.Errorf(
				"get AI design plan: %w",
				err,
			)
	}

	return plan, nil
}

func (r *Repository) SelectAIDesignPlan(
	ctx context.Context,
	sessionID string,
	planID string,
) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf(
			"begin select AI plan: %w",
			err,
		)
	}
	defer tx.Rollback()

	var exists int

	err = tx.QueryRowContext(
		ctx,
		`
		SELECT 1
		FROM ai_design_plans
		WHERE session_id = ? AND plan_id = ?
		`,
		sessionID,
		planID,
	).Scan(&exists)

	if errors.Is(err, sql.ErrNoRows) {
		return ErrNotFound
	}

	if err != nil {
		return fmt.Errorf(
			"verify AI design plan: %w",
			err,
		)
	}

	if _, err := tx.ExecContext(
		ctx,
		`
		UPDATE ai_design_plans
		SET selected = 0
		WHERE session_id = ?
		`,
		sessionID,
	); err != nil {
		return fmt.Errorf(
			"clear selected AI plan: %w",
			err,
		)
	}

	if _, err := tx.ExecContext(
		ctx,
		`
		UPDATE ai_design_plans
		SET selected = 1
		WHERE session_id = ? AND plan_id = ?
		`,
		sessionID,
		planID,
	); err != nil {
		return fmt.Errorf(
			"select AI design plan: %w",
			err,
		)
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf(
			"commit selected AI plan: %w",
			err,
		)
	}

	return nil
}

func scanAISession(
	source scanner,
) (domain.AISessionRecord, error) {
	var session domain.AISessionRecord

	var briefJSON string
	var selectedPlanID sql.NullString
	var posterID sql.NullString
	var errorMessage sql.NullString
	var createdAt string
	var updatedAt string

	if err := source.Scan(
		&session.ID,
		&session.Status,
		&briefJSON,
		&selectedPlanID,
		&posterID,
		&errorMessage,
		&createdAt,
		&updatedAt,
	); err != nil {
		return domain.AISessionRecord{}, err
	}

	if err := json.Unmarshal(
		[]byte(briefJSON),
		&session.Brief,
	); err != nil {
		return domain.AISessionRecord{},
			fmt.Errorf(
				"decode AI session brief: %w",
				err,
			)
	}

	session.SelectedPlanID = selectedPlanID.String
	session.PosterID = posterID.String
	session.ErrorMessage = errorMessage.String

	// 迁移语句已经把库里的行改成了单 l，但一个跑着旧二进制的进程仍可能写回
	// "cancelled"。读取侧归一化让新旧进程共用一个库时也不会出现两种终态。
	session.Status = domain.NormalizeAISessionStatus(
		session.Status,
	)

	var err error

	session.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.AISessionRecord{}, err
	}

	session.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.AISessionRecord{}, err
	}

	return session, nil
}

func scanAIDesignPlan(
	source scanner,
) (domain.AIDesignPlanRecord, error) {
	var record domain.AIDesignPlanRecord

	var planJSON string
	var createdAt string

	if err := source.Scan(
		&record.SessionID,
		&record.PlanID,
		&planJSON,
		&record.Selected,
		&createdAt,
	); err != nil {
		return domain.AIDesignPlanRecord{}, err
	}

	if err := json.Unmarshal(
		[]byte(planJSON),
		&record.Plan,
	); err != nil {
		return domain.AIDesignPlanRecord{},
			fmt.Errorf(
				"decode AI design plan: %w",
				err,
			)
	}

	var err error

	record.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.AIDesignPlanRecord{}, err
	}

	return record, nil
}

// MarkAISessionAssetsUsed 记录素材真的参与了某个阶段。
//
// used_in_stage / actually_used / usage_note 三列早就建好了，读取路径也在解析，
// 但从来没有任何代码写过它们 —— 每一行都恒为 actually_used=0，而 JSON 字段没有
// omitempty，等于对确实用过的素材主动断言"没用过"。
//
// stage 会追加进逗号分隔的集合里，重复调用幂等。
func (r *Repository) MarkAISessionAssetsUsed(
	ctx context.Context,
	sessionID string,
	assetIDs []string,
	stage string,
	note string,
) error {
	stage = strings.TrimSpace(stage)

	if stage == "" || len(assetIDs) == 0 {
		return nil
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf(
			"begin mark asset usage: %w",
			err,
		)
	}
	defer tx.Rollback()

	for _, assetID := range assetIDs {
		if strings.TrimSpace(assetID) == "" {
			continue
		}

		var existing sql.NullString

		err := tx.QueryRowContext(
			ctx,
			`
			SELECT used_in_stage
			FROM ai_session_assets
			WHERE session_id = ? AND asset_id = ?
			`,
			sessionID,
			assetID,
		).Scan(&existing)

		if errors.Is(err, sql.ErrNoRows) {
			// 素材没绑在这个会话上，跳过而不是报错：合成用的素材可能来自
			// 直接调用海报接口，根本没有会话。
			continue
		}

		if err != nil {
			return fmt.Errorf(
				"read asset usage stages: %w",
				err,
			)
		}

		if _, err := tx.ExecContext(
			ctx,
			`
			UPDATE ai_session_assets
			SET
				used_in_stage = ?,
				actually_used = 1,
				usage_note = ?
			WHERE session_id = ? AND asset_id = ?
			`,
			mergeUsageStages(existing.String, stage),
			strings.TrimSpace(note),
			sessionID,
			assetID,
		); err != nil {
			return fmt.Errorf(
				"mark asset usage: %w",
				err,
			)
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf(
			"commit asset usage: %w",
			err,
		)
	}

	return nil
}

// MarkAssetUsedAcrossSessions 按素材 ID 落使用证据，不需要知道会话。
//
// 参考图控制发生在生成阶段：那时候只有 job 和素材，海报可能还没建出来，会话也
// 可能压根不存在（直接调 /api/generate 或 /api/posters）。素材没绑在任何会话上
// 时静默跳过 —— 和 MarkAISessionAssetsUsed 一样，那不是错误。
func (r *Repository) MarkAssetUsedAcrossSessions(
	ctx context.Context,
	assetIDs []string,
	stage string,
	note string,
) error {
	stage = strings.TrimSpace(stage)

	if stage == "" || len(assetIDs) == 0 {
		return nil
	}

	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf(
			"begin mark asset usage: %w",
			err,
		)
	}
	defer tx.Rollback()

	for _, assetID := range assetIDs {
		if strings.TrimSpace(assetID) == "" {
			continue
		}

		rows, err := tx.QueryContext(
			ctx,
			`
			SELECT session_id, used_in_stage
			FROM ai_session_assets
			WHERE asset_id = ?
			`,
			assetID,
		)
		if err != nil {
			return fmt.Errorf(
				"read asset usage stages: %w",
				err,
			)
		}

		type binding struct {
			sessionID string
			stages    string
		}

		var bindings []binding

		for rows.Next() {
			var sessionID string
			var existing sql.NullString

			if err := rows.Scan(
				&sessionID,
				&existing,
			); err != nil {
				rows.Close()
				return fmt.Errorf(
					"scan asset usage stages: %w",
					err,
				)
			}

			bindings = append(bindings, binding{
				sessionID: sessionID,
				stages:    existing.String,
			})
		}

		if err := rows.Err(); err != nil {
			rows.Close()
			return fmt.Errorf(
				"iterate asset usage stages: %w",
				err,
			)
		}

		rows.Close()

		for _, item := range bindings {
			if _, err := tx.ExecContext(
				ctx,
				`
				UPDATE ai_session_assets
				SET
					used_in_stage = ?,
					actually_used = 1,
					usage_note = ?
				WHERE session_id = ? AND asset_id = ?
				`,
				mergeUsageStages(item.stages, stage),
				strings.TrimSpace(note),
				item.sessionID,
				assetID,
			); err != nil {
				return fmt.Errorf(
					"mark asset usage: %w",
					err,
				)
			}
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf(
			"commit asset usage: %w",
			err,
		)
	}

	return nil
}

// RecordComposedAssetUsage 由合成器的真实绘制结果驱动，按 poster_id 找到会话再
// 落证据。找不到会话就静默返回 —— 直接走海报接口的调用方没有会话。
func (r *Repository) RecordComposedAssetUsage(
	ctx context.Context,
	posterID string,
	assetIDs []string,
) error {
	if len(assetIDs) == 0 {
		return nil
	}

	var sessionID string

	err := r.db.QueryRowContext(
		ctx,
		`
		SELECT id
		FROM ai_sessions
		WHERE poster_id = ?
		ORDER BY updated_at DESC
		LIMIT 1
		`,
		posterID,
	).Scan(&sessionID)

	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}

	if err != nil {
		return fmt.Errorf(
			"find session for poster: %w",
			err,
		)
	}

	return r.MarkAISessionAssetsUsed(
		ctx,
		sessionID,
		assetIDs,
		domain.AISessionAssetStageLogoOverlay,
		"合成时画入最终海报",
	)
}

// mergeUsageStages 把新阶段并入已有的逗号分隔集合，保持顺序且不重复。
func mergeUsageStages(
	existing string,
	stage string,
) string {
	stages := make([]string, 0, 4)
	seen := map[string]bool{}

	for _, value := range strings.Split(existing, ",") {
		value = strings.TrimSpace(value)

		if value == "" || seen[value] {
			continue
		}

		seen[value] = true
		stages = append(stages, value)
	}

	if !seen[stage] {
		stages = append(stages, stage)
	}

	return strings.Join(stages, ",")
}
