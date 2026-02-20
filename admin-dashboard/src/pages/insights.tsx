/**
 * Insights page
 * Shows AI-generated insights, question patterns, and weekly reports
 */

import { useState } from 'react';
import {
  Lightbulb,
  RefreshCw,
  HelpCircle,
  FileText,
  AlertCircle,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useInsightsList, useQuestionPatterns, useWeeklyReports } from '@/hooks/use-insights';
import { InfoTooltip } from '@/components/ui/info-tooltip';

type TabView = 'insights' | 'patterns' | 'reports';

const IMPORTANCE_COLORS: Record<string, 'destructive' | 'default' | 'secondary' | 'outline'> = {
  critical: 'destructive',
  high: 'destructive',
  medium: 'default',
  low: 'secondary',
};

export function InsightsPage() {
  const [tab, setTab] = useState<TabView>('insights');
  const [importanceFilter, setImportanceFilter] = useState<string | undefined>();

  const { data: insightsData, isLoading: insightsLoading, refetch: refetchInsights } = useInsightsList({
    importance: importanceFilter,
  });
  const { data: patternsData, isLoading: patternsLoading, refetch: refetchPatterns } = useQuestionPatterns();
  const { data: reportsData, isLoading: reportsLoading, refetch: refetchReports } = useWeeklyReports();

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Lightbulb className="h-6 w-6" />
              インサイト（AI発見レポート）
              <InfoTooltip text="インサイトとは「ソウルくんが自動的に気づいた重要な傾向や提案」のことです。誰がよく質問しているか・どんな話題が多いかなどをAIが分析してお知らせします" />
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              ソウルくんが会話から自動的に発見した傾向・気づき・改善提案をまとめています
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchInsights();
              refetchPatterns();
              refetchReports();
            }}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Tab navigation */}
        <div className="flex gap-2">
          <Button
            variant={tab === 'insights' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('insights')}
          >
            <Lightbulb className="mr-1 h-4 w-4" />
            インサイト ({insightsData?.total_count ?? 0})
          </Button>
          <Button
            variant={tab === 'patterns' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('patterns')}
          >
            <HelpCircle className="mr-1 h-4 w-4" />
            質問パターン ({patternsData?.total_count ?? 0})
          </Button>
          <Button
            variant={tab === 'reports' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTab('reports')}
          >
            <FileText className="mr-1 h-4 w-4" />
            週次レポート ({reportsData?.total_count ?? 0})
          </Button>
        </div>

        {/* Insights tab */}
        {tab === 'insights' && (
          <>
            <div className="flex gap-2">
              {[undefined, 'critical', 'high', 'medium', 'low'].map((imp) => (
                <Button
                  key={imp ?? 'all'}
                  variant={importanceFilter === imp ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setImportanceFilter(imp)}
                >
                  {imp ?? '全て'}
                </Button>
              ))}
            </div>
            <Card>
              <CardContent className="p-4">
                {insightsLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Skeleton key={i} className="h-20 w-full" />
                    ))}
                  </div>
                ) : !insightsData?.insights.length ? (
                  <div className="text-center py-8 text-muted-foreground">
                    インサイトがありません
                  </div>
                ) : (
                  <div className="space-y-3">
                    {insightsData.insights.map((insight) => (
                      <div key={insight.id} className="rounded-lg border p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <Badge variant={IMPORTANCE_COLORS[insight.importance] ?? 'outline'}>
                              {insight.importance}
                            </Badge>
                            <Badge variant="outline">{insight.insight_type}</Badge>
                            {insight.department_name && (
                              <span className="text-xs text-muted-foreground">
                                {insight.department_name}
                              </span>
                            )}
                          </div>
                          <Badge variant={insight.status === 'pending' ? 'default' : 'secondary'}>
                            {insight.status}
                          </Badge>
                        </div>
                        <div className="font-medium text-sm">{insight.title}</div>
                        <p className="text-xs text-muted-foreground mt-1">
                          {insight.description}
                        </p>
                        {insight.recommended_action && (
                          <div className="mt-2 text-xs flex items-start gap-1">
                            <AlertCircle className="h-3 w-3 mt-0.5 text-primary shrink-0" />
                            <span>{insight.recommended_action}</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {/* Patterns tab */}
        {tab === 'patterns' && (
          <Card>
            <CardContent className="p-4">
              {patternsLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : !patternsData?.patterns.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  質問パターンがありません
                </div>
              ) : (
                <div className="space-y-2">
                  {patternsData.patterns.map((pattern) => (
                    <div key={pattern.id} className="rounded-lg border p-3 flex items-center justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">{pattern.normalized_question}</div>
                        <div className="text-xs text-muted-foreground flex gap-2 mt-1">
                          <Badge variant="outline" className="text-xs">{pattern.question_category}</Badge>
                          {pattern.last_asked_at && <span>{pattern.last_asked_at.slice(0, 10)}</span>}
                        </div>
                      </div>
                      <div className="text-right shrink-0 ml-4">
                        <div className="text-lg font-bold">{pattern.occurrence_count}</div>
                        <div className="text-xs text-muted-foreground">回</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Reports tab */}
        {tab === 'reports' && (
          <Card>
            <CardContent className="p-4">
              {reportsLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : !reportsData?.reports.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  週次レポートがありません
                </div>
              ) : (
                <div className="space-y-2">
                  {reportsData.reports.map((report) => (
                    <div key={report.id} className="rounded-lg border p-3 flex items-center justify-between">
                      <div>
                        <div className="text-sm font-medium">
                          {report.week_start} 〜 {report.week_end}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1 flex gap-2">
                          {report.sent_via && <span>送信: {report.sent_via}</span>}
                          {report.sent_at && <span>{report.sent_at.slice(0, 10)}</span>}
                        </div>
                      </div>
                      <Badge variant={report.status === 'sent' ? 'secondary' : 'outline'}>
                        {report.status}
                      </Badge>
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
