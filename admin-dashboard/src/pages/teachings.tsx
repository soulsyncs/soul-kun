/**
 * CEO Teachings page
 * Shows teachings list, conflicts, and usage statistics
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BookOpen,
  RefreshCw,
  AlertTriangle,
  BarChart3,
  Gauge,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { useTeachingsList, useTeachingConflicts, useTeachingUsageStats } from '@/hooks/use-teachings';
import { api } from '@/lib/api';
import type { TeachingPenetrationResponse } from '@/types/api';

type TabView = 'teachings' | 'conflicts' | 'stats' | 'penetration';

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
  const { data: penetrationData, isLoading: penetrationLoading, refetch: refetchPenetration } =
    useQuery<TeachingPenetrationResponse>({
      queryKey: ['teachings-penetration'],
      queryFn: () => api.teachings.getPenetration(),
    });

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
              refetchPenetration();
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
          <Button
            variant={tab === 'penetration' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('penetration')}
          >
            <Gauge className="mr-1 h-4 w-4" />
            浸透度メーター
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

        {/* Penetration tab */}
        {tab === 'penetration' && (
          <div className="space-y-4">
            {/* Overall penetration summary */}
            <div className="grid grid-cols-3 gap-4">
              <Card>
                <CardContent className="p-4 text-center">
                  {penetrationLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <>
                      <div className="text-3xl font-bold">
                        {penetrationData ? `${penetrationData.overall_penetration_pct.toFixed(0)}%` : '—'}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        全体浸透度
                        <InfoTooltip text="登録済みの教えのうち、ソウルくんが実際に1回以上使った割合です（AIによる推定値）" />
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  {penetrationLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <>
                      <div className="text-3xl font-bold">
                        {penetrationData?.used_teachings ?? 0}
                        <span className="text-sm text-muted-foreground font-normal">
                          /{penetrationData?.total_teachings ?? 0}件
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">活用中の教え数</div>
                    </>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  {penetrationLoading ? (
                    <Skeleton className="h-12 w-full" />
                  ) : (
                    <>
                      <div className="text-3xl font-bold">{penetrationData?.total_usages ?? 0}</div>
                      <div className="text-xs text-muted-foreground mt-1">総参照回数</div>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Category penetration bars */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">カテゴリ別浸透度</CardTitle>
              </CardHeader>
              <CardContent>
                {penetrationLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className="h-10 w-full" />
                    ))}
                  </div>
                ) : !penetrationData?.by_category.length ? (
                  <div className="text-center py-4 text-muted-foreground text-sm">データがありません</div>
                ) : (
                  <div className="space-y-3">
                    {penetrationData.by_category.map((cat) => (
                      <div key={cat.category}>
                        <div className="flex items-center justify-between text-sm mb-1">
                          <span className="font-medium">{cat.category}</span>
                          <span className="text-muted-foreground">
                            {cat.used_teachings}/{cat.total_teachings}件 使用中・{cat.total_usages}回参照
                          </span>
                        </div>
                        <div className="w-full bg-secondary rounded-full h-3">
                          <div
                            className={`h-3 rounded-full transition-all ${
                              cat.penetration_pct >= 70
                                ? 'bg-green-500'
                                : cat.penetration_pct >= 40
                                  ? 'bg-yellow-500'
                                  : 'bg-destructive'
                            }`}
                            style={{ width: `${Math.min(cat.penetration_pct, 100)}%` }}
                          />
                        </div>
                        <div className="text-xs text-right text-muted-foreground mt-0.5">
                          {cat.penetration_pct.toFixed(0)}%
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Top teachings */}
            {(penetrationData?.top_teachings.length ?? 0) > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium">
                    よく使われている教え TOP5
                    <InfoTooltip text="ソウルくんが判断の際に最もよく参照している教えです" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {penetrationData!.top_teachings.map((t, idx) => (
                      <div key={t.id} className="flex items-start gap-3 rounded border p-3">
                        <span className="text-lg font-bold text-muted-foreground w-6 shrink-0">
                          {idx + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <Badge variant="outline" className="mb-1">{t.category}</Badge>
                          <p className="text-sm">{t.statement}</p>
                        </div>
                        <div className="text-right shrink-0">
                          <div className="text-sm font-bold">{t.usage_count}回</div>
                          <div className="text-xs text-muted-foreground">{t.penetration_pct.toFixed(1)}%</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Unused teachings */}
            {(penetrationData?.unused_teachings.length ?? 0) > 0 && (
              <Card className="border-orange-200 dark:border-orange-800">
                <CardHeader>
                  <CardTitle className="text-sm font-medium text-orange-700 dark:text-orange-300">
                    未活用の教え（改善チャンス）
                    <InfoTooltip text="ソウルくんがまだ一度も参照していない教えです。教えの書き方を改善するとより使われるようになります" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {penetrationData!.unused_teachings.map((t) => (
                      <div key={t.id} className="flex items-start gap-3 rounded border border-orange-100 dark:border-orange-900 p-3">
                        <Badge variant="outline">{t.category}</Badge>
                        <p className="text-sm text-muted-foreground">{t.statement}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
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
