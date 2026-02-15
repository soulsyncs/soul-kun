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
            <h1 className="text-3xl font-bold">Brain Analytics</h1>
            <p className="text-muted-foreground">
              LLM Brain decision metrics and performance
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
                {d}d
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-96">
            <div className="animate-pulse text-muted-foreground">
              Loading analytics...
            </div>
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center h-96">
            <div className="text-destructive">
              Failed to load brain analytics. Please try again later.
            </div>
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Total Conversations ({days}d)
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
                    Avg Latency
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
                    Total Cost ({days}d)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ${totalCost.toFixed(4)}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Charts */}
            <Tabs defaultValue="conversations">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>Daily Metrics</CardTitle>
                  <TabsList>
                    <TabsTrigger value="conversations">Conversations</TabsTrigger>
                    <TabsTrigger value="latency">Latency</TabsTrigger>
                    <TabsTrigger value="errors">Error Rate</TabsTrigger>
                  </TabsList>
                </CardHeader>
                <CardContent>
                  {chartData.length === 0 ? (
                    <div className="flex items-center justify-center h-64 text-muted-foreground">
                      No data for this period
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
                                'Avg Latency',
                              ]}
                            />
                            <Legend />
                            <Line
                              type="monotone"
                              dataKey="avg_latency_ms"
                              stroke="var(--color-chart-2)"
                              strokeWidth={2}
                              dot={{ r: 4 }}
                              name="Avg Latency"
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
                                'Error Rate',
                              ]}
                            />
                            <Line
                              type="monotone"
                              dataKey="error_pct"
                              stroke="var(--color-destructive)"
                              strokeWidth={2}
                              dot={{ r: 4 }}
                              name="Error Rate"
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
                  Recent Decision Logs
                  <span className="text-sm font-normal text-muted-foreground ml-2">
                    ({logsData?.total_count ?? 0} total)
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Time</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead className="text-right">Confidence</TableHead>
                      <TableHead className="text-right">Duration</TableHead>
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
                          No decision logs available
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
