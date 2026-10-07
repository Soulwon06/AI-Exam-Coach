"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Loading from "@/components/State";
import { api, setAuthenticatedUserId } from "@/lib/api";

type AuthUser = { id: string; username: string; is_demo: boolean };
type AuthState = "unknown" | "authenticated" | "anonymous";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [authState, setAuthState] = useState<AuthState>("unknown");

  useEffect(() => {
    if (pathname === "/login" || pathname === "/register") {
      setReady(true);
      return;
    }
    if (authState === "authenticated") {
      setReady(true);
      return;
    }
    if (authState === "anonymous") {
      router.replace("/login");
      return;
    }

    let cancelled = false;
    setReady(false);
    api<AuthUser>("/auth/me")
      .then((user) => {
        if (cancelled) return;
        setAuthenticatedUserId(user.id);
        setAuthState("authenticated");
        setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setAuthenticatedUserId(null);
        setAuthState("anonymous");
        router.replace("/login");
      });

    return () => {
      cancelled = true;
    };
  }, [authState, pathname, router]);

  if (!ready && pathname !== "/login" && pathname !== "/register") return <Loading />;
  return <>{children}</>;
}
