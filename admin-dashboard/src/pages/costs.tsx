/**
 * Cost Tracking page
 * Displays daily/monthly costs, budget progress, model/tier breakdown
 * Uses /admin/costs/daily, /admin/costs/monthly, /admin/costs/breakdown
 */

import { useQuery } from '@tanstack/react-query';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { api } from '@/lib/api';
import type {
  CostDailyResponse,
  CostMonthlyResponse,
  CostBreakdownResponse,
} from '@/types/api';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const CHART_COLORS = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
];

export function CostsPage() {
  const { data: dailyData, isLoading: dailyLoading, isError: dailyError } =
    useQuery<CostDailyResponse>({
      queryKey: ['costs-daily'],
      queryFn: () => api.costs.getDaily(30),
    });

  const { data: monthlyData, isLoading: monthlyLoading, isError: monthlyError } =
    useQuery<CostMonthlyResponse>({
      queryKey: ['costs-monthly'],
      queryFn: () => api.costs.getMonthly(),
    });

  const { data: breakdownData, isLoading: breakdownLoading, isError: breakdownError } =
    useQuery<CostBreakdownResponse>({
      queryKey: ['costs-breakdown'],
      queryFn: () => api.costs.getBreakdown(30),
    });

  const isLoading = dailyLoading || monthlyLoading || breakdownLoading;
  const isError = dailyError || monthlyError || breakdownError;

  const dailyChartData = (dailyData?.daily ?? []).map((d) => ({
    ...d,
    dateLabel: format(parseISO(d.date), 'M/d'),
  }));

  // Total cost from daily data
  const totalCost30d = (dailyData?.daily ?? []).reduce(
    (sum, d) => sum + d.cost,
    0
  );
  const avgDailyCost =
    dailyChartData.length > 0 ? totalCost30d / dailyChartData.length : 0;

  // Current month budget from monthly data
  const currentMonth = monthlyData?.months?.[0];

  const modelPieData = (breakdownData?.by_model ?? []).map((m) => ({
    name: m.model.split('/').pop() ?? m.model,
    value: m.cost,
    pct: m.pct,
    requests: m.requests,
  }));

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold">Cost Tracking</h1>
          <p className="text-muted-foreground">
            AI usage costs, budget monitoring, and breakdowns
          </p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-96">
            <div className="animate-pulse text-muted-foreground">
              Loading cost data...
            </div>
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center h-96">
            <div className="text-destructive">
              Failed to load cost data. Please try again later.
            </div>
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid gap-4 md:grid-cols-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Total (30d)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ${totalCost30d.toFixed(2)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Daily Average
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ${avgDailyCost.toFixed(2)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Current Month
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ${(currentMonth?.total_cost ?? 0).toFixed(2)}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {currentMonth?.year_month ?? '-'}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Budget Status
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {currentMonth?.budget != null ? (
                    <>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={
                            currentMonth.status === 'exceeded'
                              ? 'destructive'
                              : 'secondary'
                          }
                        >
                          {currentMonth.status === 'exceeded'
                            ? 'Over Budget'
                            : currentMonth.status === 'warning'
                              ? 'Warning'
                              : 'On Track'}
                        </Badge>
                      </div>
                      {/* Budget progress bar */}
                      <div className="mt-3 w-full bg-secondary rounded-full h-2">
                        <div
                          className={`h-2 rounded-full transition-all ${
                            currentMonth.status === 'exceeded'
                              ? 'bg-destructive'
                              : currentMonth.status === 'warning'
                                ? 'bg-yellow-500'
                                : 'bg-primary'
                          }`}
                          style={{
                            width: `${Math.min(
                              ((currentMonth.total_cost / currentMonth.budget) * 100),
                              100
                            )}%`,
                          }}
                        />
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        ${currentMonth.total_cost.toFixed(2)} / $
                        {currentMonth.budget.toFixed(0)}
                      </p>
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No budget set
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Daily Cost Chart */}
            <Card>
              <CardHeader>
                <CardTitle>Daily Cost (30 days)</CardTitle>
              </CardHeader>
              <CardContent>
                {dailyChartData.length === 0 ? (
                  <div className="flex items-center justify-center h-64 text-muted-foreground">
                    No daily cost data
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={350}>
                    <BarChart data={dailyChartData}>
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
                          'Cost',
                        ]}
                      />
                      <Bar
                        dataKey="cost"
                        fill="var(--color-chart-1)"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Breakdown */}
            <Tabs defaultValue="model">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>Cost Breakdown (30d)</CardTitle>
                  <TabsList>
                    <TabsTrigger value="model">By Model</TabsTrigger>
                    <TabsTrigger value="tier">By Tier</TabsTrigger>
                  </TabsList>
                </CardHeader>
                <CardContent>
                  <TabsContent value="model" className="mt-0">
                    <div className="grid gap-6 lg:grid-cols-2">
                      {/* Pie Chart */}
                      {modelPieData.length > 0 && (
                        <ResponsiveContainer width="100%" height={300}>
                          <PieChart>
                            <Pie
                              data={modelPieData}
                              cx="50%"
                              cy="50%"
                              innerRadius={60}
                              outerRadius={100}
                              paddingAngle={4}
                              dataKey="value"
                              label={({ name }) => name}
                              labelLine={false}
                            >
                              {modelPieData.map((_, index) => (
                                <Cell
                                  key={`cell-${index}`}
                                  fill={CHART_COLORS[index % CHART_COLORS.length]}
                                />
                              ))}
                            </Pie>
                            <Tooltip
                              contentStyle={{
                                backgroundColor: 'var(--color-card)',
                                border: '1px solid var(--color-border)',
                                borderRadius: '8px',
                              }}
                              formatter={(value: number | undefined) => [
                                `$${(value ?? 0).toFixed(4)}`,
                                'Cost',
                              ]}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      )}
                      {/* Table */}
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Model</TableHead>
                            <TableHead className="text-right">Cost</TableHead>
                            <TableHead className="text-right">Requests</TableHead>
                            <TableHead className="text-right">Share</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {(breakdownData?.by_model ?? []).map((m) => (
                            <TableRow key={m.model}>
                              <TableCell className="font-medium">
                                {m.model}
                              </TableCell>
                              <TableCell className="text-right">
                                ${m.cost.toFixed(4)}
                              </TableCell>
                              <TableCell className="text-right">
                                {m.requests.toLocaleString()}
                              </TableCell>
                              <TableCell className="text-right">
                                <Badge variant="secondary">
                                  {m.pct.toFixed(1)}%
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </TabsContent>
                  <TabsContent value="tier" className="mt-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Tier</TableHead>
                          <TableHead className="text-right">Cost</TableHead>
                          <TableHead className="text-right">Requests</TableHead>
                          <TableHead className="text-right">Share</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {(breakdownData?.by_tier ?? []).map((t) => (
                          <TableRow key={t.tier}>
                            <TableCell className="font-medium">
                              {t.tier}
                            </TableCell>
                            <TableCell className="text-right">
                              ${t.cost.toFixed(4)}
                            </TableCell>
                            <TableCell className="text-right">
                              {t.requests.toLocaleString()}
                            </TableCell>
                            <TableCell className="text-right">
                              <Badge variant="secondary">
                                {t.pct.toFixed(1)}%
                              </Badge>
                            </TableCell>
                          </TableRow>
                        ))}
                        {(breakdownData?.by_tier ?? []).length === 0 && (
                          <TableRow>
                            <TableCell
                              colSpan={4}
                              className="text-center text-muted-foreground h-24"
                            >
                              No tier data
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </TabsContent>
                </CardContent>
              </Card>
            </Tabs>

            {/* Monthly Summary Table */}
            <Card>
              <CardHeader>
                <CardTitle>Monthly Summary</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Month</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                      <TableHead className="text-right">Requests</TableHead>
                      <TableHead className="text-right">Budget</TableHead>
                      <TableHead className="text-right">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(monthlyData?.months ?? []).map((m) => (
                      <TableRow key={m.year_month}>
                        <TableCell className="font-medium">
                          {m.year_month}
                        </TableCell>
                        <TableCell className="text-right">
                          ${m.total_cost.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right">
                          {m.requests.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right">
                          {m.budget != null ? `$${m.budget.toFixed(0)}` : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Badge
                            variant={
                              m.status === 'exceeded'
                                ? 'destructive'
                                : 'secondary'
                            }
                          >
                            {m.status}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                    {(monthlyData?.months ?? []).length === 0 && (
                      <TableRow>
                        <TableCell
                          colSpan={5}
                          className="text-center text-muted-foreground h-24"
                        >
                          No monthly data
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
