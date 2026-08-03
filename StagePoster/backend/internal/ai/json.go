package ai

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

func DecodeJSONObject(
	raw string,
	output any,
) error {
	object, err := extractJSONObject(raw)
	if err != nil {
		return err
	}

	if err := json.Unmarshal(
		[]byte(object),
		output,
	); err != nil {
		return fmt.Errorf(
			"unmarshal JSON object: %w",
			err,
		)
	}

	return nil
}

func extractJSONObject(
	raw string,
) (string, error) {
	raw = strings.TrimSpace(raw)
	raw = strings.TrimPrefix(raw, "```json")
	raw = strings.TrimPrefix(raw, "```")
	raw = strings.TrimSuffix(raw, "```")
	raw = strings.TrimSpace(raw)

	start := strings.IndexByte(raw, '{')
	if start < 0 {
		return "", errors.New(
			"response contains no JSON object",
		)
	}

	depth := 0
	inString := false
	escaped := false

	for index := start; index < len(raw); index++ {
		current := raw[index]

		if inString {
			if escaped {
				escaped = false
				continue
			}

			switch current {
			case '\\':
				escaped = true
			case '"':
				inString = false
			}

			continue
		}

		switch current {
		case '"':
			inString = true

		case '{':
			depth++

		case '}':
			depth--

			if depth == 0 {
				return raw[start : index+1], nil
			}
		}
	}

	return "", errors.New(
		"response contains an unterminated JSON object",
	)
}
