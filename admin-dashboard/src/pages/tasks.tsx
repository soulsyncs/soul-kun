/**
 * Tasks management page
 * Unified view of ChatWork, autonomous, and detected tasks
 */

import { useState } from 'react';
import {
  CheckSquare,
  RefreshCw,
  Clock,
  Bot,
  MessageSquare,
  Search,
  X,
  ExternalLink,
  User,
  Calendar,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { useTasksOverview, useTasksList } from '@/hooks/use-tasks';
import type { TaskItem } from '@/types/api';

const SOURCE_LABELS: Record<string, string> = {
  chatwork: 'ChatWork',
  autonomous: '自律タスク',
  detected: '検出タスク',
};

const SOURCE_DESCRIPTIONS: Record<string, string> = {
  chatwork: 'ChatWorkで担当者にアサインされているタスクです',
  autonomous: 'ソウルくんが自分で判断して自動的に実行するタスクです',
  detected: 'ソウルくんが会話の中から「やるべきこと」として自動検出したタスクです',
};

const SOURCE_ICONS: Record<string, typeof MessageSquare> = {
  chatwork: MessageSquare,
  autonomous: Bot,
  detected: Search,
};

const STATUS_COLORS: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  open: 'default',
  done: 'secondary',
  pending: 'outline',
  running: 'default',
  completed: 'secondary',
  failed: 'destructive',
  cancelled: 'outline',
  detected: 'outline',
};

const STATUS_LABELS: Record<string, string> = {
  open: '未完了',
  done: '完了',
  pending: '保留中',
  running: '実行中',
  completed: '完了',
  failed: '失敗',
  cancelled: 'キャンセル',
  detected: '検出済み',
};

