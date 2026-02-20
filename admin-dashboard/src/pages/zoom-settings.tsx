/**
 * Zoom連携設定ページ
 *
 * 「この会議名 → このChatWorkルームへ議事録を送る」という設定を
 * 管理画面から一元管理する。カレンダーの備考欄に毎回書く手間をなくす。
 */

import { useState } from 'react';
import { Video, Plus, Trash2, RefreshCw, CheckCircle2, XCircle } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';

// ===== 型定義 =====

interface ZoomConfig {
  id: string;
  meeting_name_pattern: string;
  chatwork_room_id: string;
  room_name: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface ZoomConfigsResponse {
  status: string;
  configs: ZoomConfig[];
  total: number;
}

// ===== 新規追加フォーム =====

function AddConfigForm({ onSuccess }: { onSuccess: () => void }) {
  const [pattern, setPattern] = useState('');
  const [roomId, setRoomId] = useState('');
  const [roomName, setRoomName] = useState('');
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: (data: { meeting_name_pattern: string; chatwork_room_id: string; room_name?: string }) =>
      api.zoomSettings.createConfig(data),
    onSuccess: () => {
      setPattern('');
      setRoomId('');
      setRoomName('');
      setError('');
      onSuccess();
    },
    onError: (err: Error) => {
      setError(err.message || '追加に失敗しました');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pattern.trim() || !roomId.trim()) {
      setError('会議名キーワードとChatWorkルームIDは必須です');
      return;
    }
    mutation.mutate({
      meeting_name_pattern: pattern.trim(),
      chatwork_room_id: roomId.trim(),
      room_name: roomName.trim() || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            会議名キーワード <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="例: 朝会、週次MTG"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            ChatWorkルームID <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            value={roomId}
            onChange={(e) => setRoomId(e.target.value)}
            placeholder="例: 417892193"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            ルーム名（メモ用・省略可）
          </label>
          <input
            type="text"
            value={roomName}
            onChange={(e) => setRoomName(e.target.value)}
            placeholder="例: 営業チームルーム"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <Button type="submit" size="sm" disabled={mutation.isPending}>
        <Plus className="mr-2 h-4 w-4" />
        {mutation.isPending ? '追加中...' : '設定を追加'}
      </Button>
    </form>
  );
}

// ===== 設定行（編集・削除） =====

function ConfigRow({ config, onDelete, onUpdate }: {
  config: ZoomConfig;
  onDelete: (id: string) => void;
  onUpdate: (id: string, data: { is_active: boolean }) => void;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3 md:flex-row md:items-center md:gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-sm">{config.meeting_name_pattern}</span>
          <Badge variant={config.is_active ? 'default' : 'secondary'}>
            {config.is_active ? '有効' : '無効'}
          </Badge>
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          <span>ChatWorkルームID: {config.chatwork_room_id}</span>
          {config.room_name && (
            <span className="ml-2 text-muted-foreground">（{config.room_name}）</span>
          )}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onUpdate(config.id, { is_active: !config.is_active })}
        >
          {config.is_active ? (
            <><XCircle className="mr-1 h-3 w-3" />無効化</>
          ) : (
            <><CheckCircle2 className="mr-1 h-3 w-3" />有効化</>
          )}
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={() => {
            if (window.confirm(`「${config.meeting_name_pattern}」の設定を削除しますか？`)) {
              onDelete(config.id);
            }
          }}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

// ===== ローディング =====

function PageSkeleton() {
  return (
    <AppLayout>
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    </AppLayout>
  );
}

// ===== メインページ =====

export function ZoomSettingsPage() {
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<ZoomConfigsResponse>({
    queryKey: ['zoom-configs'],
    queryFn: () => api.zoomSettings.getConfigs(),
    staleTime: 300000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.zoomSettings.deleteConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zoom-configs'] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { is_active: boolean } }) =>
      api.zoomSettings.updateConfig(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zoom-configs'] }),
  });

  if (isLoading) return <PageSkeleton />;

  const configs = data?.configs ?? [];
  const activeCount = configs.filter((c) => c.is_active).length;

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ヘッダー */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-bold md:text-3xl">Zoom連携設定</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              会議名のキーワードと送信先ChatWorkルームを設定します
            </p>
          </div>
          <Button onClick={() => refetch()} size="sm" variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* サマリーカード */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="p-4">
              <div className="text-2xl font-bold">{configs.length}</div>
              <div className="text-xs text-muted-foreground">設定数（合計）</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-2xl font-bold text-green-600">{activeCount}</div>
              <div className="text-xs text-muted-foreground">有効な設定</div>
            </CardContent>
          </Card>
          <Card className="col-span-2 md:col-span-1">
            <CardContent className="p-4">
              <div className="text-2xl font-bold text-muted-foreground">
                {configs.length - activeCount}
              </div>
              <div className="text-xs text-muted-foreground">無効な設定</div>
            </CardContent>
          </Card>
        </div>

        {/* 仕組みの説明 */}
        <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
          <CardContent className="p-4">
            <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
              📋 使い方
            </p>
            <p className="mt-1 text-xs text-blue-800 dark:text-blue-200">
              会議が終わってZoom録画が完了すると、ソウルくんが自動で議事録を作成します。
              会議名に「キーワード」が含まれていれば、設定した先のChatWorkルームに届きます。
              どの設定にも一致しない場合は、管理部ルームに届きます。
            </p>
            <p className="mt-2 text-xs text-blue-700 dark:text-blue-300">
              例: キーワード「朝会」→ 会議名「2月朝会」「3月朝会MTG」などが全て対象になります
            </p>
          </CardContent>
        </Card>

        {/* 新規追加フォーム */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Plus className="h-4 w-4" />
              新しい設定を追加
            </CardTitle>
          </CardHeader>
          <CardContent>
            <AddConfigForm
              onSuccess={() => queryClient.invalidateQueries({ queryKey: ['zoom-configs'] })}
            />
          </CardContent>
        </Card>

        {/* 設定一覧 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Video className="h-4 w-4" />
              設定一覧（{configs.length}件）
            </CardTitle>
          </CardHeader>
          <CardContent>
            {error && (
              <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                設定の読み込みに失敗しました。再度お試しください。
              </div>
            )}
            {configs.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                <Video className="mx-auto mb-2 h-8 w-8 opacity-30" />
                <p>まだ設定がありません</p>
                <p className="mt-1 text-xs">上のフォームから設定を追加してください</p>
              </div>
            ) : (
              <div className="space-y-2">
                {configs.map((config) => (
                  <ConfigRow
                    key={config.id}
                    config={config}
                    onDelete={(id) => deleteMutation.mutate(id)}
                    onUpdate={(id, data) => updateMutation.mutate({ id, data })}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
