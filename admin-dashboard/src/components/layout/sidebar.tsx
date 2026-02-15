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
  LogOut,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { useAuth } from '@/hooks/use-auth';

const navigation = [
  { name: 'ダッシュボード', href: '/', icon: LayoutDashboard },
  { name: 'AI脳分析', href: '/brain', icon: Brain },
  { name: 'コスト管理', href: '/costs', icon: DollarSign },
  { name: 'メンバー', href: '/members', icon: Users },
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