export function TasksPage() {
  const [sourceFilter, setSourceFilter] = useState<string | undefined>();
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null);

  const { data: overviewData, isLoading: overviewLoading, refetch: refetchOverview } = useTasksOverview();
  const { data: listData, isLoading: listLoading, refetch: refetchList } = useTasksList({
    source: sourceFilter,
  });

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <CheckSquare className="h-6 w-6" />
              タスク管理
              <InfoTooltip text="ChatWorkのタスク・ソウルくんが自動実行するタスク・会話から検出したタスクをまとめて確認できます" />
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              タスクをタップすると詳細が見られます
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchOverview();
              refetchList();
            }}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Overview cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {overviewLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <Card key={i}>
                <CardContent className="p-4">
                  <Skeleton className="h-8 w-16 mb-2" />
                  <Skeleton className="h-4 w-32" />
                </CardContent>
              </Card>
            ))
          ) : (
            <>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <MessageSquare className="h-4 w-4" />
                    ChatWorkタスク
                    <InfoTooltip text={SOURCE_DESCRIPTIONS.chatwork} />
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="text-2xl font-bold">
                    {overviewData?.chatwork_tasks.total ?? 0}
                  </div>
                  <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                    <span>未完了: {overviewData?.chatwork_tasks.open ?? 0}</span>
                    <span>完了: {overviewData?.chatwork_tasks.done ?? 0}</span>
                    {(overviewData?.chatwork_tasks.overdue ?? 0) > 0 && (
                      <span className="text-destructive">
                        期限切れ: {overviewData?.chatwork_tasks.overdue}
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Bot className="h-4 w-4" />
                    自律タスク
                    <InfoTooltip text={SOURCE_DESCRIPTIONS.autonomous} />
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="text-2xl font-bold">
                    {overviewData?.autonomous_tasks.total ?? 0}
                  </div>
                  <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                    <span>実行中: {overviewData?.autonomous_tasks.running ?? 0}</span>
                    <span>完了: {overviewData?.autonomous_tasks.completed ?? 0}</span>
                    {(overviewData?.autonomous_tasks.failed ?? 0) > 0 && (
                      <span className="text-destructive">
                        失敗: {overviewData?.autonomous_tasks.failed}
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Search className="h-4 w-4" />
                    検出タスク
                    <InfoTooltip text={SOURCE_DESCRIPTIONS.detected} />
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="text-2xl font-bold">
                    {overviewData?.detected_tasks.total ?? 0}
                  </div>
                  <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                    <span>処理済: {overviewData?.detected_tasks.processed ?? 0}</span>
                    <span>未処理: {overviewData?.detected_tasks.unprocessed ?? 0}</span>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Source filter */}
        <div className="flex gap-2">
          {[undefined, 'chatwork', 'autonomous', 'detected'].map((s) => (
            <Button
              key={s ?? 'all'}
              variant={sourceFilter === s ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSourceFilter(s)}
            >
              {s ? SOURCE_LABELS[s] : '全て'}
            </Button>
          ))}
        </div>

        {/* Task list + Detail panel */}
        <div className="flex flex-col md:flex-row gap-4">
          <Card className="flex-1">
            <CardContent className="p-4">
              {listLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : !listData?.tasks.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  タスクが見つかりません
                </div>
              ) : (
                <div className="space-y-2">
                  {listData.tasks.map((task) => {
                    const SourceIcon = SOURCE_ICONS[task.source] ?? CheckSquare;
                    const isSelected = selectedTask?.id === task.id && selectedTask?.source === task.source;
                    return (
                      <div
                        key={`${task.source}-${task.id}`}
                        className={`rounded-lg border p-3 cursor-pointer transition-colors hover:bg-muted/50 ${isSelected ? 'bg-muted/30 border-primary' : ''}`}
                        onClick={() => setSelectedTask(isSelected ? null : task)}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0">
                            <SourceIcon className="h-4 w-4 text-muted-foreground shrink-0" />
                            <span className="text-sm font-medium truncate">
                              {task.title}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <Badge variant="outline" className="text-xs">
                              {SOURCE_LABELS[task.source] ?? task.source}
                            </Badge>
                            <Badge variant={STATUS_COLORS[task.status] ?? 'outline'}>
                              {STATUS_LABELS[task.status] ?? task.status}
                            </Badge>
                          </div>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground flex gap-3">
                          {task.assignee_name && (
                            <span className="flex items-center gap-1">
                              <User className="h-3 w-3" />
                              {task.assignee_name}
                            </span>
                          )}
                          {task.deadline && (
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              期限: {task.deadline}
                            </span>
                          )}
                          {task.created_at && (
                            <span className="flex items-center gap-1">
                              <Calendar className="h-3 w-3" />
                              {task.created_at.slice(0, 10)}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Task detail panel */}
          {selectedTask && (
            <Card className="w-full md:w-[340px] md:shrink-0">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">タスク詳細</CardTitle>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0"
                    onClick={() => setSelectedTask(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <p className="text-xs text-muted-foreground mb-1">タスク名</p>
                  <p className="text-sm font-medium">{selectedTask.title}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">種類</p>
                    <Badge variant="outline" className="text-xs">
                      {SOURCE_LABELS[selectedTask.source] ?? selectedTask.source}
                    </Badge>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">状態</p>
                    <Badge variant={STATUS_COLORS[selectedTask.status] ?? 'outline'}>
                      {STATUS_LABELS[selectedTask.status] ?? selectedTask.status}
                    </Badge>
                  </div>
                </div>
                {selectedTask.assignee_name && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">担当者</p>
                    <p className="text-sm flex items-center gap-1">
                      <User className="h-3.5 w-3.5" />
                      {selectedTask.assignee_name}
                    </p>
                  </div>
                )}
                {selectedTask.deadline && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">期限</p>
                    <p className="text-sm flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" />
                      {selectedTask.deadline}
                    </p>
                  </div>
                )}
                {selectedTask.created_at && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">作成日</p>
                    <p className="text-sm">{selectedTask.created_at.slice(0, 10)}</p>
                  </div>
                )}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">種類の説明</p>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {SOURCE_DESCRIPTIONS[selectedTask.source] ?? ''}
                  </p>
                </div>
                {selectedTask.source === 'chatwork' && (
                  <Button variant="outline" size="sm" className="w-full" asChild>
                    <a href="https://www.chatwork.com/" target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="mr-2 h-3.5 w-3.5" />
                      ChatWorkで確認する
                    </a>
                  </Button>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
