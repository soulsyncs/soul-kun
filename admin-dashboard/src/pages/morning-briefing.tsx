/**
 * Morning Briefing page
 * Displays a quick 3-minute summary of org status: weather, goals, tasks, alerts, costs
 */

import { useQuery } from '@tanstack/react-query';
import { format } from 'date-fns';
import { ja } from 'date-fns/locale';
import { api } from '@/lib/api';
import type {
  DashboardSummaryResponse,
  GoalStatsResponse,
  TaskOverviewStats,
  EmotionTrendsResponse,
} from '@/types/api';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { Link } from '@tanstack/react-router';
import {
  Target,
  CheckSquare,
  DollarSign,
  AlertTriangle,
  ExternalLink,
  ArrowRight,
} from 'lucide-react';

// 感情スコア → 天気アイコン + ラベル に変換するユーティリティ
function scoreToWeather(score: number | undefined): {
  emoji: string;
  label: string;
  description: string;
  color: string;
} {
  if (score === undefined) {
    return { emoji: '❓', label: 'データなし', description: '感情データがまだありません', color: 'text-muted-foreground' };
  }
  if (score >= 0.5) {
    return { emoji: '☀️', label: '晴れ', description: '組織全体の雰囲気は良好です', color: 'text-yellow-500' };
  }
  if (score >= 0.1) {
    return { emoji: '⛅', label: '曇り', description: '組織の雰囲気はやや安定しています', color: 'text-blue-400' };
  }
  if (score >= -0.1) {
    return { emoji: '🌧️', label: '雨', description: '組織の雰囲気に注意が必要です', color: 'text-blue-600' };
  }
  return { emoji: '⛈️', label: '嵐', description: '組織の雰囲気が低下しています。要対応。', color: 'text-red-500' };
}

