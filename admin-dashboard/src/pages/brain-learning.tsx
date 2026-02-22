/**
 * Brain Learning Review page (Human-in-the-loop)
 * 学習パターンの人間確認画面
 *
 * ソウルくんが自動抽出した学習パターンを管理者が確認・承認/却下できる。
 * CLAUDE.md §1-1: 管理ダッシュボードはBrain経由不要（読み取り・書き込みとも）
 */

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle,
  XCircle,
  RefreshCw,
  BookOpen,
  AlertTriangle,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import type { LearningPatternEntry, LearningPatternsResponse } from '@/types/api';

const SCOPE_LABEL: Record<string, string> = {
  global: '全体',
  org: '組織',
  user: 'ユーザー',
};

const PATTERN_TYPE_LABEL: Record<string, string> = {
  success: '成功パターン',
  failure: '失敗パターン',
  timing: 'タイミング',
  phrasing: '言い回し',
  topic: 'トピック',
};

function PatternCard({
  pattern,
  onApprove,
  onReject,
  isPending,
}: {
  pattern: LearningPatternEntry;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  isPending: boolean;
}) {
  const successPct = pattern.success_rate != null
    ? Math.round(pattern.success_rate * 100)
    : null;
  const confidencePct = pattern.confidence_score != null
    ? Math.round(pattern.confidence_score * 100)
    : null;

  return (
    <Card className="mb-3">
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <Badge variant="outline">
                {PATTERN_TYPE_LABEL[pattern.pattern_type] ?? pattern.pattern_type}
              </Badge>
              {pattern.pattern_category && (
                <Badge variant="secondary">{pattern.pattern_category}</Badge>
              )}
              {pattern.scope && (
                <Badge variant="secondary">
                  {SCOPE_LABEL[pattern.scope] ?? pattern.scope}
                </Badge>
              )}
            </div>
            <div className="text-sm text-muted-foreground mt-1 space-y-0.5">
              <div>
                サンプル数: <span className="font-medium text-foreground">{pattern.sample_count}</span>件 /
                成功: <span className="font-medium text-foreground">{pattern.success_count}</span> /
                失敗: <span className="font-medium text-foreground">{pattern.failure_count}</span>
                {successPct != null && (
                  <span className="ml-1 text-green-600 dark:text-green-400">
                    （成功率 {successPct}%）
                  </span>
                )}
              </div>
              {confidencePct != null && (
                <div>
                  信頼度: <span className="font-medium text-foreground">{confidencePct}%</span>
                </div>
              )}
              <div className="text-xs opacity-60">
                検出日時: {new Date(pattern.created_at).toLocaleString('ja-JP')}
              </div>
            </div>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button
              size="sm"
              variant="default"
              onClick={() => onApprove(pattern.id)}
              disabled={isPending}
              className="gap-1"
            >
              <CheckCircle className="h-4 w-4" />
              承認
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onReject(pattern.id)}
              disabled={isPending}
              className="gap-1 text-destructive border-destructive hover:bg-destructive hover:text-destructive-foreground"
            >
              <XCircle className="h-4 w-4" />
              却下
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function BrainLearningPage() {
  const queryClient = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const { data, isLoading, refetch } = useQuery<LearningPatternsResponse>({
    queryKey: ['brain-learning-patterns', showAll],
    queryFn: () => api.brain.getLearningPatterns(!showAll),
    staleTime: 60_000,
  });

  const validateMutation = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      api.brain.validatePattern(id, approved),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain-learning-patterns'] });
      setMutationError(null);
    },
    onError: (err: Error) =>
      setMutationError(err.message ?? '操作に失敗しました'),
  });

  const handleApprove = (id: string) =>
    validateMutation.mutate({ id, approved: true });
  const handleReject = (id: string) =>
    validateMutation.mutate({ id, approved: false });

  const patterns = data?.patterns ?? [];
  const totalCount = data?.total_count ?? 0;

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ヘッダー */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <BookOpen className="h-6 w-6" />
              学習確認（Human-in-the-loop）
            </h1>
            <p className="text-muted-foreground text-sm mt-1">
              ソウルくんが自動で学んだパターンを確認・承認してください。
              承認すると判断に反映され、却下すると無効化されます。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? '未確認のみ表示' : '全パターン表示'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
            >
              <RefreshCw className="h-4 w-4 mr-1" />
              更新
            </Button>
          </div>
        </div>

        {/* エラー表示 */}
        {mutationError && (
          <div className="flex items-center gap-2 rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-destructive text-sm">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {mutationError}
          </div>
        )}

        {/* サマリー */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {showAll ? '全パターン' : '未確認パターン'}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <p className="text-3xl font-bold">{totalCount} 件</p>
            )}
            {!showAll && totalCount === 0 && !isLoading && (
              <p className="text-sm text-muted-foreground mt-1">
                確認待ちのパターンはありません
              </p>
            )}
          </CardContent>
        </Card>

        {/* パターン一覧 */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
        ) : patterns.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <CheckCircle className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>確認待ちの学習パターンはありません</p>
          </div>
        ) : (
          <div>
            {patterns.map((pattern) => (
              <PatternCard
                key={pattern.id}
                pattern={pattern}
                onApprove={handleApprove}
                onReject={handleReject}
                isPending={validateMutation.isPending}
              />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
