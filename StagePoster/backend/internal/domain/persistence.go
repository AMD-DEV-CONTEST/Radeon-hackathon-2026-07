package domain

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"time"
)

type JobStatus string

const (
	JobStatusQueued    JobStatus = "queued"
	JobStatusRunning   JobStatus = "running"
	JobStatusSucceeded JobStatus = "succeeded"
	JobStatusFailed    JobStatus = "failed"
	JobStatusCanceled  JobStatus = "canceled"
)

type Job struct {
	ID              string     `json:"jobId"`
	ComfyPromptID   string     `json:"-"`
	WorkflowKey     string     `json:"workflowKey"`
	WorkflowVersion string     `json:"workflowVersion"`
	Prompt          string     `json:"prompt"`
	NegativePrompt  string     `json:"negativePrompt,omitempty"`
	Seed            int64      `json:"seed"`
	Status          JobStatus  `json:"status"`
	RequestJSON     string     `json:"-"`
	ErrorMessage    string     `json:"error,omitempty"`
	CreatedAt       time.Time  `json:"createdAt"`
	StartedAt       *time.Time `json:"startedAt,omitempty"`
	CompletedAt     *time.Time `json:"completedAt,omitempty"`
	UpdatedAt       time.Time  `json:"updatedAt"`
}

type Output struct {
	ID          string    `json:"id"`
	JobID       string    `json:"jobId"`
	Kind        string    `json:"kind"`
	Filename    string    `json:"filename"`
	MimeType    string    `json:"mimeType"`
	StoragePath string    `json:"-"`
	Width       int       `json:"width,omitempty"`
	Height      int       `json:"height,omitempty"`
	CreatedAt   time.Time `json:"createdAt"`
}

func NewID(prefix string) (string, error) {
	var value [16]byte

	if _, err := rand.Read(value[:]); err != nil {
		return "", fmt.Errorf("generate random id: %w", err)
	}

	// UUID v4 bits.
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80

	id := fmt.Sprintf(
		"%s%s-%s-%s-%s-%s",
		prefix,
		hex.EncodeToString(value[0:4]),
		hex.EncodeToString(value[4:6]),
		hex.EncodeToString(value[6:8]),
		hex.EncodeToString(value[8:10]),
		hex.EncodeToString(value[10:16]),
	)

	return id, nil
}
