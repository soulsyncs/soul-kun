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
import { TrendingUp } from 'lucide-react';
import { api } from '@/lib/api';
import type {
  CostDailyResponse,
  CostMonthlyResponse,
  CostBreakdownResponse,
  AiRoiResponse,
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
import { InfoTooltip } from '@/components/ui/info-tooltip';

const CHART_COLORS = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
];

const STATUS_LABELS: Record<string, string> = {
  exceeded: '予算超過',
  warning: '注意',
  ok: '順調',
  on_track: '順調',
};

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

  const { data: roiData } =
    useQuery<AiRoiResponse>({
      queryKey: ['costs-ai-roi'],
      queryFn: () => api.costs.getAiRoi(30),
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
          <h1 className="text-3xl font-bold">コスト管理</h1>
          <p className="text-muted-foreground">
            AI利用コスト、予算管理、内訳分析
          </p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-96">
            <div className="animate-pulse text-muted-foreground">
              コストデータを読み込み中...
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
            <div className="grid gap-4 md:grid-cols-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    合計（30日間）
                    <InfoTooltip text="過去30日間にAI利用でかかった費用の合計です" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ¥{totalCost30d.toFixed(0)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    日次平均
                    <InfoTooltip text="1日あたりの平均コストです" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ¥{avgDailyCost.toFixed(0)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    今月
                    <InfoTooltip text="今月の累計コストです" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    ¥{(currentMonth?.total_cost ?? 0).toFixed(0)}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {currentMonth?.year_month ?? '-'}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    予算状況
                    <InfoTooltip text="今月の予算に対する利用状況です。バーが右端に近いほど予算を使い切りそうです" />
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
                          {STATUS_LABELS[currentMonth.status] ?? currentMonth.status}
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
                        ¥{currentMonth.total_cost.toFixed(0)} / ¥
                        {currentMonth.budget.toFixed(0)}
                      </p>
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      予算が設定されていません
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Daily Cost Chart */}
            <Card>
              <CardHeader>
                <CardTitle>
                  日別コスト（30日間）
                  <InfoTooltip text="過去30日間のAI利用コストを日ごとに棒グラフで表示しています" />
                </CardTitle>
              </CardHeader>
              <CardContent>
                {dailyChartData.length === 0 ? (
                  <div className="flex items-center justify-center h-64 text-muted-foreground">
                    日別コストデータがありません
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={350}>
                    <BarChart data={dailyChartData}>
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
                      <Bar
                        dataKey="cost"
                        fill="var(--color-chart-1)"
                        radius={[4, 4, 0, 0]}
                        name="コスト"
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
                  <CardTitle>
                    コスト内訳（30日間）
                    <InfoTooltip text="どのAIモデルにどれくらいの費用がかかっているかの内訳です" />
                  </CardTitle>
                  <TabsList>
                    <TabsTrigger value="model">モデル別</TabsTrigger>
                    <TabsTrigger value="tier">ティア別</TabsTrigger>
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
                                `¥${(value ?? 0).toFixed(0)}`,
                                'コスト',
                              ]}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      )}
                      {/* Table */}
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>モデル</TableHead>
                            <TableHead className="text-right">コスト</TableHead>
                            <TableHead className="text-right">リクエスト数</TableHead>
                            <TableHead className="text-right">割合</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {(breakdownData?.by_model ?? []).map((m) => (
                            <TableRow key={m.model}>
                              <TableCell className="font-medium">
                                {m.model}
                              </TableCell>
                              <TableCell className="text-right">
                                ¥{m.cost.toFixed(0)}
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
                          <TableHead>ティア</TableHead>
                          <TableHead className="text-right">コスト</TableHead>
                          <TableHead className="text-right">リクエスト数</TableHead>
                          <TableHead className="text-right">割合</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {(breakdownData?.by_tier ?? []).map((t) => (
                          <TableRow key={t.tier}>
                            <TableCell className="font-medium">
                              {t.tier}
                            </TableCell>
                            <TableCell className="text-right">
                              ¥{t.cost.toFixed(0)}
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
                              ティアデータがありません
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </TabsContent>
                </CardContent>
              </Card>
            </Tabs>

            {/* AI ROI Card */}
            {roiData && (
              <Card className="border-2 border-green-200 bg-green-50 dark:bg-green-950 dark:border-green-800">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-green-800 dark:text-green-200">
                    <TrendingUp className="h-5 w-5" />
                    AI費用対効果（ROI）
                    <InfoTooltip text="AIにかけた費用と、それによって削減できた人件費を比較した投資対効果です（AIによる推定値）" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-6 mb-4">
                    <div className="text-center">
                      <div className="text-xs text-muted-foreground mb-1">AI費用（30日）</div>
                      <div className="text-2xl font-bold text-destructive">
                        ¥{Math.round(roiData.total_cost_jpy).toLocaleString()}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-muted-foreground mb-1">削減できた人件費（推定）</div>
                      <div className="text-2xl font-bold text-green-700 dark:text-green-300">
                        ¥{Math.round(roiData.labor_saved_jpy).toLocaleString()}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-muted-foreground mb-1">ROI倍率</div>
                      <div className="text-3xl font-bold text-green-700 dark:text-green-300">
                        {roiData.roi_multiplier.toFixed(1)}x
                      </div>
                      <div className="text-xs text-muted-foreground">費用の{roiData.roi_multiplier.toFixed(1)}倍の価値</div>
                    </div>
                  </div>
                  <div className="text-sm text-muted-foreground mb-3">
                    削減工数: <strong>{roiData.time_saved_hours.toFixed(1)}時間</strong>（{roiData.total_requests.toLocaleString()}リクエスト × 平均処理時間）
                  </div>
                  {roiData.by_tier.length > 0 && (
                    <div className="space-y-2">
                      {roiData.by_tier.map((t) => (
                        <div key={t.tier} className="flex items-center gap-3 text-sm">
                          <span className="w-24 font-medium text-muted-foreground">{t.tier}</span>
                          <div className="flex-1 bg-secondary rounded-full h-2">
                            <div
                              className="h-2 rounded-full bg-green-500"
                              style={{
                                width: `${roiData.labor_saved_jpy > 0 ? Math.min((t.labor_saved_jpy / roiData.labor_saved_jpy) * 100, 100) : 0}%`,
                              }}
                            />
                          </div>
                          <span className="w-28 text-right text-xs">
                            ¥{Math.round(t.labor_saved_jpy).toLocaleString()} 節約
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* Monthly Summary Table */}
            <Card>
              <CardHeader>
                <CardTitle>
                  月次サマリー
                  <InfoTooltip text="月ごとのコスト・リクエスト数・予算消化状況の一覧です" />
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>月</TableHead>
                      <TableHead className="text-right">コスト</TableHead>
                      <TableHead className="text-right">リクエスト数</TableHead>
                      <TableHead className="text-right">予算</TableHead>
                      <TableHead className="text-right">ステータス</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(monthlyData?.months ?? []).map((m) => (
                      <TableRow key={m.year_month}>
                        <TableCell className="font-medium">
                          {m.year_month}
                        </TableCell>
                        <TableCell className="text-right">
                          ¥{m.total_cost.toFixed(0)}
                        </TableCell>
                        <TableCell className="text-right">
                          {m.requests.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right">
                          {m.budget != null ? `¥${m.budget.toFixed(0)}` : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Badge
                            variant={
                              m.status === 'exceeded'
                                ? 'destructive'
                                : 'secondary'
                            }
                          >
                            {STATUS_LABELS[m.status] ?? m.status}
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
                          月次データがありません
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
