"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { api, setAuthenticatedUserId } from "@/lib/api";

type AuthUser = { id: string; username: string; is_demo: boolean };

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("两次输入的密码不一致");
      return;
    }
    setBusy(true);
    try {
      const user = await api<AuthUser>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setAuthenticatedUserId(user.id);
      window.location.assign("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "注册失败，请重试");
      setBusy(false);
    }
  }

  return (
    <div className="px-5 pt-16">
      <div className="mb-8 text-center">
        <div className="text-4xl">📚</div>
        <h1 className="mt-3 text-2xl font-extrabold">创建学习账号</h1>
        <p className="mt-2 text-sm text-muted">你的课程和练习记录会与其他账号分开保存</p>
      </div>
      <form onSubmit={submit} className="card space-y-4">
        <label className="block text-sm font-semibold">
          用户名
          <input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" type="text" autoComplete="username" minLength={3} maxLength={32} pattern="[A-Za-z0-9_-]{3,32}" required value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="block text-sm font-semibold">
          密码（至少 8 位）
          <input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <label className="block text-sm font-semibold">
          确认密码
          <input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
        </label>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <button className="btn-primary w-full disabled:opacity-60" disabled={busy} type="submit">{busy ? "正在创建…" : "注册并开始学习"}</button>
      </form>
      <p className="mt-5 text-center text-sm text-muted">
        已有账号？ <Link className="font-bold text-primary" href="/login">返回登录</Link>
      </p>
    </div>
  );
}
