//go:build linux

package agent

import (
	"os"
	"strings"
)

// collectUUID 读取 /sys/class/dmi/id/product_uuid。
func collectUUID() (string, error) {
	data, err := os.ReadFile("/sys/class/dmi/id/product_uuid")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(data)), nil
}
