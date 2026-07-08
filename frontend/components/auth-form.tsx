"use client";

import { FormEvent, useState } from "react";
import { api, getErrorMessage, type TokenResponse } from "@/lib/api";
import { ErrorAlert } from "@/components/error-alert";
import { TransientMessage } from "@/components/transient-message";


type AuthMode = "login" | "register";

export function AuthForm({
  initialMode = "login",
  onAuthenticated
}: {
  initialMode?: AuthMode;
  onAuthenticated: (token: TokenResponse, successMessage: string) => Promise<void> | void;
}) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");

    try {
      if (mode === "register") {
        await api.register({ email, password });
      }
      const token = await api.login({ email, password });
      const message =
        mode === "register" ? "Account created. You are now logged in." : "Login successful.";
      setSuccess(message);
      await onAuthenticated(token, message);
    } catch (submissionError) {
      setError(getErrorMessage(submissionError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel auth-card">
      <div className="row between">
        <div>
          <p className="eyebrow">Access</p>
          <h2>{mode === "login" ? "Log in" : "Create an account"}</h2>
        </div>
        <div className="segment">
          <button
            className={mode === "login" ? "active" : ""}
            onClick={() => {
              setMode("login");
              setError("");
              setSuccess("");
            }}
            type="button"
          >
            Login
          </button>
          <button
            className={mode === "register" ? "active" : ""}
            onClick={() => {
              setMode("register");
              setError("");
              setSuccess("");
            }}
            type="button"
          >
            Register
          </button>
        </div>
      </div>

      <form className="stack" onSubmit={onSubmit}>
        <label>
          <span>Email</span>
          <input
            autoComplete="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="teacher@example.com"
            required
            type="email"
            value={email}
          />
        </label>
        <label>
          <span>Password</span>
          <input
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={8}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="At least 8 characters"
            required
            type="password"
            value={password}
          />
        </label>
        <button className="primary" disabled={busy} type="submit">
          {busy ? "Working..." : mode === "login" ? "Log in" : "Register and log in"}
        </button>
        {error ? <ErrorAlert message={error} /> : null}
        {success ? <TransientMessage message={success} tone="success" /> : null}
      </form>
    </div>
  );
}
