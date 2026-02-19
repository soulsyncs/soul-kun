/**
 * Goals management page
 * Shows goal list with stats summary and detail panel
 * Phase 3 追加: 目標未来予測タブ
 */

import { useState } from 'react';
import {
  Target,
  RefreshCw,
  TrendingUp,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Telescope,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { useGoalsList, useGoalStats, useGoalDetail, useGoalForecast } from '@/hooks/use-goals';
import type { GoalForecastItem } from '@/types/api';

const STATUS_LABELS: Record<string, string> = {
  active: '進行中',
  completed: '完了',
  paused: '一時停止',
  cancelled: 'キャンセル',
};

const STATUS_COLORS: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  active: 'default',
  completed: 'secondary',
  paused: 'outline',
  cancelled: 'destructive',
};

// 予測ステータスの表示設定
const FORECAST_CONFIG: Record<string, { label: string; color: string; emoji: string }> = {
  ahead:    { label: '順調（前倒し）', color: 'text-green-600',  emoji: '🟢' },
  on_track: { label: '予定通り',       color: 'text-blue-600',   emoji: '🔵' },
  at_risk:  { label: '遅れ気味',       color: 'text-yellow-600', emoji: '🟡' },
  stalled:  { label: '停滞中',         color: 'text-red-600',    emoji: '🔴' },
  no_data:  { label: 'データ不足',     color: 'text-gray-400',   emoji: '⚪' },
};

