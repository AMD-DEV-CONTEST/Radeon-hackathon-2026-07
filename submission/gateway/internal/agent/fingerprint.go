// Package agent — machine fingerprint collection.
// Raw UUID and MAC are NEVER exposed outside this package.
package agent

import (
	"crypto/sha256"
	"fmt"
	"net"
	"sort"
	"strings"
)

// CollectMachineFingerprint reads machine UUID + primary MAC, computes
// SHA256(uuid+"\n"+mac), and returns only the hex hash.
func CollectMachineFingerprint() (string, error) {
	uuid, err := collectUUID()
	if err != nil {
		return "", fmt.Errorf("collect uuid: %w", err)
	}
	uuid = strings.TrimSpace(uuid)
	if uuid == "" {
		return "", fmt.Errorf("empty uuid")
	}

	mac, err := collectPrimaryMAC()
	if err != nil {
		return "", fmt.Errorf("collect mac: %w", err)
	}
	mac = strings.TrimSpace(mac)
	if mac == "" {
		return "", fmt.Errorf("empty mac")
	}

	raw := uuid + "\n" + mac
	hash := sha256.Sum256([]byte(raw))
	return fmt.Sprintf("%x", hash), nil
}

// collectPrimaryMAC 获取第一个非回环、非空的物理网卡 MAC 地址。
func collectPrimaryMAC() (string, error) {
	ifaces, err := net.Interfaces()
	if err != nil {
		return "", err
	}

	type ifaceMAC struct {
		name string
		mac  string
	}
	var candidates []ifaceMAC

	for _, iface := range ifaces {
		// 跳过回环
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		// 必须 up
		if iface.Flags&net.FlagUp == 0 {
			continue
		}
		mac := iface.HardwareAddr.String()
		if mac == "" {
			continue
		}
		candidates = append(candidates, ifaceMAC{name: iface.Name, mac: mac})
	}

	if len(candidates) == 0 {
		return "", fmt.Errorf("no non-loopback interface with MAC found")
	}

	// 按接口名排序，取第一个，保证确定性
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].name < candidates[j].name
	})

	return candidates[0].mac, nil
}
