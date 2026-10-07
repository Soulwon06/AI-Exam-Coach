import type { Metadata } from "next";
import "./globals.css";
import BottomNav from "@/components/BottomNav";
import AuthGate from "@/components/AuthGate";

export const metadata: Metadata = {
  title: "AI 考试教练",
  description: "个性化备考助手：上传资料，AI 拆解考点，动态安排学习与强化。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen">
        <AuthGate>
          <main className="mx-auto max-w-md pb-20">{children}</main>
          <BottomNav />
        </AuthGate>
      </body>
    </html>
  );
}
