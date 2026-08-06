package main

import (
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
)

var (
	httpClient = &http.Client{Timeout: 10 * time.Second}
)

func httpNewRequest(method, url string, body io.Reader) (*http.Request, error) {
	return http.NewRequest(method, url, body)
}

func stringsNewReader(s string) io.Reader {
	return strings.NewReader(s)
}

// Config
var (
	agentID  = envDefault("AGENT_ID", "d322357a-3e2c-42a2-92ac-408e6c7e30a6")
	agentName = envDefault("AGENT_NAME", "hermes")
	gwHTTP   = envDefault("GATEWAY_URL", "https://api.upser.pro")
	gwWS     = envDefault("GATEWAY_WS_URL", "wss://api.upser.pro")
	username = envDefault("GATEWAY_USERNAME", "admin")
	password = os.Getenv("GATEWAY_PASSWORD")

	inboxFile  = fmt.Sprintf("/tmp/uascli_%s_in.json", agentName)
	outboxFile = fmt.Sprintf("/tmp/uascli_%s_out.json", agentName)

	echoMode bool
)

var dialer = &websocket.Dialer{
	TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	HandshakeTimeout: 10 * time.Second,
}

func envDefault(k, d string) string {
	if v := os.Getenv(k); v != "" { return v }
	return d
}

func main() {
	flag.BoolVar(&echoMode, "echo", false, "Echo mode")
	flag.Parse()

	if password == "" {
		log.Fatal("GATEWAY_PASSWORD not set")
	}

	log.Printf("Hermes Bridge: %s (echo=%v)", agentID, echoMode)

	// Login to Gateway
	token := login()

	wsURL := fmt.Sprintf("%s/agents/%s/output?token=%s", gwWS, agentID, token)

	// Clean up
	os.Remove(inboxFile)
	os.Remove(outboxFile)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)

	for {
		select {
		case <-sig:
			log.Println("bye")
			return
		default:
		}

		conn, _, err := dialer.Dial(wsURL, nil)
		if err != nil {
			log.Printf("dial: %v, retry 5s", err)
			time.Sleep(5 * time.Second)
			continue
		}
		log.Printf("connected: %s", agentID)

		done := make(chan struct{})
		go readLoop(conn, done)
		go pingLoop(conn, done)
		if !echoMode {
			go outboxLoop(conn, done)
		}

		<-done
		conn.Close()
		log.Println("disconnected, retry 3s")
		time.Sleep(3 * time.Second)
	}
}

func login() string {
	body := fmt.Sprintf(`{"username":"%s","password":"%s"}`, username, password)
	token := httpPost(gwHTTP+"/auth/login", body)
	var r map[string]string
	json.Unmarshal([]byte(token), &r)
	if r["token"] == "" {
		log.Fatalf("login failed: %s", token)
	}
	log.Printf("logged in")
	return r["token"]
}

func httpPost(url, body string) string {
	req, _ := httpNewRequest("POST", url, stringsNewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := httpClient.Do(req)
	if err != nil {
		log.Fatalf("http: %v", err)
	}
	defer resp.Body.Close()
	buf := make([]byte, 4096)
	n, _ := resp.Body.Read(buf)
	return string(buf[:n])
}

// ── Read loop ──────────────────────────────────
func readLoop(conn *websocket.Conn, done chan struct{}) {
	defer close(done)

	conn.SetReadDeadline(time.Now().Add(120 * time.Second))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(120 * time.Second))
		return nil
	})

	for {
		_, raw, err := conn.ReadMessage()
		if err != nil {
			return
		}

		var msg map[string]interface{}
		if json.Unmarshal(raw, &msg) != nil { continue }

		t, _ := msg["type"].(string)
		if t != "chat:receive" { continue }

		from, _ := msg["from"].(string)
		content, _ := msg["content"].(string)
		log.Printf("[IN] %s: %s", from, content)

		if echoMode {
			sendReply(conn, from, fmt.Sprintf("[%s] echo: %s", agentName, content))
			continue
		}

		// Bridge mode: write to inbox
		entry, _ := json.Marshal(map[string]interface{}{
			"from": from, "content": content, "time": time.Now().UnixMilli(),
		})
		f, _ := os.OpenFile(inboxFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		f.Write(entry)
		f.Write([]byte("\n"))
		f.Close()
	}
}

// ── Outbox loop ────────────────────────────────
func outboxLoop(conn *websocket.Conn, done chan struct{}) {
	var lastMod time.Time
	t := time.NewTicker(500 * time.Millisecond)
	defer t.Stop()

	for {
		select {
		case <-done: return
		case <-t.C:
		}
		info, err := os.Stat(outboxFile)
		if err != nil { continue }
		if !info.ModTime().After(lastMod) { continue }

		time.Sleep(100 * time.Millisecond)
		data, _ := os.ReadFile(outboxFile)
		if len(data) == 0 { continue }
		lastMod = info.ModTime()

		var entry struct {
			ReplyTo string `json:"reply_to"`
			Content string `json:"content"`
		}
		if json.Unmarshal(data, &entry) != nil { continue }
		if entry.ReplyTo == "" || entry.Content == "" { continue }

		sendReply(conn, entry.ReplyTo, entry.Content)
		log.Printf("[OUT] -> %s: %s", entry.ReplyTo, entry.Content)
		os.Remove(outboxFile)
	}
}

// ── Helpers ────────────────────────────────────
var mu sync.Mutex

func sendReply(conn *websocket.Conn, to, content string) {
	mu.Lock()
	defer mu.Unlock()
	reply, _ := json.Marshal(map[string]interface{}{
		"type": "chat:reply", "reply_to": to, "from_agent": agentID, "content": content,
	})
	conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	conn.WriteMessage(websocket.TextMessage, reply)
}

func pingLoop(conn *websocket.Conn, done chan struct{}) {
	t := time.NewTicker(25 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-done: return
		case <-t.C:
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			conn.WriteMessage(websocket.PingMessage, nil)
		}
	}
}
