package poster

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/vision"
)

// KeyVisualInspector 是视觉模型那一层的最小接口。
//
// 定成接口而不是直接依赖 internal/ai，是为了不让海报流程反向依赖 AI 包。
// 实现方负责先拿 GPU 许可（ai.Runtime.Acquire 会卸载 ComfyUI 模型）——
// 显存怎么调度不该是 poster 包知道的事。
//
// 一次调用检查多张图，而不是一张一张来：每次 Acquire 都会把 ComfyUI 踢出显存，
// 三张候选分三次拿许可就是三轮卸载/加载。
type KeyVisualInspector interface {
	InspectKeyVisuals(
		ctx context.Context,
		paths []string,
	) (map[string]domain.VisualInspection, error)
}

// WithKeyVisualInspector 注入视觉模型检查器。不注入时像素分析照常做，
// 只是 Texture / Style / HasGeneratedText 留空，Source 保持 pixels。
func (s *Service) WithKeyVisualInspector(
	inspector KeyVisualInspector,
) *Service {

	s.inspector = inspector
	return s
}

// 单次视觉检查的时间上限。
//
// 整个 reconcile tick 的预算是 90 秒（worker/poster_reconciler.go），三张图的
// 视觉检查必须留出余量给同一 tick 里的其他海报，所以这里自己设一个更小的闸。
const inspectionTimeout = 60 * time.Second

// analyzeKeyVisual 算出这张候选的像素级分析并入库。
//
// 纯 CPU，1024x1536 上单遍扫描约一百毫秒，所以直接跑在 reconcile tick 里。
// 失败不改变候选状态：一张图分析不出来不代表它不能用，前端拿不到 visualAnalysis
// 时会退回自己的默认版式。
func (s *Service) analyzeKeyVisual(
	ctx context.Context,
	candidateID string,
	imagePath string,
) error {

	analysis, err := vision.AnalyzeFile(imagePath)
	if err != nil {
		return fmt.Errorf(
			"analyze key visual %s: %w",
			candidateID,
			err,
		)
	}

	encoded, err := json.Marshal(analysis)
	if err != nil {
		return fmt.Errorf(
			"encode visual analysis %s: %w",
			candidateID,
			err,
		)
	}

	return s.repository.SaveCandidateVisualAnalysis(
		ctx,
		candidateID,
		string(encoded),
	)
}

