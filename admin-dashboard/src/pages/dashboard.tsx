/**
 * Dashboard page
 * Displays KPIs, alerts, insights from /admin/dashboard/summary
 * Brain metrics chart from /admin/brain/metrics
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { api } from '@/lib/api';
import type { DashboardSummaryResponse, BrainMetricsResponse } from '@/types/api';
import { AppLayout } from '@/components/layout/app-layout';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import {
  MessageSquare,
  AlertTriangle,
  DollarSign,
  Clock,
  Activity,
  Zap,
} from 'lucide-react';

type Period = 'today' | '7d' | '30d';

const PERIOD_LABELS: Record<Period, string> = {
  today: '今日',
  '7d': '7日間',
  '30d': '30日間',
};

export function DashboardPage() {
  const [period, setPeriod] = useState<Period>('7d');

  const { data: summaryData, isLoading: summaryLoading, isError: summaryError } =
    useQuery<DashboardSummaryResponse>({
      queryKey: ['dashboard-summary', period],
      queryFn: () => api.dashboard.getSummary(period),
    });

  const brainDays = period === 'today' ? 1 : period === '7d' ? 7 : 30;
  const { data: metricsData, isLoading: metricsLoading } =
    useQuery<BrainMetricsResponse>({
      queryKey: ['brain-metrics-dashboard', brainDays],
      queryFn: () => api.brain.getMetrics(brainDays),
    });

  if (summaryLoading) {
    return (
      <AppLayout>
        <div className="flex items-center justify-center h-96">
          <div className="animate-pulse text-muted-foreground">
            ダッシュボードを読み込み中...
          </div>
        </div>
      </AppLayout>
    );
  }

  if (summaryError) {
    return (
      <AppLayout>
        <div className="flex items-center justify-center h-96">
          <div className="text-destructive">
            データの読み込みに失敗しました。しばらくしてからお試しください。
          </div>
        </div>
      </AppLayout>
    );
  }

  const kpis = summaryData?.kpis;
  const alerts = summaryData?.recent_alerts ?? [];
  const insights = summaryData?.recent_insights ?? [];

  const chartData = (metricsData?.metrics ?? []).map((m) => ({
    ...m,
    dateLabel: format(parseISO(m.date), 'M/d'),
  }));

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header with period selector */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">ダッシュボード</h1>
            <p className="text-muted-foreground">
              ソウルくんのパフォーマンス概要
            </p>
          </div>
          <div className="flex gap-2">
            {(['today', '7d', '30d'] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  period === p
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-secondary text-secondary-foreground hover:bg-accent'
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </div>

        {/* KPI Grid */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <KpiCard
            title="会話数"
            value={kpis?.total_conversations ?? 0}
            icon={MessageSquare}
            tooltip="ソウルくんがユーザーと行った会話の回数です"
          />
          <KpiCard
            title="平均応答時間"
            value={kpis?.avg_response_time_ms ?? 0}
            icon={Clock}
            format="ms"
            tooltip="ソウルくんが質問を受けてから返答するまでの平均時間です（ミリ秒 = 1/1000秒）"
          />
          <KpiCard
            title="エラー率"
            value={((kpis?.error_rate ?? 0) * 100).toFixed(2) + '%'}
            icon={AlertTriangle}
            tooltip="全リクエストのうち、エラーが発生した割合です。低いほど安定しています"
          />
          <KpiCard
            title="本日のコスト"
            value={kpis?.total_cost_today ?? 0}
            icon={DollarSign}
            format="currency"
            tooltip="今日のAI利用にかかった費用（USドル）です"
          />
          <KpiCard
            title="予算残高"
            value={kpis?.monthly_budget_remaining ?? 0}
            icon={Activity}
            format="currency"
            tooltip="今月の予算のうち、まだ使える残りの金額です"
          />
          <KpiCard
            title="アクティブアラート"
            value={kpis?.active_alerts_count ?? 0}
            icon={Zap}
            tooltip="現在対応が必要な警告の数です。0が理想です"
          />
        </div>

        {/* Trend Charts */}
        <Tabs defaultValue="conversations">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>
                AI脳メトリクス推移
                <InfoTooltip text="ソウルくんのAI脳の動作状況を日ごとにグラフで表示しています" />
              </CardTitle>
              <TabsList>
                <TabsTrigger value="conversations">会話数</TabsTrigger>
                <TabsTrigger value="latency">レイテンシ</TabsTrigger>
                <TabsTrigger value="cost">コスト</TabsTrigger>
              </TabsList>
            </CardHeader>
            <CardContent>
              {metricsLoading ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground">
                  グラフを読み込み中...
                </div>
              ) : chartData.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground">
                  この期間のデータがありません
                </div>
              ) : (
                <>
                  <TabsContent value="conversations" className="mt-0">
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis dataKey="dateLabel" className="text-xs fill-muted-foreground" />
                        <YAxis className="text-xs fill-muted-foreground" />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'var(--color-card)',
                            border: '1px solid var(--color-border)',
                            borderRadius: '8px',
                          }}
                        />
                        <Bar
                          dataKey="conversations"
                          fill="var(--color-chart-1)"
                          radius={[4, 4, 0, 0]}
                          name="会話数"
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </TabsContent>
                  <TabsContent value="latency" className="mt-0">
                    <ResponsiveContainer width="100%" height={300}>
                      <AreaChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis dataKey="dateLabel" className="text-xs fill-muted-foreground" />
                        <YAxis
                          className="text-xs fill-muted-foreground"
                          tickFormatter={(v: number) => `${v.toFixed(0)}ms`}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'var(--color-card)',
                            border: '1px solid var(--color-border)',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number | undefined) => [
                            `${(value ?? 0).toFixed(1)}ms`,
                            '平均レイテンシ',
                          ]}
                        />
                        <Area
                          type="monotone"
                          dataKey="avg_latency_ms"
                          stroke="var(--color-chart-2)"
                          fill="var(--color-chart-2)"
                          fillOpacity={0.2}
                          strokeWidth={2}
                          name="平均レイテンシ"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </TabsContent>
                  <TabsContent value="cost" className="mt-0">
                    <ResponsiveContainer width="100%" height={300}>
                      <AreaChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis dataKey="dateLabel" className="text-xs fill-muted-foreground" />
                        <YAxis
                          className="text-xs fill-muted-foreground"
                          tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'var(--color-card)',
                            border: '1px solid var(--color-border)',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number | undefined) => [
                            `$${(value ?? 0).toFixed(4)}`,
                            'コスト',
                          ]}
                        />
                        <Area
                          type="monotone"
                          dataKey="cost"
                          stroke="var(--color-chart-4)"
                          fill="var(--color-chart-4)"
                          fillOpacity={0.2}
                          strokeWidth={2}
                          name="コスト"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </TabsContent>
                </>
              )}
            </CardContent>
          </Card>
        </Tabs>

        {/* Alerts and Insights */}
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Recent Alerts */}
          <Card>
            <CardHeader>
              <CardTitle>
                最近のアラート
                <InfoTooltip text="システムが検知した異常や注意が必要な事象の一覧です" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {alerts.length === 0 ? (
                <p className="text-sm text-muted-foreground">最近のアラートはありません</p>
              ) : (
                <div className="space-y-3">
                  {alerts.map((alert) => (
                    <div
                      key={alert.id}
                      className="flex items-start gap-3 rounded-lg border p-3"
                    >
                      <Badge
                        variant={
                          alert.severity === 'critical'
                            ? 'destructive'
                            : 'secondary'
                        }
                        className="mt-0.5"
                      >
                        {alert.severity}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">{alert.alert_type}</p>
                        <p className="text-xs text-muted-foreground truncate">
                          {alert.message}
                        </p>
                      </div>
                      {alert.is_resolved && (
                        <Badge variant="secondary" className="text-green-600">
                          解決済み
                        </Badge>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Recent Insights */}
          <Card>
            <CardHeader>
              <CardTitle>
                最近のインサイト
                <InfoTooltip text="ソウルくんが自動的に発見した傾向や改善提案です" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {insights.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  最近のインサイトはありません
                </p>
              ) : (
                <div className="space-y-3">
                  {insights.map((insight) => (
                    <div
                      key={insight.id}
                      className="rounded-lg border p-3"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="secondary">{insight.insight_type}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {format(parseISO(insight.created_at), 'M/d HH:mm')}
                        </span>
                      </div>
                      <p className="text-sm font-medium">{insight.title}</p>
                      <p className="text-xs text-muted-foreground line-clamp-2">
                        {insight.summary}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppLayout>
  );
}
