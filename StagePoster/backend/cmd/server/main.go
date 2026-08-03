package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/api"
	"github.com/Ripped-sys/StagePoster/backend/internal/assistant"
	"github.com/Ripped-sys/StagePoster/backend/internal/comfy"
	"github.com/Ripped-sys/StagePoster/backend/internal/composer"
	posterflow "github.com/Ripped-sys/StagePoster/backend/internal/poster"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	"github.com/Ripped-sys/StagePoster/backend/internal/service"
	"github.com/Ripped-sys/StagePoster/backend/internal/storage"
	"github.com/Ripped-sys/StagePoster/backend/internal/worker"
)

func main() {
	listenAddr := env(
		"LISTEN_ADDR",
		":8080",
	)

	comfyURL := env(
		"COMFY_URL",
		"http://127.0.0.1:8188",
	)

	workflowPath := env(
		"WORKFLOW_PATH",
		"/workspace/poster-engine/workflows/z_image_poster_v1.json",
	)

	databasePath := env(
		"DB_PATH",
		"/workspace/persistence/stageposter/data/poster.db",
	)

	storageRoot := env(
		"STORAGE_ROOT",
		"/workspace/persistence/stageposter/storage/jobs",
	)

	assetStorageRoot := env(
		"ASSET_STORAGE_ROOT",
		"/workspace/persistence/stageposter/storage/assets",
	)

	posterOutputRoot := env(
		"POSTER_OUTPUT_ROOT",
		"/workspace/persistence/stageposter/storage/posters",
	)

	workflowKey := env(
		"WORKFLOW_KEY",
		"poster-text",
	)

	workflowVersion := env(
		"WORKFLOW_VERSION",
		"1.0.0",
	)

	reconcileInterval := envDuration(
		"RECONCILE_INTERVAL",
		2*time.Second,
	)

	startupContext, startupCancel :=
		context.WithTimeout(
			context.Background(),
			20*time.Second,
		)
	defer startupCancel()

	repositoryInstance, err := repository.OpenSQLite(
		startupContext,
		databasePath,
	)
	if err != nil {
		log.Fatalf(
			"open repository: %v",
			err,
		)
	}
	defer repositoryInstance.Close()

	fileStore, err := storage.NewFileStore(
		storageRoot,
	)
	if err != nil {
		log.Fatalf(
			"open file storage: %v",
			err,
		)
	}

	assetStore, err := storage.NewAssetStore(
		assetStorageRoot,
		20<<20,
	)
	if err != nil {
		log.Fatalf(
			"open asset storage: %v",
			err,
		)
	}

	template, err := comfy.LoadTemplate(
		workflowPath,
		os.Getenv("PROMPT_NODE_ID"),
		os.Getenv("NEGATIVE_PROMPT_NODE_ID"),
		os.Getenv("SEED_NODE_ID"),
		envFloat("COMFY_CFG", 0),
	)
	if err != nil {
		log.Fatalf(
			"load workflow template: %v",
			err,
		)
	}

	// 参考图控制需要一份 Z-Image ControlNet 权重放在
	// ComfyUI/models/model_patches 下。没配就退回到"参考图只影响需求理解"，
	// 并在启动日志和 capabilities 里如实说明。
	template = template.WithReferencePatch(
		os.Getenv("REFERENCE_CONTROL_PATCH"),
	)

	if template.ReferenceControlAvailable() {
		log.Printf(
			"reference image conditioning active: patch=%s",
			template.ReferencePatch(),
		)
	} else {
		log.Printf(
			"reference image conditioning unavailable " +
				"(set REFERENCE_CONTROL_PATCH to a file in " +
				"ComfyUI/models/model_patches); reference images " +
				"will only affect brief understanding",
		)
	}

	// 负向提示词一直被算出来、存进库、在 API 里返回，但工作流没有负向文本节点
	// 且 cfg == 1，提交给 ComfyUI 的图其实完全没受影响。静默失效比报错更难查，
	// 所以启动时把实际状态打出来。
	if !template.NegativePromptEffective() {
		log.Printf(
			"warning: negative prompts have no effect "+
				"(negative binding=%v, cfg=%.2f); "+
				"need a negative text node and cfg > 1",
			template.Bindings().NegativePrompt != nil,
			template.EffectiveCFG(),
		)
	} else {
		log.Printf(
			"negative prompt active: node=%s cfg=%.2f",
			template.Bindings().NegativePrompt.NodeID,
			template.EffectiveCFG(),
		)
	}

	comfyClient := comfy.NewClient(
		comfyURL,
	)

	posterService := service.NewPosterService(
		comfyClient,
		template,
		repositoryInstance,
		fileStore,
		workflowKey,
		workflowVersion,
	)

	assetService := service.NewAssetService(
		repositoryInstance,
		assetStore,
	)

	assetProcessor := service.NewAssetProcessor(
		repositoryInstance,
		2,
	)

	posterComposer, err := composer.New(
		posterOutputRoot,
		os.Getenv("POSTER_FONT_REGULAR"),
		os.Getenv("POSTER_FONT_BOLD"),
	)
	if err != nil {
		log.Fatalf(
			"open poster composer: %v",
			err,
		)
	}

	candidatePlanner := posterflow.NewPlanner()
	candidateEvaluator := posterflow.NewEvaluator()

	posterFlow := posterflow.NewService(
		repositoryInstance,
		posterService,
		candidatePlanner,
		candidateEvaluator,
		posterComposer,
	)

	// AIConfig 原子地持有 Client、Service、Runtime、
	// VLM URL 和模型名称，避免出现半配置状态。
	aiConfig := api.NewAIConfigFromEnv()

	// Qwen 唤醒前先卸载 ComfyUI 模型，避免单卡显存争用。
	aiConfig.Runtime.SetBeforeAcquire(
		posterService.ReleaseComfyMemory,
	)

	aiSessionService := assistant.NewService(
		repositoryInstance,
		aiConfig.Service,
		aiConfig.Runtime,
		posterFlow,
	)

	apiServer := api.NewServer(
		posterService,
		assetService,
		posterFlow,
		os.Getenv("POSTER_API_TOKEN"),
		env("CORS_ORIGIN", "*"),
	).WithAI(
		aiConfig,
	).WithAISessions(
		aiSessionService,
	).WithAssetProcessor(
		assetProcessor,
	).WithHealthCollector(
		service.NewHealthCollector(
			comfyURL,
			aiConfig.Client,
			aiConfig.Model,
			aiConfig.Client.IsSleeping,
			workflowVersion,
		),
	)

	server := &http.Server{
		Addr:              listenAddr,
		Handler:           apiServer.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       90 * time.Second,
		WriteTimeout:      8 * time.Minute,
		IdleTimeout:       120 * time.Second,
	}

	runContext, stop := signal.NotifyContext(
		context.Background(),
		os.Interrupt,
		syscall.SIGTERM,
	)
	defer stop()

	reconciler := worker.NewReconciler(
		posterService,
		reconcileInterval,
		log.Default(),
	)

	posterReconciler := worker.NewPosterReconciler(
		posterFlow,
		reconcileInterval,
		log.Default(),
	)

	go reconciler.Run(runContext)
	go posterReconciler.Run(runContext)

	go func() {
		<-runContext.Done()

		shutdownContext, cancel :=
			context.WithTimeout(
				context.Background(),
				15*time.Second,
			)
		defer cancel()

		_ = server.Shutdown(
			shutdownContext,
		)

		assetShutdownCtx, assetCancel :=
			context.WithTimeout(
				context.Background(),
				5*time.Second,
			)
		defer assetCancel()
		_ = assetProcessor.Shutdown(assetShutdownCtx)
	}()

	log.Printf(
		"Poster backend listening on %s",
		listenAddr,
	)

	log.Printf(
		"ComfyUI URL: %s",
		comfyURL,
	)

	log.Printf(
		"VLM URL: %s",
		aiConfig.URL,
	)

	log.Printf(
		"VLM model: %s",
		aiConfig.Model,
	)

	log.Printf(
		"Workflow: %s",
		workflowPath,
	)

	log.Printf(
		"Workflow identity: %s@%s",
		workflowKey,
		workflowVersion,
	)

	log.Printf(
		"Database: %s",
		databasePath,
	)

	log.Printf(
		"Storage: %s",
		storageRoot,
	)

	log.Printf(
		"Asset storage: %s",
		assetStorageRoot,
	)

	log.Printf(
		"Poster outputs: %s",
		posterOutputRoot,
	)

	log.Printf(
		"Bindings: %+v",
		template.Bindings(),
	)

	if err := server.ListenAndServe(); err != nil &&
		!errors.Is(
			err,
			http.ErrServerClosed,
		) {
		log.Fatal(err)
	}
}

func env(
	key string,
	fallback string,
) string {
	value := strings.TrimSpace(
		os.Getenv(key),
	)

	if value == "" {
		return fallback
	}

	return value
}

func envFloat(
	key string,
	fallback float64,
) float64 {
	value := strings.TrimSpace(
		os.Getenv(key),
	)

	if value == "" {
		return fallback
	}

	parsed, err := strconv.ParseFloat(value, 64)
	if err != nil {
		log.Printf(
			"invalid float %s=%q, using %v",
			key,
			value,
			fallback,
		)

		return fallback
	}

	return parsed
}

func envDuration(
	key string,
	fallback time.Duration,
) time.Duration {
	value := strings.TrimSpace(
		os.Getenv(key),
	)

	if value == "" {
		return fallback
	}

	parsed, err := time.ParseDuration(value)
	if err != nil {
		log.Printf(
			"invalid duration %s=%q, using %s",
			key,
			value,
			fallback,
		)

		return fallback
	}

	return parsed
}
