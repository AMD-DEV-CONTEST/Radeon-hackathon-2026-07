package uasclient

import (
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// writeMu is a per-connection write mutex. gorilla/websocket allows
// only one concurrent writer per connection. The ping goroutine and
// the broadcast paths (event ack, Send) would otherwise write the
// same conn concurrently → corrupted frames → the connection errors
// out and drops. Every write MUST go through safeWriteJSON.
var writeMu sync.Map // *websocket.Conn → *sync.Mutex

func connMutex(c *websocket.Conn) *sync.Mutex {
	mu, _ := writeMu.LoadOrStore(c, &sync.Mutex{})
	return mu.(*sync.Mutex)
}

// releaseConn frees the per-connection write mutex. Call after the
// connection is closed so the map doesn't grow forever.
func releaseConn(c *websocket.Conn) {
	writeMu.Delete(c)
}

// safeWriteJSON serializes WriteJSON per connection.
func safeWriteJSON(c *websocket.Conn, v interface{}) error {
	mu := connMutex(c)
	mu.Lock()
	defer mu.Unlock()
	_ = c.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.WriteJSON(v)
}

// sendAck posts an event:ack frame back to the Gateway. status is
// "ack" or "nack". The Gateway uses this to advance its per-event
// pending/acked/nacked counters, so we always send it even when
// the consumer deduped the event locally.
func sendAck(c *websocket.Conn, eventKey, eventID, status string) error {
	if eventID == "" {
		return nil
	}
	if status == "" {
		status = "ack"
	}
	frame := map[string]interface{}{
		"type":      "event:ack",
		"event_key": eventKey,
		"event_id":  eventID,
		"status":    status,
		"ts":        time.Now().UTC().Format(time.RFC3339),
	}
	if err := safeWriteJSON(c, frame); err != nil {
		return fmt.Errorf("ack write: %w", err)
	}
	return nil
}

// sendPing writes a WS ping frame. Used by the keepalive loop.
func sendPing(c *websocket.Conn) error {
	mu := connMutex(c)
	mu.Lock()
	defer mu.Unlock()
	_ = c.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.WriteMessage(websocket.PingMessage, nil)
}

// decodeEvent parses a raw frame into Event, leaving the raw map
// populated for callers that want fields we didn't struct-ify.
func decodeEvent(raw []byte) (Event, error) {
	var e Event
	if err := json.Unmarshal(raw, &e); err != nil {
		return e, err
	}
	e.Raw = map[string]interface{}{}
	_ = json.Unmarshal(raw, &e.Raw)
	return e, nil
}