export function MorningBriefingPage() {
  const today = format(new Date(), 'M月d日（EEEE）', { locale: ja });

  const { data: summary, isLoading: summaryLoading } =
    useQuery<DashboardSummaryResponse>({
      queryKey: ['morning-briefing-summary'],
      queryFn: () => api.dashboard.getSummary('today'),
    });

  const { data: goalStats, isLoading: goalsLoading } =
    useQuery<GoalStatsResponse>({
      queryKey: ['morning-briefing-goals'],
      queryFn: () => api.goals.getStats(),
    });

  const { data: taskStats, isLoading: tasksLoading } =
    useQuery<TaskOverviewStats>({
      queryKey: ['morning-briefing-tasks'],
      queryFn: () => api.tasks.getOverview(),
    });

  const { data: wellnessTrends, isLoading: wellnessLoading } =
    useQuery<EmotionTrendsResponse>({
      queryKey: ['morning-briefing-wellness'],
      queryFn: () => api.wellness.getTrends({ days: 7 }),
    });

  const isLoading = summaryLoading || goalsLoading || tasksLoading || wellnessLoading;

  // 直近の感情スコア（最新日）
  const trends = wellnessTrends?.trends ?? [];
  const latestScore = trends.length > 0 ? trends[trends.length - 1].avg_score : undefined;
  const weather = scoreToWeather(latestScore);

  // 未解決アラート（緊急のみ）
  const criticalAlerts = (summary?.recent_alerts ?? []).filter(
    (a) => !a.is_resolved && a.severity === 'critical'
  );
  const warningAlerts = (summary?.recent_alerts ?? []).filter(
    (a) => !a.is_resolved && a.severity !== 'critical'
  );

  if (isLoading) {
    return (
      <AppLayout>
        <div className="flex items-center justify-center h-96">
          <div className="animate-pulse text-muted-foreground">朝のまとめを読み込み中...</div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ヘッダー */}
        <div>
          <h1 className="text-3xl font-bold">おはようございます ☀️</h1>
          <p className="text-muted-foreground text-lg">{today} の状況まとめ</p>
          <p className="text-sm text-muted-foreground mt-1">
            今日やるべきことが3分でわかります
          </p>
        </div>

        {/* 天気カード — 組織の雰囲気 */}
        <Card className="border-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">
                今日の組織の天気
                <InfoTooltip text="過去7日間の社員メッセージから分析した、組織全体の雰囲気です（AIによる推定値）" />
              </CardTitle>
              <Link to="/wellness" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-primary">
                詳細 <ExternalLink className="h-3 w-3" />
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              <span className="text-6xl">{weather.emoji}</span>
              <div>
                <div className={`text-2xl font-bold ${weather.color}`}>{weather.label}</div>
                <div className="text-muted-foreground">{weather.description}</div>
                {latestScore !== undefined && (
                  <div className="text-sm text-muted-foreground mt-1">
                    感情スコア: {latestScore.toFixed(2)}（AIによる推定値）
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* メインKPIグリッド */}
        <div className="grid gap-4 md:grid-cols-3">
          {/* 目標達成率 */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                全社目標達成率
                <InfoTooltip text="現在進行中の全目標のうち達成済みの割合" />
              </CardTitle>
              <Target className="h-5 w-5 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                {goalStats ? `${Math.round(goalStats.completion_rate)}%` : '—'}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {goalStats
                  ? `達成 ${goalStats.completed_goals}件 / 全体 ${goalStats.total_goals}件`
                  : 'データなし'}
              </p>
              {goalStats && goalStats.overdue_goals > 0 && (
                <Badge variant="destructive" className="mt-2 text-xs">
                  期限超過 {goalStats.overdue_goals}件
                </Badge>
              )}
              <Link to="/goals" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary mt-2">
                詳細を見る <ArrowRight className="h-3 w-3" />
              </Link>
            </CardContent>
          </Card>

          {/* 期限切れタスク */}
          <Card className={taskStats && taskStats.chatwork_tasks.overdue > 0 ? 'border-orange-400 border-2' : ''}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                期限切れタスク
                <InfoTooltip text="締め切りを過ぎているのに未完了のタスクの数。0が理想です" />
              </CardTitle>
              <CheckSquare className="h-5 w-5 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className={`text-3xl font-bold ${taskStats && taskStats.chatwork_tasks.overdue > 0 ? 'text-orange-500' : 'text-green-600'}`}>
                {taskStats?.chatwork_tasks.overdue ?? '—'}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {taskStats
                  ? `未完了 ${taskStats.chatwork_tasks.open}件 / 全体 ${taskStats.chatwork_tasks.total}件`
                  : 'データなし'}
              </p>
              {taskStats && taskStats.chatwork_tasks.overdue === 0 && (
                <p className="text-xs text-green-600 mt-2 font-medium">すべて期限内 ✓</p>
              )}
              <Link to="/tasks" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary mt-2">
                詳細を見る <ArrowRight className="h-3 w-3" />
              </Link>
            </CardContent>
          </Card>

          {/* 今日のAIコスト */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                今日のAI費用
                <InfoTooltip text="今日ソウルくんのAIが使った費用（日本円）" />
              </CardTitle>
              <DollarSign className="h-5 w-5 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                ¥{Math.round(summary?.kpis?.total_cost_today ?? 0).toLocaleString()}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                予算残 ¥{Math.round(summary?.kpis?.monthly_budget_remaining ?? 0).toLocaleString()}
              </p>
              <Link to="/costs" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary mt-2">
                詳細を見る <ArrowRight className="h-3 w-3" />
              </Link>
            </CardContent>
          </Card>
        </div>

        {/* アラート */}
        {criticalAlerts.length > 0 || warningAlerts.length > 0 ? (
          <Card className="border-destructive border-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5 text-destructive" />
                  今日対応が必要なこと
                </CardTitle>
                <Link to="/" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-primary">
                  ダッシュボード <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {criticalAlerts.map((alert) => (
                  <div key={alert.id} className="flex items-center gap-3 rounded-lg bg-destructive/10 p-3">
                    <Badge variant="destructive" className="shrink-0">緊急</Badge>
                    <div>
                      <p className="text-sm font-medium">{alert.alert_type}</p>
                      <p className="text-xs text-muted-foreground">{alert.message}</p>
                    </div>
                  </div>
                ))}
                {warningAlerts.slice(0, 3).map((alert) => (
                  <div key={alert.id} className="flex items-center gap-3 rounded-lg border p-3">
                    <Badge variant="secondary" className="shrink-0">警告</Badge>
                    <div>
                      <p className="text-sm font-medium">{alert.alert_type}</p>
                      <p className="text-xs text-muted-foreground">{alert.message}</p>
                    </div>
                  </div>
                ))}
                {warningAlerts.length > 3 && (
                  <p className="text-xs text-muted-foreground pl-1">
                    他 {warningAlerts.length - 3}件の警告があります
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-6">
              <div className="flex items-center gap-3">
                <span className="text-2xl">✅</span>
                <div>
                  <p className="font-medium text-green-700">今日の緊急案件はありません</p>
                  <p className="text-sm text-muted-foreground">すべてのアラートが解決済みです</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 今日の会話数 */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">
              ソウルくんの今日の活動
              <InfoTooltip text="今日ソウルくんがメンバーと行ったやり取りの回数" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-6">
              <div className="text-center">
                <div className="text-2xl font-bold">{summary?.kpis?.total_conversations ?? 0}</div>
                <div className="text-xs text-muted-foreground">今日の会話数</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold">{summary?.kpis?.active_alerts_count ?? 0}</div>
                <div className="text-xs text-muted-foreground">アクティブアラート</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold">
                  {((1 - (summary?.kpis?.error_rate ?? 0)) * 100).toFixed(1)}%
                </div>
                <div className="text-xs text-muted-foreground">正常稼働率</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
