package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// cmdUpdate performs a self-update: git pull → rebuild → daemon restart.
// Single command — agents run `ils update` and it's done.
func cmdUpdate() {
	binPath, err := os.Executable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "❌ 无法定位自身路径: %v\n", err)
		os.Exit(1)
	}
	binPath, _ = filepath.EvalSymlinks(binPath)

	// Repo root = dir of dir of bin/ (i.e. /root/unionagents-go)
	repoRoot := filepath.Dir(filepath.Dir(binPath))
	if _, err := os.Stat(filepath.Join(repoRoot, "go.mod")); err != nil {
		repoRoot = "."
	}

	fmt.Printf("📦 UAS CLI 自更新\n")
	fmt.Printf("   仓库: %s\n", repoRoot)

	// 1. git fetch + pull
	fmt.Println("\n➜ 拉取代码...")
	for _, cmd := range []struct{ name, arg string }{
		{"git", "fetch origin go-migration"},
		{"git", "checkout go-migration"},
		{"git", "pull origin go-migration"},
	} {
		c := exec.Command("bash", "-c", cmd.name+" "+cmd.arg)
		c.Dir = repoRoot
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		if err := c.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "❌ %s 失败: %v\n", cmd.arg, err)
			os.Exit(1)
		}
	}

	// 2. build binary
	fmt.Println("\n➜ 编译...")
	build := exec.Command("go", "build", "-o", binPath, "./cmd/ils")
	build.Dir = repoRoot
	build.Stdout = os.Stdout
	build.Stderr = os.Stderr
	if err := build.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "❌ 编译失败: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("   ✅ 二进制已更新: %s\n", binPath)

	// 3. restart daemon
	svcName := "unionagents-ils-daemon.service"
	fmt.Println("\n➜ 重启守护进程...")
	if err := exec.Command("systemctl", "restart", svcName).Run(); err != nil {
		// Try alternative names
		for _, alt := range []string{"uas-daemon.service", "ils-daemon.service"} {
			if e := exec.Command("systemctl", "restart", alt).Run(); e == nil {
				svcName = alt
				err = nil
				break
			}
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "⚠️ 未找到运行中的服务，请手动启动: ils daemon\n")
			return
		}
	}

	time.Sleep(2 * time.Second)
	out, _ := exec.Command("systemctl", "is-active", svcName).Output()
	if strings.TrimSpace(string(out)) != "active" {
		fmt.Printf("⚠️ %s 状态异常\n", svcName)
		os.Exit(1)
	}

	fmt.Printf("\n✅ UAS CLI 更新完成！%s 运行中\n", svcName)
	logs := exec.Command("journalctl", "-u", svcName, "--no-pager", "-n", "5")
	logs.Stdout = os.Stdout
	logs.Stderr = os.Stderr
	logs.Run()
}
