"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { clearAccessToken, getAuthChangedEventName, hasAccessToken } from "@/lib/auth";

export function TopNav() {
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    const eventName = getAuthChangedEventName();
    const sync = () => setAuthenticated(hasAccessToken());
    sync();
    window.addEventListener(eventName, sync);
    window.addEventListener("focus", sync);
    return () => {
      window.removeEventListener(eventName, sync);
      window.removeEventListener("focus", sync);
    };
  }, []);

  return (
    <nav className="topnav">
      <Link href="/">Home</Link>
      {authenticated ? (
        <button
          className="topnav-button"
          onClick={() => {
            clearAccessToken();
            window.location.href = "/";
          }}
          type="button"
        >
          Log out
        </button>
      ) : (
        <Link href="/auth">Sign in</Link>
      )}
    </nav>
  );
}
