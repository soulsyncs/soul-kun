/**
 * Sidebar navigation component
 */

import { Link, useLocation } from '@tanstack/react-router';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  Brain,
  DollarSign,
  Users,
  Network,
  Target,
  Heart,
  CheckSquare,
  Lightbulb,
  Video,
  Zap,
  BookOpen,
  Settings,
  Link2,
  LogOut,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { useAuth } from '@/hooks/use-auth';

const navigation = [
  // 概要
  { name: 'ダッシュボード', href: '/', icon: LayoutDashboard },
  // 組織
  { name: '組織図', href: '/org-chart', icon: Network },
  { name: 'メンバー', href: '/members', icon: Users },
  // マネジメント
  { name: '目標管理', href: '/goals', icon: Target },
  { name: 'ウェルネス', href: '/wellness', icon: Heart },
  { name: 'タスク', href: '/tasks', icon: CheckSquare },
  // 分析
  { name: 'AI脳分析', href: '/brain', icon: Brain },
  { name: 'インサイト', href: '/insights', icon: Lightbulb },
  { name: 'ミーティング', href: '/meetings', icon: Video },
  // 運用
  { name: 'プロアクティブ', href: '/proactive', icon: Zap },
  { name: 'CEO教え', href: '/teachings', icon: BookOpen },
  { name: 'コスト管理', href: '/costs', icon: DollarSign },
  { name: '連携設定', href: '/integrations', icon: Link2 },
  { name: 'システム', href: '/system', icon: Settings },
];

export function Sidebar() {
  const location = useLocation();
  const { user, logout } = useAuth();

  return (
    <div className="flex h-full w-64 flex-col border-r bg-card">
      {/* Logo */}
      <div className="flex h-16 items-center px-6">
        <h1 className="text-xl font-bold">ソウルくん管理画面</h1>
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigation.map((item) => {
          const isActive = location.pathname === item.href;
          const Icon = item.icon;

          return (
            <Link
              key={item.name}
              to={item.href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
              )}
            >
              <Icon className="h-5 w-5" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <Separator />

      {/* User info and logout */}
      <div className="p-4">
        <div className="mb-3 text-sm">
          <div className="font-medium">{user?.name ?? '管理者'}</div>
          <div className="text-muted-foreground">
            レベル {user?.role_level ?? '-'}
            {user?.role ? ` (${user.role})` : ''}
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={logout}
        >
          <LogOut className="mr-2 h-4 w-4" />
          ログアウト
        </Button>
      </div>
    </div>
  );
}
