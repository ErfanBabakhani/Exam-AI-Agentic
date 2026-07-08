"use client";

import { useEffect, useRef, useState } from "react";

type Tone = "success" | "error";

const FULL_DURATION_MS = 6000;

export function TransientMessage({
  message,
  tone,
}: {
  message: string;
  tone: Tone;
}) {
  const [isVisible, setIsVisible] = useState(Boolean(message));
  const [isFading, setIsFading] = useState(false);
  const fadeFrameRef = useRef<number | null>(null);
  const hideTimerRef = useRef<number | null>(null);

  function clearTimers() {
    if (fadeFrameRef.current !== null) {
      window.cancelAnimationFrame(fadeFrameRef.current);
      fadeFrameRef.current = null;
    }
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }

  function startTimers() {
    clearTimers();
    setIsVisible(Boolean(message));
    setIsFading(false);
    if (!message) {
      return;
    }
    fadeFrameRef.current = window.requestAnimationFrame(() => {
      setIsFading(true);
      fadeFrameRef.current = null;
    });
    hideTimerRef.current = window.setTimeout(() => {
      setIsVisible(false);
      setIsFading(false);
    }, FULL_DURATION_MS);
  }

  useEffect(() => {
    startTimers();
    return clearTimers;
  }, [message]);

  if (!message || !isVisible) {
    return null;
  }

  return (
    <div
      className={`status status-${tone} transient-message${isFading ? " transient-message-fading" : ""}`}
      onMouseEnter={() => {
        clearTimers();
        setIsVisible(true);
        setIsFading(false);
      }}
      onMouseLeave={() => startTimers()}
      role={tone === "error" ? "alert" : "status"}
    >
      {message}
    </div>
  );
}
