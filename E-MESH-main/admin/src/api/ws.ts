import { useEffect, useRef, useState } from 'react';
import { EventEnvelope, EventType } from './types';

type EventHandler = (data: any) => void;

class AdminWebSocketClient {
  private ws: WebSocket | null = null;
  private listeners: Map<string, Set<EventHandler>> = new Map();
  private reconnectTimer: number | null = null;
  private pingInterval: number | null = null;

  public connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const token = localStorage.getItem('emesh_admin_access_token');
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.port === '5173' ? `${window.location.hostname || 'localhost'}:8000` : window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws${token ? `?token=${encodeURIComponent(token)}` : ''}`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[E-Mesh Admin WS] Connected to live NOC stream');
        this.startPing();
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);

          if (payload.type === 'pong') {
            return;
          }

          const eventName = payload.event;
          if (eventName) {
            // Trigger specific listeners
            const specific = this.listeners.get(eventName);
            if (specific) {
              specific.forEach((handler) => handler(payload.data));
            }

            // Trigger wildcard listeners
            const all = this.listeners.get('*');
            if (all) {
              all.forEach((handler) => handler(payload));
            }
          }
        } catch (err) {
          console.error('[E-Mesh Admin WS] Frame parse error', err);
        }
      };

      this.ws.onclose = () => {
        console.log('[E-Mesh Admin WS] Disconnected. Reconnecting in 4s...');
        this.stopPing();
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.reconnectTimer = window.setTimeout(() => this.connect(), 4000);
      };

      this.ws.onerror = (err) => {
        console.warn('[E-Mesh Admin WS] Socket error', err);
      };
    } catch (err) {
      console.warn('[E-Mesh Admin WS] Failed to create socket', err);
    }
  }

  private startPing() {
    this.stopPing();
    this.pingInterval = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 20000);
  }

  private stopPing() {
    if (this.pingInterval) clearInterval(this.pingInterval);
    this.pingInterval = null;
  }

  public subscribe(event: string, handler: EventHandler) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);

    return () => {
      const set = this.listeners.get(event);
      if (set) {
        set.delete(handler);
        if (set.size === 0) {
          this.listeners.delete(event);
        }
      }
    };
  }
}

export const adminWs = new AdminWebSocketClient();

/**
 * React Hook for subscribing to real-time mesh events
 */
export function useMeshEvent(event: string, handler: (data: any) => void) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    adminWs.connect();
    const unsubscribe = adminWs.subscribe(event, (data) => {
      handlerRef.current(data);
    });
    return () => unsubscribe();
  }, [event]);
}
