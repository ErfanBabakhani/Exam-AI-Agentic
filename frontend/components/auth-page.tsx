"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, getErrorMessage, type TokenResponse } from "@/lib/api";
import { hasAccessToken, persistAccessToken } from "@/lib/auth";
import { AuthForm } from "@/components/auth-form";
import { ErrorAlert } from "@/components/error-alert";
import { LoadingState } from "@/components/loading-state";
import { TransientMessage } from "@/components/transient-message";
import { WelcomePanel } from "@/components/welcome-panel";


export function AuthPage() {
  const [checking, setChecking] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function validateSession() {
      if (!hasAccessToken()) {
        setChecking(false);
        return;
      }

      try {
        await api.me();
        setAuthenticated(true);
      } catch (sessionError) {
        setError(getErrorMessage(sessionError));
      } finally {
        setChecking(false);
      }
    }

    void validateSession();
  }, []);

  async function handleAuthenticated(token: TokenResponse, successMessage: string) {
    persistAccessToken(token.access_token);
    setAuthenticated(true);
    setError("");
    setMessage(successMessage);
  }

  if (checking) {
    return (
      <LoadingState
        message="Checking whether you already have an active browser session."
        title="Preparing sign-in page"
      />
    );
  }

  if (authenticated) {
    return (
      <section className="page-grid single-column public-page">
        <div className="hero-card">
          <p className="eyebrow">Authenticated</p>
          <h1>Your session is ready.</h1>
          <p className="lede">{message || "You are already logged in and can return to the dashboard."}</p>
          <div className="row action-row">
            <Link className="primary" href="/">
              Open dashboard
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="page-grid auth-grid public-page">
      <WelcomePanel />
      <div className="column">
        {error ? <ErrorAlert message={error} /> : null}
        {message ? <TransientMessage message={message} tone="success" /> : null}
        <AuthForm initialMode="login" onAuthenticated={handleAuthenticated} />
      </div>
    </section>
  );
}
