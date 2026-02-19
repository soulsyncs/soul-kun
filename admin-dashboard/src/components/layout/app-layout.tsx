/**
 * Main application layout wrapper
 * Includes sidebar and main content area
 * Mobile: hamburger menu + slide-in sidebar overlay
 * Desktop: fixed sidebar always visible
 */

import { useState, type ReactNode } from 'react';
import { Menu } from 'lucide-react';
import { Sidebar } from './sidebar';

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden">

      {/* ====== モバイル: 背景オーバーレイ（サイドバーが開いた時に表示） ====== */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ====== サイドバー ====== */}
      {/* モバイル: 固定オーバーレイとして z-30 で表示。デスクトップ: 通常フロー */}
      <div
        className={[
          // モバイル
          'fixed inset-y-0 left-0 z-30 transition-transform duration-300 md:relative md:translate-x-0 md:z-auto',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
          // デスクトップ
          'md:flex md:shrink-0',
        ].join(' ')}
      >
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      {/* ====== メインコンテンツ ====== */}
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-background">

        {/* モバイル専用ヘッダー（ハンバーガーメニュー）*/}
        <div className="flex h-14 shrink-0 items-center gap-3 border-b px-4 md:hidden">
          <button
            type="button"
            aria-label="メニューを開く"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold">ソウルくん管理画面</span>
        </div>

        {/* ページコンテンツ */}
        <div className="container mx-auto p-4 md:p-6">
          {children}
        </div>
      </main>
    </div>
  );
}
