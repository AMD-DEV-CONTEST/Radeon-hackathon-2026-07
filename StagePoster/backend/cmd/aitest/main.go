package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/ai"
	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func main() {
	client := ai.NewClient(
		env(
			"VLM_URL",
			"http://127.0.0.1:8001",
		),
		env(
			"VLM_API_KEY",
			"stageposter-vlm-local",
		),
		env(
			"VLM_MODEL",
			"stageposter-vlm",
		),
		3*time.Minute,
	)

	service := ai.NewService(client)

	ctx, cancel := context.WithTimeout(
		context.Background(),
		5*time.Minute,
	)
	defer cancel()

	if err := service.Health(ctx); err != nil {
		log.Fatalf(
			"VLM health failed: %v",
			err,
		)
	}

	event := domain.EventBrief{
		Title:        "Abyssal Kingdom Festival",
		Artist:       "Maverick",
		Date:         "2026-08-21",
		Time:         "20:00",
		Venue:        "Void Arena",
		PresalePrice: "$45",
		DoorPrice:    "$60",
	}

	visual := domain.VisualBrief{
		Style:      "dark fantasy editorial",
		Theme:      "abyssal gothic kingdom",
		MusicGenre: "gothic metal",
		Mood: []string{
			"epic",
			"mysterious",
			"ritualistic",
		},
		PreferredColors: []string{
			"black",
			"aged ivory",
			"deep red",
		},
	}

	plans, metrics, err := service.Plan(
		ctx,
		event,
		visual,
		"黑色王座、巨大羽翼、哥特王国，高级、有压迫感，禁止生成文字。",
	)
	if err != nil {
		log.Fatalf(
			"design planning failed: %v",
			err,
		)
	}

	fmt.Printf(
		"\nDESIGN latency=%s promptTokens=%d completionTokens=%d\n",
		metrics.Latency,
		metrics.PromptTokens,
		metrics.CompletionTokens,
	)

	printJSON(plans)

	reviewImage := strings.TrimSpace(
		os.Getenv("REVIEW_IMAGE"),
	)

	if reviewImage == "" {
		fmt.Println(
			"\nREVIEW_IMAGE not set; skipping visual review",
		)
		return
	}

	review, reviewMetrics, err := service.Review(
		ctx,
		reviewImage,
		event,
		visual,
		&plans.Plans[0],
	)
	if err != nil {
		log.Fatalf(
			"visual review failed: %v",
			err,
		)
	}

	fmt.Printf(
		"\nREVIEW latency=%s promptTokens=%d completionTokens=%d\n",
		reviewMetrics.Latency,
		reviewMetrics.PromptTokens,
		reviewMetrics.CompletionTokens,
	)

	printJSON(review)
}

func printJSON(
	value any,
) {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")

	if err := encoder.Encode(value); err != nil {
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
