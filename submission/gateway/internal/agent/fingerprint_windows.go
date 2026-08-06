//go:build windows

package agent

import (
	"os/exec"
	"strings"
)

// collectUUID 通过 wmic csproduct get uuid 获取 Windows 机器 UUID。
func collectUUID() (string, error) {
	// wmic csproduct get uuid 输出格式:
	// UUID
	// 4C4C4544-0051-4D10-8051-C8C04F325831
	// (首行是列头，第二行是值)
	cmd := exec.Command("wmic", "csproduct", "get", "uuid")
	out, err := cmd.Output()
	if err != nil {
		return "", err
	}

	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		// 跳过列头 "UUID" 和空行
		if line == "" || strings.EqualFold(line, "UUID") {
			continue
		}
		return line, nil
	}

	return "", nil
}