function ForecastRow({ item }: { item: GoalForecastItem }) {
  const cfg = FORECAST_CONFIG[item.forecast_status] ?? FORECAST_CONFIG.no_data;
  return (
    <div className={`p-3 rounded-lg border-l-4 bg-muted/30 ${
      item.forecast_status === 'ahead'    ? 'border-green-500' :
      item.forecast_status === 'on_track' ? 'border-blue-500' :
      item.forecast_status === 'at_risk'  ? 'border-yellow-500' :
      item.forecast_status === 'stalled'  ? 'border-red-500' :
      'border-gray-300'
    }`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">{item.title}</div>
          <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
            {item.user_name && <span>{item.user_name}</span>}
            {item.department_name && <span>・{item.department_name}</span>}
            {item.deadline && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                期限: {item.deadline}
              </span>
            )}
          </div>
        </div>
        <span className={`text-xs font-medium whitespace-nowrap ${cfg.color}`}>
          {cfg.emoji} {cfg.label}
        </span>
      </div>

      <div className="mt-2 flex items-center gap-4 text-xs">
        {item.progress_pct != null && (
          <span className="text-muted-foreground">
            現在: <span className="font-semibold text-foreground">{item.progress_pct}%</span>
          </span>
        )}
        {item.days_ahead_or_behind != null && item.forecast_status !== 'no_data' && (
          <span className={item.days_ahead_or_behind <= 0 ? 'text-green-600' : 'text-red-600'}>
            {item.days_ahead_or_behind <= 0
              ? `${Math.abs(item.days_ahead_or_behind)}日 前倒し`
              : `${item.days_ahead_or_behind}日 遅れ`}
          </span>
        )}
        {item.projected_completion_date && item.forecast_status !== 'no_data' && (
          <span className="text-muted-foreground">
            予測完了: <span className="font-medium text-foreground">{item.projected_completion_date}</span>
          </span>
        )}
      </div>

      {item.target_value != null && (
        <div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              item.forecast_status === 'ahead' || item.forecast_status === 'on_track'
                ? 'bg-green-500'
                : item.forecast_status === 'at_risk'
                ? 'bg-yellow-500'
                : 'bg-red-500'
            }`}
            style={{ width: `${Math.min(item.progress_pct ?? 0, 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

type TabType = 'list' | 'forecast';

export function GoalsPage() {
  const [activeTab, setActiveTab] = useState<TabType>('list');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);

  const { data: statsData, isLoading: statsLoading } = useGoalStats();
  const { data: listData, isLoading: listLoading, refetch } = useGoalsList({
    status: statusFilter,
  });
  const { data: detailData, isLoading: detailLoading } = useGoalDetail(selectedGoalId);
  const { data: forecastData, isLoading: forecastLoading, refetch: refetchForecast } = useGoalForecast();

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Target className="h-6 w-6" />
              目標管理
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {listData?.total_count ?? 0}件の目標
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => activeTab === 'list' ? refetch() : refetchForecast()}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-4 gap-4">
          {statsLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
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
                    <TrendingUp className="h-4 w-4" />
                    達成率
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {statsData?.completion_rate ?? 0}%
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Target className="h-4 w-4" />
                    進行中
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {statsData?.active_goals ?? 0}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <CheckCircle2 className="h-4 w-4" />
                    完了
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {statsData?.completed_goals ?? 0}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <AlertTriangle className="h-4 w-4" />
                    期限超過
                  </div>
                  <div className="text-2xl font-bold mt-1 text-destructive">
                    {statsData?.overdue_goals ?? 0}
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Tab selector */}
        <div className="flex gap-2 border-b">
          <button
            className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'list'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setActiveTab('list')}
          >
            <Target className="h-4 w-4 inline mr-1" />
            目標一覧
          </button>
          <button
            className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'forecast'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setActiveTab('forecast')}
          >
            <Telescope className="h-4 w-4 inline mr-1" />
            目標未来予測
            <InfoTooltip text="過去の進捗データから線形回帰で将来の達成率を予測。AIによる推定値です" />
          </button>
        </div>

        {/* ===== Tab: 目標一覧 ===== */}
        {activeTab === 'list' && (
          <>
            {/* Filter tabs */}
            <div className="flex gap-2">
              {[undefined, 'active', 'completed', 'paused'].map((s) => (
                <Button
                  key={s ?? 'all'}
                  variant={statusFilter === s ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setStatusFilter(s)}
                >
                  {s ? STATUS_LABELS[s] : '全て'}
                </Button>
              ))}
            </div>

            {/* Main content */}
            <div className="flex gap-6">
              {/* Goal list */}
              <div className="flex-1 min-w-0">
                <Card>
                  <CardContent className="p-4">
                    {listLoading ? (
                      <div className="space-y-3">
                        {Array.from({ length: 5 }).map((_, i) => (
                          <Skeleton key={i} className="h-16 w-full" />
                        ))}
                      </div>
                    ) : !listData?.goals.length ? (
                      <div className="text-center py-8 text-muted-foreground">
                        目標が見つかりません
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {listData.goals.map((goal) => (
                          <button
                            key={goal.id}
                            className={`w-full text-left rounded-lg p-3 transition-colors ${
                              selectedGoalId === goal.id
                                ? 'bg-accent'
                                : 'hover:bg-accent/50'
                            }`}
                            onClick={() =>
                              setSelectedGoalId(
                                selectedGoalId === goal.id ? null : goal.id
                              )
                            }
                          >
                            <div className="flex items-center justify-between">
                              <div className="font-medium text-sm">{goal.title}</div>
                              <Badge variant={STATUS_COLORS[goal.status] ?? 'outline'}>
                                {STATUS_LABELS[goal.status] ?? goal.status}
                              </Badge>
                            </div>
                            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                              {goal.user_name && <span>{goal.user_name}</span>}
                              {goal.department_name && <span>{goal.department_name}</span>}
                              {goal.deadline && (
                                <span className="flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {goal.deadline}
                                </span>
                              )}
                              {goal.progress_pct != null && (
                                <span>{goal.progress_pct}%</span>
                              )}
                            </div>
                            {goal.target_value != null && (
                              <div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-primary rounded-full transition-all"
                                  style={{
                                    width: `${Math.min(goal.progress_pct ?? 0, 100)}%`,
                                  }}
                                />
                              </div>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Detail panel */}
              {selectedGoalId && (
                <div className="w-80 shrink-0">
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-base">目標詳細</CardTitle>
                    </CardHeader>
                    <CardContent>
                      {detailLoading ? (
                        <div className="space-y-2">
                          <Skeleton className="h-5 w-32" />
                          <Skeleton className="h-4 w-48" />
                        </div>
                      ) : detailData?.goal ? (
                        <div className="space-y-4">
                          <div>
                            <div className="font-medium">{detailData.goal.title}</div>
                            <div className="text-xs text-muted-foreground mt-1">
                              {detailData.goal.goal_type} / {detailData.goal.goal_level}
                            </div>
                          </div>
                          <div className="flex gap-2 flex-wrap">
                            <Badge variant={STATUS_COLORS[detailData.goal.status] ?? 'outline'}>
                              {STATUS_LABELS[detailData.goal.status] ?? detailData.goal.status}
                            </Badge>
                            <Badge variant="outline">{detailData.goal.period_type}</Badge>
                          </div>
                          {detailData.goal.target_value != null && (
                            <div className="text-sm">
                              <span className="text-muted-foreground">進捗: </span>
                              {detailData.goal.current_value ?? 0} / {detailData.goal.target_value}
                              {detailData.goal.unit && ` ${detailData.goal.unit}`}
                            </div>
                          )}
                          {detailData.progress.length > 0 && (
                            <div className="space-y-1">
                              <div className="text-xs font-medium text-muted-foreground">
                                最近の進捗
                              </div>
                              {detailData.progress.slice(0, 5).map((p) => (
                                <div
                                  key={p.id}
                                  className="text-xs flex justify-between"
                                >
                                  <span>{p.progress_date}</span>
                                  <span>
                                    {p.value != null ? `+${p.value}` : '-'}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : null}
                    </CardContent>
                  </Card>
                </div>
              )}
            </div>
          </>
        )}

        {/* ===== Tab: 目標未来予測 ===== */}
        {activeTab === 'forecast' && (
          <div className="space-y-4">
            {/* サマリーカード */}
            {forecastLoading ? (
              <div className="grid grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Card key={i}><CardContent className="p-4"><Skeleton className="h-10 w-full" /></CardContent></Card>
                ))}
              </div>
            ) : forecastData ? (
              <div className="grid grid-cols-4 gap-4">
                <Card className="border-green-200">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground">🟢 順調（前倒し）</div>
                    <div className="text-2xl font-bold mt-1 text-green-600">
                      {forecastData.ahead_count}件
                    </div>
                  </CardContent>
                </Card>
                <Card className="border-blue-200">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground">🔵 予定通り</div>
                    <div className="text-2xl font-bold mt-1 text-blue-600">
                      {forecastData.on_track_count}件
                    </div>
                  </CardContent>
                </Card>
                <Card className="border-yellow-200">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground">🟡 遅れ気味</div>
                    <div className="text-2xl font-bold mt-1 text-yellow-600">
                      {forecastData.at_risk_count}件
                    </div>
                  </CardContent>
                </Card>
                <Card className="border-red-200">
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground">🔴 停滞中</div>
                    <div className="text-2xl font-bold mt-1 text-red-600">
                      {forecastData.stalled_count}件
                    </div>
                  </CardContent>
                </Card>
              </div>
            ) : null}

            {/* 予測リスト */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Telescope className="h-4 w-4" />
                  目標別 未来予測
                  <InfoTooltip text="過去60日の進捗データを元に線形回帰で予測。AIによる推定値のため参考指標として活用してください" />
                </CardTitle>
              </CardHeader>
              <CardContent>
                {forecastLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Skeleton key={i} className="h-20 w-full" />
                    ))}
                  </div>
                ) : !forecastData?.forecasts.length ? (
                  <div className="text-center py-8 text-muted-foreground">
                    予測データがありません（進捗記録が2件以上必要です）
                  </div>
                ) : (
                  <div className="space-y-3">
                    {forecastData.forecasts.map((item) => (
                      <ForecastRow key={item.id} item={item} />
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
