"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "学习", icon: "📖" },
  { href: "/knowledge", label: "知识", icon: "🗂️" },
  { href: "/review", label: "错题", icon: "🔁" },
  { href: "/me", label: "我的", icon: "👤" },
];

export default function BottomNav() {
  const pathname = usePathname();
  if (pathname.startsWith("/learning-sessions") || pathname === "/login" || pathname === "/register") return null;
  return (
    <nav className="bottom-nav grid grid-cols-4 pb-[env(safe-area-inset-bottom)]">
      {items.map((item) => {
        const active =
          pathname === item.href ||
          (item.href === "/" && pathname === "") ||
          (item.href !== "/" && pathname.startsWith(item.href));
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex flex-col items-center gap-0.5 py-2 text-xs font-semibold ${
              active ? "text-primary" : "text-muted"
            }`}
          >
            <span className="text-xl leading-none">{item.icon}</span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
