package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/konspace/unionagents-go/internal/ironlaw"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	switch os.Args[1] {
	case "daemon":
		daemonRun()
	case "start":
		daemonRun()
	case "event":
		cmdEvent(os.Args[2:])
	case "chat":
		cmdChat(os.Args[2:])
	case "inbox":
		cmdInbox(os.Args[2:])
	case "doctor":
		cmdDoctor(os.Args[2:])
	case "audit":
		cmdAudit(os.Args[2:])
	case "gateway":
		cmdGateway(os.Args[2:])
	case "agent":
		cmdAgent(os.Args[2:])
	case "pr":
		cmdPr(os.Args[2:])
	case "profile":
		if err := runProfileCmd(os.Args[2:], os.Stdout, os.Stderr); err != nil {
			fmt.Fprintf(os.Stderr, "profile: %v\n", err)
			os.Exit(1)
		}
	case "local":
		if len(os.Args) > 2 && os.Args[2] == "daemon" {
			cmdLocalDaemon(os.Args[3:])
		} else {
			fmt.Fprintf(os.Stderr, "用法: %s local daemon --profiles x1,c1,z1\n", os.Args[0])
			os.Exit(1)
		}
	case "boundary":
		cmdBoundary(os.Args[2:])
	case "ws":
		cmdWS(os.Args[2:])
	case "bridge":
		if len(os.Args) > 2 && os.Args[2] == "listen" {
			cmdBridgeListen(os.Args[3:])
		} else if len(os.Args) > 2 && os.Args[2] == "auto" {
			cmdBridgeAuto(os.Args[3:])
		} else if len(os.Args) > 2 && os.Args[2] == "runtime" {
			cmdBridgeRuntime(os.Args[3:])
		} else {
			ilsBridgeRun()
		}
	case "check":
		cmdCheck()
	case "embed":
		cmdEmbed()
	case "update":
		cmdUpdate()
	case "version":
		cmdVersion()
	case "help":
		printUsage()
	default:
		fmt.Fprintf(os.Stderr, "未知命令: %s\n", os.Args[1])
		printUsage()
		os.Exit(1)
	}
}

func printUsage() {
	bin := filepath.Base(os.Args[0])
	fmt.Printf(`%s — UnionAgents Iron Law System v`+ironlaw.Version+`

用法:
  %[1]s daemon                   启动持久 worker 守护进程（Gateway WSS 事件驱动）
  %[1]s event consume chat       消费 UAS chat 事件（stdout NDJSON）
  %[1]s chat send                发送 chat 消息并输出 Gateway 真实投递字段
	  %[1]s inbox watch              监听指定逻辑 agent_id 的入站 chat 消息
	  %[1]s inbox read <profile> [--lines N] [--all]   读本地 inbox(默认最后 50 行)
	  %[1]s inbox tail <profile> [--lines N] [--follow]  尾读本地 inbox(--follow 阻塞)
	  %[1]s profile list|set|get|rm   管理 local agent profiles
	  %[1]s local daemon --profiles x1,c1,z1   多 profile client-mode inbox daemon
	  %[1]s chat send --from-profile <name> --target-agent-id <id> --text "..."  (--from-agent-id 仍优先)
  %[1]s doctor                   检查 Gateway health、事件状态、WS ready
  %[1]s audit verify             校验 cron_events 审计轨迹（task_id 完整性/无重复触发）
  %[1]s gateway status           查询 Gateway health、事件和 ready 状态
  %[1]s agent status             查询 Agent 注册/在线状态
  %[1]s pr merge <number>        Enforce C1 final-verdict gates before gh pr merge
  %[1]s boundary status          查询 UAS 边界清单（Lark/飞书仅外部参考，不进入链路）
  %[1]s bridge                   启动 Cockpit HTTP 桥（补全 ILS 字段 → 编排器）
  %[1]s bridge listen --dir <dir> 阻塞读取桥目录的 inbox socket（UAS bridge pipe）
  %[1]s bridge auto --dir <dir>   自动桥模式：收 inbox 消息 → 自动回 outbox（压测/演示用）
  %[1]s bridge runtime --dir <dir> --cmd "<sh>"  真 AI 模式：管道 stdin 调用 CLI，stdout 当回复
  %[1]s ws                       启动 UAS WS ←→ stdio 双向中继（pipe 给任意 Agent）
  %[1]s start                    启动 daemon（alias）
  %[1]s check <task.json>        验证任务是否符合铁律
  %[1]s embed                    输出 AGENTS.md 内容（嵌入系统提示）
  %[1]s update                   自更新：git pull → 编译 → 重启守护进程
  %[1]s version                  输出版本号

daemon 环境变量:
  ORCHESTRATOR_URL  编排器地址（默认 https://api.upser.pro）
  GATEWAY_URL       Gateway WS 地址（默认 wss://api.upser.pro）
  GATEWAY_PASSWORD  Gateway 登录密码
  AGENT_ID          Agent ID（空则自动注册）
  AGENT_NAME        Agent 显示名（默认 hostname-ils）
  ILS_BRIDGE_DIR    桥模式目录（设此值后 daemon 不 spawn 子进程，写 inbox.ndjson + inbox.sock）
                    用 'ils bridge listen --dir <dir>' 阻塞读 inbox（UAS bridge pipe）

示例:
  GATEWAY_PASSWORD=*** %[1]s daemon
  %[1]s event consume chat --max-events 1 --timeout 30s
  %[1]s chat send --target-agent-id <id> --text "ping"
  %[1]s inbox watch --agent-id x1 --format text
  %[1]s doctor --gateway-url ws://127.0.0.1:8001
  echo '{"title":"修复登录","task_type":"coding"}' | %[1]s check -
  %[1]s check task.json
  %[1]s embed >> ~/.claude/CLAUDE.md
  %[1]s update
`, bin)
}

func cmdVersion() {
	fmt.Println(ironlaw.Version)
}

func cmdEmbed() {
	fmt.Print(ironlaw.AGENTS_MD)
}

func cmdCheck() {
	var raw string
	if len(os.Args) < 3 || os.Args[2] == "-" {
		var buf strings.Builder
		b := make([]byte, 4096)
		for {
			n, err := os.Stdin.Read(b)
			if n > 0 {
				buf.Write(b[:n])
			}
			if err != nil {
				break
			}
		}
		raw = buf.String()
	} else {
		data, err := os.ReadFile(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "读取文件失败: %v\n", err)
			os.Exit(1)
		}
		raw = string(data)
	}

	raw = strings.TrimSpace(raw)
	if raw == "" {
		fmt.Println(`{"status":"skip","reason":"empty input"}`)
		return
	}

	task, err := ironlaw.ParseTask(raw)
	if err != nil {
		fmt.Fprintf(os.Stderr, `{"status":"error","error":"invalid JSON: %v"}`+"\n", err)
		os.Exit(1)
	}

	warnings, err := ironlaw.ValidateTaskBeforeDispatch(task)

	result := map[string]interface{}{
		"status":   "pass",
		"warnings": warnings,
	}

	if err != nil {
		if v, ok := err.(*ironlaw.RuleViolation); ok {
			result["status"] = "fail"
			result["rule"] = v.Rule
			result["message"] = v.Message
			result["auto_fixable"] = v.AutoFixable
		} else {
			result["status"] = "error"
			result["error"] = err.Error()
		}
	}

	out, _ := json.Marshal(result)
	fmt.Println(string(out))

	if err != nil {
		os.Exit(2)
	}
}
