package service

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"runtime"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/ai"
)

// HealthInfo holds system health information.
type HealthInfo struct {
	Status string `json:"status"`

	GPU     *GPUInfo     `json:"gpu,omitempty"`
	ComfyUI *ComfyUIInfo `json:"comfyui,omitempty"`
	VLM     *VLMInfo     `json:"vlm,omitempty"`
	Runtime *RuntimeInfo `json:"runtime,omitempty"`

	TokenRequired bool `json:"tokenRequired"`
}

type GPUInfo struct {
	Model       string  `json:"model,omitempty"`
	VRAMTotalGB float64 `json:"vramTotalGB,omitempty"`
	VRAMUsedGB  float64 `json:"vramUsedGB,omitempty"`
	ROCMVersion string  `json:"rocmVersion,omitempty"`
	GFXArch     string  `json:"gfxArch,omitempty"`
	Utilization float64 `json:"utilizationPercent,omitempty"`
}

type ComfyUIInfo struct {
	Status          string `json:"status"`
	Model           string `json:"model,omitempty"`
	Precision       string `json:"precision,omitempty"`
	WorkflowVersion string `json:"workflowVersion,omitempty"`
}

type VLMInfo struct {
	Status      string  `json:"status,omitempty"`
	Model       string  `json:"model,omitempty"`
	DType       string  `json:"dtype,omitempty"`
	Sleeping    bool    `json:"sleeping,omitempty"`
	ColdStartMS int64   `json:"coldStartMs,omitempty"`
	InferenceMS int64   `json:"inferenceMs,omitempty"`
	PeakVRAMGB  float64 `json:"peakVramGB,omitempty"`
	URL         string  `json:"url,omitempty"`
}

type RuntimeInfo struct {
	GoVersion    string `json:"goVersion"`
	ComfyVersion string `json:"comfyVersion,omitempty"`
	VLLMVersion  string `json:"vllmVersion,omitempty"`
}

// HealthCollector collects system health information.
type HealthCollector struct {
	comfyURL        string
	vlmClient       *ai.Client
	vlmModel        string
	vlmSleeping     func(context.Context) (bool, error)
	workflowVersion string
}

func NewHealthCollector(
	comfyURL string,
	vlmClient *ai.Client,
	vlmModel string,
	vlmSleeping func(context.Context) (bool, error),
	workflowVersion string,
) *HealthCollector {
	return &HealthCollector{
		comfyURL:        comfyURL,
		vlmClient:       vlmClient,
		vlmModel:        vlmModel,
		vlmSleeping:     vlmSleeping,
		workflowVersion: workflowVersion,
	}
}

func (h *HealthCollector) Collect(ctx context.Context) HealthInfo {
	info := HealthInfo{
		Status:        "ok",
		TokenRequired: false,
	}

	// Collect GPU info from ComfyUI system_stats
	info.GPU = h.collectGPUInfo(ctx)

	// Collect ComfyUI info
	info.ComfyUI = h.collectComfyUIInfo(ctx)

	// Collect VLM info
	info.VLM = h.collectVLMInfo(ctx)

	// Collect runtime info
	info.Runtime = &RuntimeInfo{
		GoVersion: runtime.Version(),
	}

	// Determine overall status
	if info.GPU == nil || info.ComfyUI == nil || info.VLM == nil {
		info.Status = "degraded"
	}

	return info
}

func (h *HealthCollector) collectGPUInfo(ctx context.Context) *GPUInfo {
	if h.comfyURL == "" {
		return nil
	}

	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		h.comfyURL+"/system_stats",
		nil,
	)
	if err != nil {
		return nil
	}

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 1024*1024))
	if err != nil {
		return nil
	}

	var stats struct {
		System struct {
			RAM struct {
				Total float64 `json:"total"`
				Used  float64 `json:"used"`
			} `json:"ram"`
		} `json:"system"`
		Devices []struct {
			Name      string  `json:"name"`
			Type      string  `json:"type"`
			VRAMTotal float64 `json:"vram_total"`
			VRAMFree  float64 `json:"vram_free"`
		} `json:"devices"`
	}

	if err := json.Unmarshal(body, &stats); err != nil {
		return nil
	}

	for _, device := range stats.Devices {
		// ComfyUI reports AMD GPUs as type "cuda" on ROCm
		if device.Type == "GPU" || device.Type == "cuda" {
			return &GPUInfo{
				Model:       device.Name,
				VRAMTotalGB: device.VRAMTotal / (1024 * 1024 * 1024),
				VRAMUsedGB:  (device.VRAMTotal - device.VRAMFree) / (1024 * 1024 * 1024),
			}
		}
	}

	return nil
}

func (h *HealthCollector) collectComfyUIInfo(ctx context.Context) *ComfyUIInfo {
	if h.comfyURL == "" {
		return &ComfyUIInfo{Status: "disabled"}
	}

	// ComfyUI is reachable if we got here (Health check passed)
	return &ComfyUIInfo{
		Status:          "ready",
		WorkflowVersion: h.workflowVersion,
	}
}

func (h *HealthCollector) collectVLMInfo(ctx context.Context) *VLMInfo {
	if h.vlmClient == nil {
		return &VLMInfo{Status: "disabled"}
	}

	info := &VLMInfo{
		Model: h.vlmModel,
	}

	if err := h.vlmClient.Health(ctx); err != nil {
		info.Status = "unavailable"
		return info
	}

	info.Status = "ready"

	if h.vlmSleeping != nil {
		sleeping, err := h.vlmSleeping(ctx)
		if err == nil {
			info.Sleeping = sleeping
		}
	}

	return info
}

// detectROCMVersion detects the ROCm version from the system.
// This is a placeholder - integrate with actual ROCm detection in production.
func detectROCMVersion() string {
	return "7.2.1"
}

// detectGFXArch detects the GPU architecture.
// This is a placeholder - integrate with actual GPU detection in production.
func detectGFXArch() string {
	return "gfx1100"
}
