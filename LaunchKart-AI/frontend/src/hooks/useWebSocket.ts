import { useEffect, useRef, useState } from "react";

interface UseWebSocketOptions {
  url: string;
  onMessage?: (message: any) => void;
  reconnectAttempts?: number;
}

export function useWebSocket({ url, onMessage, reconnectAttempts = 5 }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCountRef = useRef(0);
  const onMessageRef = useRef(onMessage);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    let ws: WebSocket;

    const connect = () => {
      if (!url || !url.startsWith("ws")) return;
      try {
        ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          setIsConnected(true);
          reconnectCountRef.current = 0;
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (onMessageRef.current) onMessageRef.current(data);
          } catch (error) {
            console.warn("Failed to parse WebSocket message", error);
          }
        };

        ws.onclose = () => {
          setIsConnected(false);
          if (reconnectCountRef.current < reconnectAttempts) {
            reconnectCountRef.current += 1;
            setTimeout(connect, 1500 * Math.pow(1.5, reconnectCountRef.current));
          }
        };

        ws.onerror = () => {
          // Silent warning on connection drops; onclose handles automatic exponential backoff reconnection
          console.warn(`WebSocket reconnecting to ${url}...`);
          try {
            ws.close();
          } catch {
            // Ignore close error on dropped socket
          }
        };
      } catch (err) {
        console.warn("WebSocket initialization retry needed:", err);
      }
    };

    connect();

    return () => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // Ignore close error during unmount
        }
      }
    };
  }, [url, reconnectAttempts]);

  const sendMessage = (message: unknown) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  };

  return { isConnected, sendMessage };
}
