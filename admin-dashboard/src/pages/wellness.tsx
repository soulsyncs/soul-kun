/**
 * Wellness / Emotion analysis page
 * Shows emotion trends and alerts
 */

import { useState } from 'react';
import {
  Heart,
  RefreshCw,
  AlertCircle,
  TrendingDown,
  TrendingUp,
  Activity,
  Shield,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useEmotionAlerts, useEmotionTrends } from '@/hooks/use-wellness';

const RISK_COLORS: Record<string, 'destructive' | 'default' | 'secondary' | 'outline'> = {
  critical: 'destructive',
  high: 'destructive',
  medium: 'default',
  low: 'secondary',
};

const RISK_LABELS: Record<string, string> = {
  critical: '重大',
  high: '高',
  medium: '中',
  low: '低',
};

const ALERT_TYPE_LABELS: Record<string, string> = {
  sudden_drop: '急激な低下',
  sustained_negative: '継続的なネガティブ',
  high_volatility: '高い変動',
  recovery: '回復',
};

export function WellnessPage() {
  const [days, setDays] = useState(30);
  const [alertFilter, setAlertFilter] = useState<string | undefined>();

  const { data: trendsData, isLoading: trendsLoading, refetch: refetchTrends } = useEmotionTrends({ days });
  const { data: alertsData, isLoading: alertsLoading, refetch: refetchAlerts } = useEmotionAlerts({
    status: alertFilter,
  });

  const avgScore = trendsData?.trends.length
    ? trendsData.trends.reduce((sum, t) => sum + t.avg_score, 0) / trendsData.trends.length
    : null;

  const totalNegative = trendsData?.trends.reduce((sum, t) => sum + t.negative_count, 0) ?? 0;
  const totalPositive = trendsData?.trends.reduce((sum, t) => sum + t.positive_count, 0) ?? 0;

  // 直近の感情スコア（最新日）
  const latestTrend = trendsData?.trends[trendsData.trends.length - 1];
  const latestScore = latestTrend?.avg_score;

  // 天気変換ロジック
  const weather = (() => {
    if (latestScore === undefined) return { emoji: '❓', label: 'データなし', color: 'text-muted-foreground', bg: 'bg-muted' };
    if (latestScore >= 0.5) return { emoji: '☀️', label: '晴れ — 組織の雰囲気は良好です', color: 'text-yellow-600', bg: 'bg-yellow-50 dark:bg-yellow-950' };
    if (latestScore >= 0.1) return { emoji: '⛅', label: '曇り — やや安定しています', color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-950' };
    if (latestScore >= -0.1) return { emoji: '🌧️', label: '雨 — 注意が必要です', color: 'text-blue-700', bg: 'bg-blue-100 dark:bg-blue-900' };
    return { emoji: '⛈️', label: '嵐 — 雰囲気が低下中。要対応。', color: 'text-red-600', bg: 'bg-red-50 dark:bg-red-950' };
  })();

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Heart className="h-6 w-6" />
              ウェルネス
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              組織の感情分析とアラート
            </p>
          </div>
          <div className="flex gap-2">
            <div className="flex rounded-lg border bg-card p-1">
              {[7, 14, 30, 60].map((d) => (
                <Button
                  key={d}
                  variant={days === d ? 'default' : 'ghost'}
                  size="sm"
                  onClick={() => setDays(d)}
                >
                  {d}日
                </Button>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                refetchTrends();
                refetchAlerts();
              }}
            >
              <RefreshCw className="mr-1 h-4 w-4" />
              更新
            </Button>
          </div>
        </div>

        {/* 天気予報カード（感情スコアの直感的表示）*/}
        <Card className={weather.bg}>
          <CardContent className="py-5">
            <div className="flex items-center gap-4">
              <span className="text-5xl">{weather.emoji}</span>
              <div>
                <div className={`text-xl font-bold ${weather.color}`}>{weather.label}</div>
                <div className="text-sm text-muted-foreground mt-1">
                  {latestScore !== undefined
                    ? `最新感情スコア: ${latestScore.toFixed(2)}（AIによる推定値 / ${latestTrend?.date ?? '—'}）`
                    : 'まだデータがありません'}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-4">
          {trendsLoading ? (
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
                    <Activity className="h-4 w-4" />
                    平均スコア
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {avgScore != null ? avgScore.toFixed(2) : '-'}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <TrendingUp className="h-4 w-4" />
                    ポジティブ
                  </div>
                  <div className="text-2xl font-bold mt-1 text-green-600">
                    {totalPositive}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <TrendingDown className="h-4 w-4" />
                    ネガティブ
                  </div>
                  <div className="text-2xl font-bold mt-1 text-destructive">
                    {totalNegative}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Shield className="h-4 w-4" />
                    アラート
                  </div>
                  <div className="text-2xl font-bold mt-1">
                    {alertsData?.total_count ?? 0}
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Trend chart (simplified bar representation) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">感情スコア推移（{days}日間）</CardTitle>
          </CardHeader>
          <CardContent>
            {trendsLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : !trendsData?.trends.length ? (
              <div className="text-center py-8 text-muted-foreground">
                データがありません
              </div>
            ) : (
              <div className="flex items-end gap-px h-40">
                {trendsData.trends.map((t) => {
                  const normalized = ((t.avg_score + 1) / 2) * 100;
                  const color =
                    t.avg_score > 0.2
                      ? 'bg-green-500'
                      : t.avg_score < -0.2
                        ? 'bg-red-500'
                        : 'bg-yellow-500';
                  return (
                    <div
                      key={t.date}
                      className="flex-1 min-w-0 group relative"
                    >
                      <div
                        className={`${color} rounded-t transition-all`}
                        style={{ height: `${Math.max(normalized, 4)}%` }}
                      />
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block bg-popover text-popover-foreground border rounded px-2 py-1 text-xs whitespace-nowrap z-10">
                        {t.date}: {t.avg_score.toFixed(2)} ({t.message_count}件)
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Alerts */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <AlertCircle className="h-4 w-4" />
                感情アラート
              </CardTitle>
              <div className="flex gap-1">
                {[undefined, 'active', 'resolved'].map((s) => (
                  <Button
                    key={s ?? 'all'}
                    variant={alertFilter === s ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setAlertFilter(s)}
                  >
                    {s === 'active' ? 'アクティブ' : s === 'resolved' ? '解決済み' : '全て'}
                  </Button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {alertsLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            ) : !alertsData?.alerts.length ? (
              <div className="text-center py-6 text-muted-foreground">
                アラートはありません
              </div>
            ) : (
              <div className="space-y-2">
                {alertsData.alerts.map((alert) => (
                  <div
                    key={alert.id}
                    className="rounded-lg border p-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant={RISK_COLORS[alert.risk_level] ?? 'outline'}>
                          {RISK_LABELS[alert.risk_level] ?? alert.risk_level}
                        </Badge>
                        <span className="text-sm font-medium">
                          {ALERT_TYPE_LABELS[alert.alert_type] ?? alert.alert_type}
                        </span>
                      </div>
                      <Badge variant={alert.status === 'active' ? 'default' : 'secondary'}>
                        {alert.status === 'active' ? 'アクティブ' : '解決済み'}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground flex gap-3">
                      {alert.user_name && <span>{alert.user_name}</span>}
                      {alert.department_name && <span>{alert.department_name}</span>}
                      {alert.score_change != null && (
                        <span>
                          変動: {alert.score_change > 0 ? '+' : ''}
                          {alert.score_change.toFixed(2)}
                        </span>
                      )}
                      {alert.consecutive_negative_days != null && (
                        <span>{alert.consecutive_negative_days}日連続</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
