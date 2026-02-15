/**
 * CEO Teachings page
 * Shows teachings list, conflicts, and usage statistics
 */

import { useState } from 'react';
import {
  BookOpen,
  RefreshCw,
  AlertTriangle,
  BarChart3,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useTeachingsList, useTeachingConflicts, useTeachingUsageStats } from '@/hooks/use-teachings';

type TabView = 'teachings' | 'conflicts' | 'stats';

const STATUS_COLORS: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  validated: 'default',
  pending: 'outline',
  rejected: 'destructive',
};

export function TeachingsPage() {
  const [tab, setTab] = useState<TabView>('teachings');
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();

  const { data: teachingsData, isLoading: teachingsLoading, refetch: refetchTeachings } = useTeachingsList({
    category: categoryFilter,
  });
  const { data: conflictsData, isLoading: conflictsLoading, refetch: refetchConflicts } = useTeachingConflicts();
  const { data: usageData, isLoading: usageLoading, refetch: refetchUsage } = useTeachingUsageStats();

  // Extract unique categories from teachings
  const categories = teachingsData?.teachings
    ? [...new Set(teachingsData.teachings.map((t) => t.category))]
    : [];

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <BookOpen className="h-6 w-6" />
              CEO教え
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              代表の教え・方針の管理と利用状況
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchTeachings();
              refetchConflicts();
              refetchUsage();
            }}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Tab navigation */}
        <div className="flex gap-2">
          <Button
            variant={tab === 'teachings' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('teachings')}
          >
            <BookOpen className="mr-1 h-4 w-4" />
            教え一覧 ({teachingsData?.total_count ?? 0})
          </Button>
          <Button
            variant={tab === 'conflicts' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('conflicts')}
          >
            <AlertTriangle className="mr-1 h-4 w-4" />
            矛盾検出 ({conflictsData?.total_count ?? 0})
          </Button>
          <Button
            variant={tab === 'stats' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('stats')}
          >
            <BarChart3 className="mr-1 h-4 w-4" />
            利用統計
          </Button>
        </div>

        {/* Teachings tab */}
        {tab === 'teachings' && (
          <>
            {categories.length > 0 && (
              <div className="flex gap-2 flex-wrap">
                <Button
                  variant={!categoryFilter ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setCategoryFilter(undefined)}
                >
                  全て
                </Button>
                {categories.map((cat) => (
                  <Button
                    key={cat}
                    variant={categoryFilter === cat ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setCategoryFilter(cat)}
                  >
                    {cat}
                  </Button>
                ))}
              </div>
            )}
            <Card>
              <CardContent className="p-4">
                {teachingsLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Skeleton key={i} className="h-16 w-full" />
                    ))}
                  </div>
                ) : !teachingsData?.teachings.length ? (
                  <div className="text-center py-8 text-muted-foreground">
                    教えが登録されていません
                  </div>
                ) : (
                  <div className="space-y-3">
                    {teachingsData.teachings.map((teaching) => (
                      <div key={teaching.id} className="rounded-lg border p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <Badge variant="outline">{teaching.category}</Badge>
                            {teaching.subcategory && (
                              <Badge variant="secondary">{teaching.subcategory}</Badge>
                            )}
                            {teaching.priority != null && (
                              <span className="text-xs text-muted-foreground">
                                優先度: {teaching.priority}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <Badge variant={STATUS_COLORS[teaching.validation_status] ?? 'outline'}>
                              {teaching.validation_status}
                            </Badge>
                            {teaching.usage_count != null && (
                              <span className="text-xs text-muted-foreground">
                                利用 {teaching.usage_count}回
                              </span>
                            )}
                          </div>
                        </div>
                        <p className="text-sm">{teaching.statement}</p>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {/* Conflicts tab */}
        {tab === 'conflicts' && (
          <Card>
            <CardContent className="p-4">
              {conflictsLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : !conflictsData?.conflicts.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  矛盾は検出されていません
                </div>
              ) : (
                <div className="space-y-3">
                  {conflictsData.conflicts.map((conflict) => (
                    <div key={conflict.id} className="rounded-lg border p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <AlertTriangle className="h-4 w-4 text-orange-500" />
                        <Badge variant={conflict.severity === 'high' ? 'destructive' : 'default'}>
                          {conflict.severity}
                        </Badge>
                        <Badge variant="outline">{conflict.conflict_type}</Badge>
                        {conflict.created_at && (
                          <span className="text-xs text-muted-foreground">
                            {conflict.created_at.slice(0, 10)}
                          </span>
                        )}
                      </div>
                      <p className="text-sm">{conflict.description}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Stats tab */}
        {tab === 'stats' && (
          <div className="space-y-4">
            {/* Summary cards */}
            <div className="grid grid-cols-2 gap-4">
              <Card>
                <CardContent className="p-4 text-center">
                  {usageLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <>
                      <div className="text-2xl font-bold">{usageData?.total_usages ?? 0}</div>
                      <div className="text-xs text-muted-foreground">総利用回数</div>
                    </>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  {usageLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <>
                      <div className="text-2xl font-bold">
                        {usageData ? `${usageData.helpful_rate.toFixed(1)}%` : '-'}
                      </div>
                      <div className="text-xs text-muted-foreground">有用率</div>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* By category */}
            <Card>
              <CardContent className="p-4">
                <h3 className="text-sm font-medium mb-3">カテゴリ別利用状況</h3>
                {usageLoading ? (
                  <div className="space-y-2">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className="h-8 w-full" />
                    ))}
                  </div>
                ) : !usageData?.by_category.length ? (
                  <div className="text-center py-4 text-muted-foreground text-sm">
                    利用データがありません
                  </div>
                ) : (
                  <div className="space-y-2">
                    {usageData.by_category.map((cat, idx) => (
                      <div key={idx} className="flex items-center justify-between rounded border p-2">
                        <span className="text-sm font-medium">{cat.category}</span>
                        <div className="flex items-center gap-3 text-sm">
                          <span>{cat.usage_count}回</span>
                          <span className="text-muted-foreground">
                            ({cat.helpful_count}件 有用)
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
