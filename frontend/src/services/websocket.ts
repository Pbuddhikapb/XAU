export type ConnectionStatus = "CONNECTING" | "OPEN" | "CLOSED" | "FALLBACK";

export type TelemetryFrameHandler = (data: any, timestamp: string) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private status: ConnectionStatus = "CLOSED";
  private statusListeners: Array<(status: ConnectionStatus) => void> = [];
  private topicListeners: Map<string, Set<TelemetryFrameHandler>> = new Map();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private watchdogTimer: number | null = null;
  private lastMessageTime = 0;

  constructor() {
    this.connect();
  }

  public getStatus(): ConnectionStatus {
    return this.status;
  }

  public onStatusChange(listener: (status: ConnectionStatus) => void): () => void {
    this.statusListeners.push(listener);
    listener(this.status);
    return () => {
      this.statusListeners = this.statusListeners.filter((l) => l !== listener);
    };
  }

  public subscribe(topic: string, handler: TelemetryFrameHandler): () => void {
    if (!this.topicListeners.has(topic)) {
      this.topicListeners.set(topic, new Set());
    }
    this.topicListeners.get(topic)!.add(handler);
    return () => {
      this.topicListeners.get(topic)?.delete(handler);
    };
  }

  private setStatus(newStatus: ConnectionStatus) {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.statusListeners.forEach((l) => l(newStatus));
    }
  }

  public connect() {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      return;
    }

    this.setStatus("CONNECTING");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/telemetry`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.setStatus("OPEN");
        this.reconnectAttempts = 0;
        this.lastMessageTime = Date.now();
        this.startHeartbeat();
      };

      this.ws.onmessage = (event) => {
        this.lastMessageTime = Date.now();
        if (event.data === "pong") return;

        try {
          const frame = JSON.parse(event.data);
          const topic = frame.topic;
          const data = frame.data;
          const timestamp = frame.timestamp;

          if (topic && this.topicListeners.has(topic)) {
            this.topicListeners.get(topic)!.forEach((handler) => handler(data, timestamp));
          }
          // Also dispatch wildcard listeners
          if (this.topicListeners.has("*")) {
            this.topicListeners.get("*")!.forEach((handler) => handler({ topic, data }, timestamp));
          }
        } catch {
          // Plain text message ignored
        }
      };

      this.ws.onclose = () => {
        this.cleanup();
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        if (this.ws) {
          this.ws.close();
        }
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.pingTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send("ping");
      }
    }, 10000);

    this.watchdogTimer = window.setInterval(() => {
      if (this.status === "OPEN" && Date.now() - this.lastMessageTime > 25000) {
        // Watchdog timeout - force reconnect
        if (this.ws) {
          this.ws.close();
        }
      }
    }, 5000);
  }

  private stopHeartbeat() {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.watchdogTimer !== null) {
      clearInterval(this.watchdogTimer);
      this.watchdogTimer = null;
    }
  }

  private cleanup() {
    this.stopHeartbeat();
    this.ws = null;
    this.setStatus("CLOSED");
  }

  private scheduleReconnect() {
    if (this.reconnectTimer !== null) return;

    this.reconnectAttempts++;
    if (this.reconnectAttempts > this.maxReconnectAttempts) {
      this.setStatus("FALLBACK");
      // Fallback mode: still retry every 30s
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, 30000);
      return;
    }

    const backoff = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 15000);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, backoff);
  }
}

export const wsClient = new WebSocketClient();
