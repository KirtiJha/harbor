import { useEffect, useRef, useState } from "react";
import type { Activity, Snapshot } from "./api";

export type Conn = "connecting" | "live" | "lost";

/** The live picture from Harbor's event stream; reconnects on its own when Harbor restarts. */
export function useHarbor(onEvents: (e: Activity[]) => void) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [conn, setConn] = useState<Conn>("connecting");
  const cb = useRef(onEvents);
  cb.current = onEvents;

  useEffect(() => {
    let es: EventSource | null = null;
    let retry: number | undefined;
    let closed = false;
    const open = () => {
      es = new EventSource("/api/stream");
      es.addEventListener("snapshot", (e) => {
        setSnap(JSON.parse((e as MessageEvent).data));
        setConn("live");
      });
      es.addEventListener("events", (e) => cb.current(JSON.parse((e as MessageEvent).data)));
      es.onerror = () => {
        setConn("lost");
        es?.close();
        if (!closed) retry = window.setTimeout(open, 1500);
      };
    };
    open();
    return () => {
      closed = true;
      es?.close();
      window.clearTimeout(retry);
    };
  }, []);

  return { snap, conn };
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function useLocal<T>(key: string, initial: T) {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(v));
  }, [key, v]);
  return [v, setV] as const;
}
