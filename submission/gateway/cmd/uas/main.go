// uas — UnionAgents System 运维工具集
//
//	uas fingerprint       采集设备指纹 → SHA256 hex
//	uas boundary status   查询 UAS 边界清单
package main

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/konspace/unionagents-go/internal/agent"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	switch os.Args[1] {
	case "fingerprint":
		cmdFingerprint()
	case "boundary":
		cmdBoundary(os.Args[2:])
	case "help", "-h", "--help":
		printUsage()
	default:
		fmt.Fprintf(os.Stderr, "未知命令: %s\n", os.Args[1])
		printUsage()
		os.Exit(1)
	}
}

func printUsage() {
	bin := filepath.Base(os.Args[0])
	fmt.Printf(`uas — UnionAgents System 运维工具

用法:
  %[1]s fingerprint [--json]   采集设备指纹（UUID + MAC → SHA256 hex）
  %[1]s boundary status        查询 JD-ECS / OB / CLI 边界清单

说明:
  Linux:  读取 /sys/class/dmi/id/product_uuid + 网卡 MAC
  Windows: wmic csproduct get uuid + 网卡 MAC
  输出:   {"uuid":"...","mac":"...","sha256":"<64-char-hex>"}
  边界:   Lark CLI / 飞书云平台仅作为外部参考，不进入 UAS 通信链路
`, bin)
}

func cmdFingerprint() {
	fp, err := agent.CollectMachineFingerprint()
	if err != nil {
		fmt.Fprintln(os.Stderr, err.Error())
		os.Exit(1)
	}
	fmt.Println(fp)
}
