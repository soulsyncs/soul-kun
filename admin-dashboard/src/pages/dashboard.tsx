/**
 * Dashboard page
 * Displays KPIs, alerts, insights from /admin/dashboard/summary
 * Brain metrics chart from /admin/brain/metrics
 */

import { useState } from 'react';
import { Link } from '@tanstack/react-router';
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
import type { DashboardSummaryResponse, BrainMetricsResponse, GoalStatsResponse, TaskOverviewStats } from '@/types/api';
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
  TrendingUp,
  Target,
  Flame,
  AlertOctagon,
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

  const { data: goalStats } = useQuery<GoalStatsResponse>({
    queryKey: ['goal-stats'],
    queryFn: () => api.goals.getStats(),
  });

  const { data: taskStats } = useQuery<TaskOverviewStats>({
    queryKey: ['task-overview'],
    queryFn: () => api.tasks.getOverview(),
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

  const totalCost = chartData.reduce((sum, m) => sum + m.cost, 0);
  const totalConversations = chartData.reduce((sum, m) => sum + m.conversations, 0);
  const costPerConv = totalConversations > 0 ? Math.round(totalCost / totalConversations) : 0;

  const urgentAlerts = alerts
    .filter((a) => !a.is_resolved)
    .sort((a, b) => (a.severity === 'critical' ? -1 : b.severity === 'critical' ? 1 : 0))
    .slice(0, 3);

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header with period selector */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl md:text-3xl font-bold">ダッシュボード</h1>
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

        {/* Executive KPI Section */}
        <div className="grid gap-4 md:grid-cols-3">
          {/* ROI: 1会話あたりコスト */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                1会話あたりコスト（ROI）
                <InfoTooltip text="AIにかかった費用を会話数で割った値です。低いほどコスト効率が良い状態です" />
              </CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">¥{costPerConv.toLocaleString()}</div>
              <p className="text-xs text-muted-foreground">
                {PERIOD_LABELS[period]}の合計 ¥{Math.round(totalCost).toLocaleString()} / {totalConversations.toLocaleString()}会話
              </p>
            </CardContent>
          </Card>

          {/* 全社目標達成率 */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                全社目標達成率
                <InfoTooltip text="現在進行中の全ての目標のうち、達成済みの割合です" />
              </CardTitle>
              <Target className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {goalStats ? `${Math.round(goalStats.completion_rate)}%` : '—'}
              </div>
              <p className="text-xs text-muted-foreground">
                {goalStats
                  ? `達成 ${goalStats.completed_goals}件 / 全体 ${goalStats.total_goals}件`
                  : 'データ取得中...'}
              </p>
            </CardContent>
          </Card>

          {/* トップ3緊急案件 */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                緊急対応が必要な案件
                <InfoTooltip text="未解決のアラートのうち、優先度が高い順に最大3件を表示します" />
              </CardTitle>
              <Flame className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              {urgentAlerts.length === 0 ? (
                <p className="text-sm text-green-600 font-medium">緊急案件なし ✓</p>
              ) : (
                <div className="space-y-1.5">
                  {urgentAlerts.map((alert) => (
                    <div key={alert.id} className="flex items-center gap-2 text-sm">
                      <Badge
                        variant={alert.severity === 'critical' ? 'destructive' : 'secondary'}
                        className="text-xs shrink-0"
                      >
                        {alert.severity === 'critical' ? '緊急' : '警告'}
                      </Badge>
                      <span className="truncate text-xs">{alert.alert_type}</span>
                    </div>
                  ))}
                  {alerts.filter((a) => !a.is_resolved).length > 3 && (
                    <p className="text-xs text-muted-foreground">
                      他 {alerts.filter((a) => !a.is_resolved).length - 3}件の未解決アラートがあります
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
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
            tooltip="今日のAI利用にかかった費用（日本円）です"
          />
          <KpiCard
            title="予算残高"
            value={kpis?.monthly_budget_remaining ?? 0}
            icon={Activity}
            format="currency"
            tooltip="今月の予算のうち、まだ使える残りの金額です（日本円）"
          />
          <KpiCard
            title="アクティブアラート"
            value={kpis?.active_alerts_count ?? 0}
            icon={Zap}
            tooltip="現在対応が必要な警告の数です。0が理想です"
          />
        </div>

        {/* ⑤ 決断の詰まりアラート */}
        {(taskStats?.chatwork_tasks?.overdue ?? 0) > 0 && (
          <Card className="border-orange-400 border-2">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <AlertOctagon className="h-5 w-5 text-orange-500" />
                決断が止まっているタスク
                <InfoTooltip text="締め切りを過ぎているのに未完了のタスクです。誰かの判断待ちや担当者不明になっている可能性があります（AIによる検知）" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-6">
                <div className="text-center">
                  <div className="text-3xl font-bold text-orange-500">{taskStats?.chatwork_tasks?.overdue ?? 0}</div>
                  <div className="text-xs text-muted-foreground">期限超過</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-muted-foreground">{taskStats?.chatwork_tasks?.open ?? 0}</div>
                  <div className="text-xs text-muted-foreground">未完了合計</div>
                </div>
                <div className="flex-1 text-sm text-muted-foreground">
                  <p>期限が過ぎているタスクがあります。</p>
                  <p className="mt-1">
                    <Link to="/tasks" className="text-primary underline">タスク一覧</Link>で確認して、担当者に声をかけてください。
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
        {taskStats?.chatwork_tasks?.overdue === 0 && (taskStats.chatwork_tasks.open ?? 0) > 0 && (
          <Card className="border-green-400 border">
            <CardContent className="py-4">
              <div className="flex items-center gap-3">
                <span className="text-xl">✅</span>
                <div>
                  <p className="text-sm font-medium text-green-700">期限切れタスクはありません</p>
                  <p className="text-xs text-muted-foreground">
                    未完了 {taskStats?.chatwork_tasks?.open}件 — すべて期限内です
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

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
                          tickFormatter={(v: number) => `¥${v.toFixed(0)}`}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'var(--color-card)',
                            border: '1px solid var(--color-border)',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number | undefined) => [
                            `¥${(value ?? 0).toFixed(0)}`,
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
