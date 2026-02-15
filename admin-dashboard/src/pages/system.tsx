/**
 * System Health page
 * Shows system health summary, daily metrics, and self-diagnoses
 */

import { useState } from 'react';
import {
  Settings,
  RefreshCw,
  Activity,
  Stethoscope,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useSystemHealth, useSystemMetrics, useSelfDiagnoses } from '@/hooks/use-system';

type TabView = 'health' | 'metrics' | 'diagnoses';

export function SystemPage() {
  const [tab, setTab] = useState<TabView>('health');
  const [metricsDays, setMetricsDays] = useState(7);

  const { data: healthData, isLoading: healthLoading, refetch: refetchHealth } = useSystemHealth();
  const { data: metricsData, isLoading: metricsLoading, refetch: refetchMetrics } = useSystemMetrics(metricsDays);
  const { data: diagnosesData, isLoading: diagnosesLoading, refetch: refetchDiagnoses } = useSelfDiagnoses();

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Settings className="h-6 w-6" />
              システムヘルス
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              AIシステムのパフォーマンスと自己診断
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchHealth();
              refetchMetrics();
              refetchDiagnoses();
            }}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Tab navigation */}
        <div className="flex gap-2">
          <Button
            variant={tab === 'health' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('health')}
          >
            <Activity className="mr-1 h-4 w-4" />
            ヘルスサマリー
          </Button>
          <Button
            variant={tab === 'metrics' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('metrics')}
          >
            <Settings className="mr-1 h-4 w-4" />
            メトリクス推移
          </Button>
          <Button
            variant={tab === 'diagnoses' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('diagnoses')}
          >
            <Stethoscope className="mr-1 h-4 w-4" />
            自己診断 ({diagnosesData?.total_count ?? 0})
          </Button>
        </div>

        {/* Health tab */}
        {tab === 'health' && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {healthLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <Card key={i}>
                  <CardContent className="p-4">
                    <Skeleton className="h-12 w-full" />
                  </CardContent>
                </Card>
              ))
            ) : (
              <>
                <Card>
                  <CardContent className="p-4 text-center">
                    <div className="text-2xl font-bold">{healthData?.total_conversations ?? 0}</div>
                    <div className="text-xs text-muted-foreground">総会話数</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4 text-center">
                    <div className="text-2xl font-bold">{healthData?.unique_users ?? 0}</div>
                    <div className="text-xs text-muted-foreground">ユニークユーザー</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4 text-center">
                    <div className="text-2xl font-bold">
                      {healthData?.avg_response_time_ms != null
                        ? `${healthData.avg_response_time_ms}ms`
                        : '-'}
                    </div>
                    <div className="text-xs text-muted-foreground">平均応答時間</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4 text-center">
                    <div className="text-2xl font-bold">
                      {healthData?.p95_response_time_ms != null
                        ? `${healthData.p95_response_time_ms}ms`
                        : '-'}
                    </div>
                    <div className="text-xs text-muted-foreground">P95応答時間</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4 text-center">
                    <div className="text-2xl font-bold">
                      {healthData ? `${healthData.success_rate.toFixed(1)}%` : '-'}
                    </div>
                    <div className="text-xs text-muted-foreground">成功率</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4 text-center">
                    <div className="text-2xl font-bold text-red-500">
                      {healthData?.error_count ?? 0}
                    </div>
                    <div className="text-xs text-muted-foreground">エラー数</div>
                  </CardContent>
                </Card>
                <Card className="col-span-2">
                  <CardContent className="p-4 text-center">
                    <div className="text-sm text-muted-foreground">最新データ日</div>
                    <div className="text-lg font-medium mt-1">
                      {healthData?.latest_date ?? '取得中...'}
                    </div>
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        )}

        {/* Metrics tab */}
        {tab === 'metrics' && (
          <>
            <div className="flex gap-2">
              {[7, 14, 30].map((d) => (
                <Button
                  key={d}
                  variant={metricsDays === d ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setMetricsDays(d)}
                >
                  {d}日間
                </Button>
              ))}
            </div>
            <Card>
              <CardContent className="p-4">
                {metricsLoading ? (
                  <div className="space-y-2">
                    {Array.from({ length: 7 }).map((_, i) => (
                      <Skeleton key={i} className="h-10 w-full" />
                    ))}
                  </div>
                ) : !metricsData?.metrics.length ? (
                  <div className="text-center py-8 text-muted-foreground">
                    メトリクスデータがありません
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-muted-foreground">
                          <th className="text-left p-2">日付</th>
                          <th className="text-right p-2">会話数</th>
                          <th className="text-right p-2">ユーザー</th>
                          <th className="text-right p-2">平均応答(ms)</th>
                          <th className="text-right p-2">成功</th>
                          <th className="text-right p-2">エラー</th>
                          <th className="text-right p-2">信頼度</th>
                        </tr>
                      </thead>
                      <tbody>
                        {metricsData.metrics.map((m) => (
                          <tr key={m.metric_date} className="border-b">
                            <td className="p-2">{m.metric_date}</td>
                            <td className="text-right p-2">{m.total_conversations}</td>
                            <td className="text-right p-2">{m.unique_users}</td>
                            <td className="text-right p-2">
                              {m.avg_response_time_ms ?? '-'}
                            </td>
                            <td className="text-right p-2">{m.success_count}</td>
                            <td className="text-right p-2">
                              {m.error_count > 0 ? (
                                <span className="text-red-500">{m.error_count}</span>
                              ) : (
                                '0'
                              )}
                            </td>
                            <td className="text-right p-2">
                              {m.avg_confidence != null
                                ? `${(m.avg_confidence * 100).toFixed(0)}%`
                                : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {/* Diagnoses tab */}
        {tab === 'diagnoses' && (
          <Card>
            <CardContent className="p-4">
              {diagnosesLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-20 w-full" />
                  ))}
                </div>
              ) : !diagnosesData?.diagnoses.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  自己診断データがありません
                </div>
              ) : (
                <div className="space-y-3">
                  {diagnosesData.diagnoses.map((diag) => (
                    <div key={diag.id} className="rounded-lg border p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{diag.diagnosis_type}</Badge>
                          {diag.period_start && diag.period_end && (
                            <span className="text-xs text-muted-foreground">
                              {diag.period_start.slice(0, 10)} 〜 {diag.period_end.slice(0, 10)}
                            </span>
                          )}
                        </div>
                        <div className="text-right">
                          <span className="text-lg font-bold">
                            {(diag.overall_score * 100).toFixed(0)}%
                          </span>
                          <span className="text-xs text-muted-foreground ml-1">スコア</span>
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground mb-2">
                        処理数: {diag.successful_interactions}/{diag.total_interactions}
                        （成功率: {diag.total_interactions > 0
                          ? ((diag.successful_interactions / diag.total_interactions) * 100).toFixed(1)
                          : 0}%）
                      </div>
                      {diag.identified_weaknesses && diag.identified_weaknesses.length > 0 && (
                        <div className="mt-2">
                          <div className="text-xs font-medium mb-1">検出された課題:</div>
                          <div className="flex flex-wrap gap-1">
                            {diag.identified_weaknesses.map((w, idx) => (
                              <Badge key={idx} variant="secondary" className="text-xs">
                                {w}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </AppLayout>
  );
}