// inspectReadyCandidates 在候选全部就绪、即将交给用户挑选之前，补齐两件事：
//
//  1. 缺失的像素分析（重启前生成的老候选、或者当时分析失败的）；
//  2. 视觉模型判断 —— 纹理、风格、以及**图里有没有伪文字**。
//
// 返回 true 表示有候选因为伪文字被打回重生成，调用方这一轮不要推进到
// awaiting_selection。
//
// 视觉模型不可用、超时、或者报错时一律返回 false 并继续放行。检查器坏了不该
// 把整条流水线卡死，而 Source 字段会如实停留在 pixels，前端因此知道"这张图
// 没查过伪文字"，不会把它误当成"查过且干净"。
func (s *Service) inspectReadyCandidates(
	ctx context.Context,
	posterRecord domain.PosterRecord,
	candidates []domain.CandidateRecord,
	goal domain.GoalContract,
) bool {

	paths := make(map[string]string, len(candidates))

	for _, candidate := range candidates {
		if candidate.Status !=
			domain.CandidateStatusReady {
			continue
		}

		output, err := s.repository.GetOutput(
			ctx,
			candidate.JobID,
			"poster",
		)
		if err != nil {
			log.Printf(
				"poster %s candidate %s: read output for inspection: %v",
				posterRecord.ID,
				candidate.ID,
				err,
			)

			continue
		}

		// 老候选可能还没算过像素分析，先补上。
		if candidate.VisualAnalysisJSON == "" {
			if err := s.analyzeKeyVisual(
				ctx,
				candidate.ID,
				output.StoragePath,
			); err != nil {
				log.Printf(
					"poster %s: %v",
					posterRecord.ID,
					err,
				)

				continue
			}
		}

		paths[candidate.ID] = output.StoragePath
	}

	if s.inspector == nil || len(paths) == 0 {
		return false
	}

	// 已经带过视觉模型结论的候选不必再问一遍 —— 它们的 Source 已经是
	// pixels+vlm，重问只是白烧一次 GPU。
	pending := make([]string, 0, len(paths))
	byPath := make(map[string]string, len(paths))

	for _, candidate := range candidates {
		path, ok := paths[candidate.ID]
		if !ok {
			continue
		}

		if inspected(candidate.VisualAnalysisJSON) {
			continue
		}

		pending = append(pending, path)
		byPath[path] = candidate.ID
	}

	if len(pending) == 0 {
		return false
	}

	inspectCtx, cancel := context.WithTimeout(
		ctx,
		inspectionTimeout,
	)
	defer cancel()

	results, err := s.inspector.InspectKeyVisuals(
		inspectCtx,
		pending,
	)
	if err != nil {
		log.Printf(
			"poster %s: key visual inspection unavailable, candidates stay pixel-only: %v",
			posterRecord.ID,
			err,
		)

		return false
	}

	retried := false

	for _, candidate := range candidates {
		path, ok := paths[candidate.ID]
		if !ok {
			continue
		}

		inspection, ok := results[path]
		if !ok {
			continue
		}

		analysis, err := decodeAnalysis(
			candidate.VisualAnalysisJSON,
		)
		if err != nil {
			log.Printf(
				"poster %s candidate %s: decode stored analysis: %v",
				posterRecord.ID,
				candidate.ID,
				err,
			)

			continue
		}

		analysis.Merge(inspection)

		encoded, err := json.Marshal(analysis)
		if err != nil {
			log.Printf(
				"poster %s candidate %s: encode merged analysis: %v",
				posterRecord.ID,
				candidate.ID,
				err,
			)

			continue
		}

		if err := s.repository.SaveCandidateVisualAnalysis(
			ctx,
			candidate.ID,
			string(encoded),
		); err != nil {
			log.Printf(
				"poster %s candidate %s: save merged analysis: %v",
				posterRecord.ID,
				candidate.ID,
				err,
			)

			continue
		}

		if !analysis.HasGeneratedText {
			continue
		}

		// 主视觉里出现了字。这张图不能用 —— 前端会在它上面再叠一层真文字，
		// 成图就是两套文字打架。换个种子重生成，次数由 goal.MaxAttempts 兜住，
		// 用完还带字就标记失败，不会无限循环。
		log.Printf(
			"poster %s candidate %s: pseudo-text detected %v, regenerating",
			posterRecord.ID,
			candidate.ID,
			analysis.GeneratedText,
		)

		if err := s.retryCandidate(
			ctx,
			posterRecord,
			candidate,
			goal,
			fmt.Sprintf(
				"generated key visual contains text: %v",
				analysis.GeneratedText,
			),
		); err != nil {
			log.Printf(
				"poster %s candidate %s: regenerate after pseudo-text: %v",
				posterRecord.ID,
				candidate.ID,
				err,
			)

			continue
		}

		retried = true
	}

	return retried
}

// inspected 判断这份存下来的分析是否已经带过视觉模型结论。
func inspected(analysisJSON string) bool {
	analysis, err := decodeAnalysis(analysisJSON)
	if err != nil {
		return false
	}

	return analysis.Source == domain.VisualSourcePixelsVLM
}

func decodeAnalysis(
	analysisJSON string,
) (domain.VisualAnalysis, error) {

	if analysisJSON == "" {
		return domain.VisualAnalysis{},
			fmt.Errorf("visual analysis is empty")
	}

	var analysis domain.VisualAnalysis

	if err := json.Unmarshal(
		[]byte(analysisJSON),
		&analysis,
	); err != nil {
		return domain.VisualAnalysis{}, err
	}

	return analysis, nil
}
