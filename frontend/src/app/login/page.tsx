"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { api, setAuthenticatedUserId } from "@/lib/api";

type AuthUser = { id: string; username: string; is_demo: boolean };

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function authenticate() {
    setBusy(true);
    setError("");
    try {
      const user = await api<AuthUser>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setAuthenticatedUserId(user.id);
      window.location.assign("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登录失败，请重试");
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void authenticate();
  }

  return (
    <div className="px-5 pt-16">
      <div className="mb-8 text-center">
        <div className="text-4xl">📚</div>
        <h1 className="mt-3 text-2xl font-extrabold">登录 AI 考试教练</h1>
        <p className="mt-2 text-sm text-muted">继续你的课程复习与真题练习</p>
      </div>
      <form onSubmit={submit} className="card space-y-4">
        <label className="block text-sm font-semibold">
          用户名
          <input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" type="text" autoComplete="username" minLength={3} maxLength={32} required value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="block text-sm font-semibold">
          密码
          <input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <button className="btn-primary w-full disabled:opacity-60" disabled={busy} type="submit">{busy ? "正在登录…" : "登录"}</button>
      </form>
      <p className="mt-5 text-center text-sm text-muted">
        还没有账号？ <Link className="font-bold text-primary" href="/register">注册</Link>
      </p>
    </div>
  );
}
