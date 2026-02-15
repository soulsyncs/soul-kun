/**
 * Proactive monitoring page
 * Shows proactive actions and response statistics
 */

import { useState } from 'react';
import { Zap, RefreshCw, TrendingUp, ThumbsUp } from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useProactiveActions, useProactiveStats } from '@/hooks/use-proactive';

const PRIORITY_COLORS: Record<string, 'destructive' | 'default' | 'secondary' | 'outline'> = {
  high: 'destructive',
  medium: 'default',
  low: 'secondary',
};

const TRIGGER_LABELS: Record<string, string> = {
  goal_abandoned: '目標放棄',
  task_overdue: 'タスク期限切れ',
  emotion_drop: '感情低下',
  inactivity: '活動停止',
  positive_reinforcement: 'ポジティブ強化',
};

export function ProactivePage() {
  const [triggerFilter, setTriggerFilter] = useState<string | undefined>();

  const { data: statsData, isLoading: statsLoading, refetch: refetchStats } = useProactiveStats();
  const { data: actionsData, isLoading: actionsLoading, refetch: refetchActions } = useProactiveActions({
    trigger_type: triggerFilter,
  });

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Zap className="h-6 w-6" />
              プロアクティブ
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              能動的なアクションの監視と統計
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchStats();
              refetchActions();
            }}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-3 gap-4">
          {statsLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <Card key={i}>
                <CardContent className="p-4">
                  <Skeleton className="h-8 w-16 mb-2" />
                  <Skeleton className="h-4 w-24" />
                </CardContent>
              </Card>
            ))
          ) : (
            <>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Zap className="h-4 w-4" />
                    総アクション数
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {statsData?.total_actions ?? 0}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <ThumbsUp className="h-4 w-4" />
                    ポジティブ反応
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {statsData?.positive_responses ?? 0}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <TrendingUp className="h-4 w-4" />
                    反応率
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {statsData?.response_rate ?? 0}%
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Trigger type breakdown */}
        {statsData?.by_trigger_type && statsData.by_trigger_type.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">トリガー別統計</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {statsData.by_trigger_type.map((item) => (
                  <div key={item.trigger_type} className="flex items-center justify-between text-sm">
                    <span>{TRIGGER_LABELS[item.trigger_type] ?? item.trigger_type}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-muted-foreground">{item.total}件</span>
                      <span className="text-green-600">+{item.positive}件</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Filter */}
        <div className="flex gap-2">
          {[undefined, 'goal_abandoned', 'task_overdue', 'emotion_drop'].map((t) => (
            <Button
              key={t ?? 'all'}
              variant={triggerFilter === t ? 'default' : 'outline'}
              size="sm"
              onClick={() => setTriggerFilter(t)}
            >
              {t ? TRIGGER_LABELS[t] ?? t : '全て'}
            </Button>
          ))}
        </div>

        {/* Action list */}
        <Card>
          <CardContent className="p-4">
            {actionsLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : !actionsData?.actions.length ? (
              <div className="text-center py-8 text-muted-foreground">
                アクションがありません
              </div>
            ) : (
              <div className="space-y-2">
                {actionsData.actions.map((action) => (
                  <div key={action.id} className="rounded-lg border p-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant={PRIORITY_COLORS[action.priority] ?? 'outline'}>
                          {action.priority}
                        </Badge>
                        <span className="text-sm font-medium">
                          {TRIGGER_LABELS[action.trigger_type] ?? action.trigger_type}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs">
                          {action.message_type}
                        </Badge>
                        {action.user_response_positive != null && (
                          <Badge variant={action.user_response_positive ? 'default' : 'secondary'}>
                            {action.user_response_positive ? '好反応' : '無反応'}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {action.created_at && action.created_at.slice(0, 16).replace('T', ' ')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
