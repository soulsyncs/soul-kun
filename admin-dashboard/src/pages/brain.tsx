/**
 * Brain Analytics page
 * Displays Brain metrics (time series), decision logs, and performance stats
 * Uses /admin/brain/metrics and /admin/brain/logs
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { api } from '@/lib/api';
import type { BrainMetricsResponse, BrainLogsResponse } from '@/types/api';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { InfoTooltip } from '@/components/ui/info-tooltip';

export function BrainPage() {
  const [days, setDays] = useState(7);

  const { data: metricsData, isLoading: metricsLoading, isError: metricsError } =
    useQuery<BrainMetricsResponse>({
      queryKey: ['brain-metrics', days],
      queryFn: () => api.brain.getMetrics(days),
    });

  const { data: logsData, isLoading: logsLoading, isError: logsError } =
    useQuery<BrainLogsResponse>({
      queryKey: ['brain-logs'],
      queryFn: () => api.brain.getLogs(50, 0),
    });

  const isLoading = metricsLoading || logsLoading;
  const isError = metricsError || logsError;

  const chartData = (metricsData?.metrics ?? []).map((m) => ({
    ...m,
    dateLabel: format(parseISO(m.date), 'M/d'),
    error_pct: m.error_rate * 100,
  }));

  // Summary stats from metrics
  const totalConversations = (metricsData?.metrics ?? []).reduce(
    (sum, m) => sum + m.conversations,
    0
  );
  const totalCost = (metricsData?.metrics ?? []).reduce(
    (sum, m) => sum + m.cost,
    0
  );
  const avgLatency =
    chartData.length > 0
      ? chartData.reduce((sum, m) => sum + m.avg_latency_ms, 0) /
        chartData.length
      : 0;

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">AI脳分析</h1>
            <p className="text-muted-foreground">
              ソウルくんのAI脳（LLM Brain）の判断性能と実績
            </p>
          </div>
          <div className="flex gap-2">
            {[7, 14, 30].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  days === d
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-secondary text-secondary-foreground hover:bg-accent'
                }`}
              >
                {d}日間
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-96">
            <div className="animate-pulse text-muted-foreground">
              分析データを読み込み中...
            </div>
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center h-96">
            <div className="text-destructive">
              データの読み込みに失敗しました。しばらくしてからお試しください。
            </div>
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    総会話数（{days}日間）
                    <InfoTooltip text="選択した期間にソウルくんが処理した会話の合計回数です" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {totalConversations.toLocaleString()}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    平均レイテンシ
                    <InfoTooltip text="AI脳が判断を下すまでにかかる平均時間です。短いほど高速に応答しています" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {avgLatency.toFixed(0)}ms
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    総コスト（{days}日間）
                    <InfoTooltip text="AI利用にかかった費用の合計（日本円）です" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ¥{totalCost.toFixed(0)}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Charts */}
            <Tabs defaultValue="conversations">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>
                    日別メトリクス
                    <InfoTooltip text="日ごとの推移をグラフで確認できます。タブで表示項目を切り替えられます" />
                  </CardTitle>
                  <TabsList>
                    <TabsTrigger value="conversations">会話数</TabsTrigger>
                    <TabsTrigger value="latency">レイテンシ</TabsTrigger>
                    <TabsTrigger value="errors">エラー率</TabsTrigger>
                  </TabsList>
                </CardHeader>
                <CardContent>
                  {chartData.length === 0 ? (
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
                          <LineChart data={chartData}>
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
                            <Legend />
                            <Line
                              type="monotone"
                              dataKey="avg_latency_ms"
                              stroke="var(--color-chart-2)"
                              strokeWidth={2}
                              dot={{ r: 4 }}
                              name="平均レイテンシ"
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </TabsContent>
                      <TabsContent value="errors" className="mt-0">
                        <ResponsiveContainer width="100%" height={300}>
                          <LineChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                            <XAxis dataKey="dateLabel" className="text-xs fill-muted-foreground" />
                            <YAxis
                              className="text-xs fill-muted-foreground"
                              tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                            />
                            <Tooltip
                              contentStyle={{
                                backgroundColor: 'var(--color-card)',
                                border: '1px solid var(--color-border)',
                                borderRadius: '8px',
                              }}
                              formatter={(value: number | undefined) => [
                                `${(value ?? 0).toFixed(2)}%`,
                                'エラー率',
                              ]}
                            />
                            <Line
                              type="monotone"
                              dataKey="error_pct"
                              stroke="var(--color-destructive)"
                              strokeWidth={2}
                              dot={{ r: 4 }}
                              name="エラー率"
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </TabsContent>
                    </>
                  )}
                </CardContent>
              </Card>
            </Tabs>

            {/* Decision Logs Table */}
            <Card>
              <CardHeader>
                <CardTitle>
                  最近の判断ログ
                  <InfoTooltip text="ソウルくんのAI脳が行った判断の履歴です。どんなアクションを、どれくらいの確信度で決定したかがわかります" />
                  <span className="text-sm font-normal text-muted-foreground ml-2">
                    （全{logsData?.total_count ?? 0}件）
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>日時</TableHead>
                      <TableHead>アクション</TableHead>
                      <TableHead className="text-right">確信度</TableHead>
                      <TableHead className="text-right">処理時間</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(logsData?.logs ?? []).map((log) => (
                      <TableRow key={log.id}>
                        <TableCell className="text-muted-foreground">
                          {format(parseISO(log.created_at), 'M/d HH:mm:ss')}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              log.selected_action === 'error'
                                ? 'destructive'
                                : 'secondary'
                            }
                          >
                            {log.selected_action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          {log.decision_confidence != null
                            ? `${(log.decision_confidence * 100).toFixed(0)}%`
                            : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          {log.total_time_ms != null
                            ? `${log.total_time_ms.toFixed(0)}ms`
                            : '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                    {(logsData?.logs ?? []).length === 0 && (
                      <TableRow>
                        <TableCell
                          colSpan={4}
                          className="text-center text-muted-foreground h-24"
                        >
                          判断ログがありません
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </AppLayout>
  );
}
