/**
 * Zoom連携設定ページ
 *
 * タブ1「送信先設定」:
 *   「この会議名 → このChatWorkルームへ議事録を送る」という設定を管理する。
 *
 * タブ2「アカウント管理」:
 *   複数のZoomアカウントを登録し、それぞれのWebhook Secret Tokenを管理する。
 *   各Zoomアカウントから届いた録画を正しく受け取るための設定。
 */

import { useState } from 'react';
import { Video, Plus, Trash2, RefreshCw, CheckCircle2, XCircle, Key, ExternalLink } from 'lucide-react';
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

interface ZoomAccount {
  id: string;
  account_name: string;
  zoom_account_id: string;
  webhook_secret_token_masked: string;
  default_room_id: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface ZoomAccountsResponse {
  status: string;
  accounts: ZoomAccount[];
  total: number;
}

// ===== タブ型 =====

type TabId = 'configs' | 'accounts';

// ===== 送信先設定: 新規追加フォーム =====

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
          <p className="mt-1 text-xs text-muted-foreground">
            📍 ChatWorkでルームを開いたときのURL末尾の数字です（例: #!rid<strong>417892193</strong>）
          </p>
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

// ===== 送信先設定: 設定行（編集・削除） =====

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

// ===== アカウント管理: 新規追加フォーム =====

function AddAccountForm({ onSuccess }: { onSuccess: () => void }) {
  const [accountName, setAccountName] = useState('');
  const [zoomAccountId, setZoomAccountId] = useState('');
  const [secretToken, setSecretToken] = useState('');
  const [defaultRoomId, setDefaultRoomId] = useState('');
  const [error, setError] = useState('');

  const mutation = useMutation({
    mutationFn: (data: {
      account_name: string;
      zoom_account_id: string;
      webhook_secret_token: string;
      default_room_id?: string;
    }) => api.zoomAccounts.createAccount(data),
    onSuccess: () => {
      setAccountName('');
      setZoomAccountId('');
      setSecretToken('');
      setDefaultRoomId('');
      setError('');
      onSuccess();
    },
    onError: (err: Error) => {
      setError(err.message || '追加に失敗しました');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!accountName.trim() || !zoomAccountId.trim() || !secretToken.trim()) {
      setError('アカウント名・Zoom Account ID・Secret Tokenは必須です');
      return;
    }
    mutation.mutate({
      account_name: accountName.trim(),
      zoom_account_id: zoomAccountId.trim(),
      webhook_secret_token: secretToken.trim(),
      default_room_id: defaultRoomId.trim() || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            アカウント名（管理用メモ） <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
            placeholder="例: 営業部Zoom、本社アカウント"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            Zoom Account ID <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            value={zoomAccountId}
            onChange={(e) => setZoomAccountId(e.target.value)}
            placeholder="例: AbCdEfGhIjKlMnOpQr"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            📍{' '}
            <a
              href="https://marketplace.zoom.us/"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-blue-600 underline hover:text-blue-800"
            >
              Zoom App Marketplace <ExternalLink className="h-2.5 w-2.5" />
            </a>
            {' '}→ アプリを開く → 「App Credentials」タブに記載されています
          </p>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            Webhook Secret Token <span className="text-destructive">*</span>
          </label>
          <input
            type="password"
            value={secretToken}
            onChange={(e) => setSecretToken(e.target.value)}
            placeholder="Zoom AppのSecret Token"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            📍 Zoom App Marketplace → アプリを開く → 「Feature」→「Event Subscriptions」に記載されています
          </p>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            デフォルト送信先ルームID（省略可）
          </label>
          <input
            type="text"
            value={defaultRoomId}
            onChange={(e) => setDefaultRoomId(e.target.value)}
            placeholder="例: 417892193（省略時は会議名マッチを優先）"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            📍 ChatWorkのルームURLの末尾の数字、またはグループチャット設定で確認できます（設定しない場合は「送信先設定」タブのキーワードで振り分けられます）
          </p>
        </div>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <Button type="submit" size="sm" disabled={mutation.isPending}>
        <Plus className="mr-2 h-4 w-4" />
        {mutation.isPending ? '追加中...' : 'アカウントを追加'}
      </Button>
    </form>
  );
}

// ===== アカウント管理: アカウント行 =====

function AccountRow({ account, onDelete, onUpdate }: {
  account: ZoomAccount;
  onDelete: (id: string) => void;
  onUpdate: (id: string, data: { is_active: boolean }) => void;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3 md:flex-row md:items-center md:gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-sm">{account.account_name}</span>
          <Badge variant={account.is_active ? 'default' : 'secondary'}>
            {account.is_active ? '有効' : '無効'}
          </Badge>
        </div>
        <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
          <div>Zoom Account ID: <span className="font-mono">{account.zoom_account_id}</span></div>
          <div>Secret Token: <span className="font-mono">{account.webhook_secret_token_masked}</span></div>
          {account.default_room_id && (
            <div>デフォルト送信先: {account.default_room_id}</div>
          )}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onUpdate(account.id, { is_active: !account.is_active })}
        >
          {account.is_active ? (
            <><XCircle className="mr-1 h-3 w-3" />無効化</>
          ) : (
            <><CheckCircle2 className="mr-1 h-3 w-3" />有効化</>
          )}
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={() => {
            if (window.confirm(`「${account.account_name}」を削除しますか？\nこのアカウントからの議事録が届かなくなります。`)) {
              onDelete(account.id);
            }
          }}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

// ===== タブ: 送信先設定 =====

function ConfigsTab() {
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

  if (isLoading) {
    return <div className="space-y-3"><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div>;
  }

  const configs = data?.configs ?? [];
  const activeCount = configs.filter((c) => c.is_active).length;

  return (
    <div className="space-y-4">
      {/* サマリー */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardContent className="p-3">
            <div className="text-2xl font-bold">{configs.length}</div>
            <div className="text-xs text-muted-foreground">設定数（合計）</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <div className="text-2xl font-bold text-green-600">{activeCount}</div>
            <div className="text-xs text-muted-foreground">有効な設定</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <div className="text-2xl font-bold text-muted-foreground">{configs.length - activeCount}</div>
            <div className="text-xs text-muted-foreground">無効な設定</div>
          </CardContent>
        </Card>
      </div>

      {/* 仕組みの説明 */}
      <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
        <CardContent className="p-4 space-y-2">
          <p className="text-sm font-medium text-blue-900 dark:text-blue-100">📋 使い方</p>
          <p className="text-xs text-blue-800 dark:text-blue-200">
            会議が終わってZoom録画が完了すると、ソウルくんが自動で議事録を作成します。
            会議名に「キーワード」が含まれていれば、設定した先のChatWorkルームに届きます。
            どの設定にも一致しない場合は、管理部ルームに届きます。
          </p>
          <p className="text-xs text-blue-700 dark:text-blue-300">
            例: キーワード「朝会」→ 会議名「2月朝会」「3月朝会MTG」などが全て対象になります
          </p>
          <div className="rounded-md border border-blue-300 bg-white/60 p-3 dark:bg-black/20">
            <p className="text-xs font-semibold text-blue-900 dark:text-blue-100">💬 ChatWorkルームIDの調べ方</p>
            <p className="mt-1 text-xs text-blue-800 dark:text-blue-200">
              議事録を送りたいChatWorkのグループチャットを開き、URLの末尾の数字をコピーしてください。
            </p>
            <p className="mt-1 text-xs font-mono text-blue-700 dark:text-blue-300">
              例: https://www.chatwork.com/#!rid<strong>417892193</strong> → ルームID は 417892193
            </p>
          </div>
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
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Video className="h-4 w-4" />
              設定一覧（{configs.length}件）
            </CardTitle>
            <Button onClick={() => refetch()} size="sm" variant="ghost">
              <RefreshCw className="h-3 w-3" />
            </Button>
          </div>
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
  );
}

// ===== タブ: アカウント管理 =====

function AccountsTab() {
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<ZoomAccountsResponse>({
    queryKey: ['zoom-accounts'],
    queryFn: () => api.zoomAccounts.getAccounts(),
    staleTime: 300000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.zoomAccounts.deleteAccount(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zoom-accounts'] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { is_active: boolean } }) =>
      api.zoomAccounts.updateAccount(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zoom-accounts'] }),
  });

  if (isLoading) {
    return <div className="space-y-3"><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div>;
  }

  const accounts = data?.accounts ?? [];
  const activeCount = accounts.filter((a) => a.is_active).length;

  return (
    <div className="space-y-4">
      {/* サマリー */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Card>
          <CardContent className="p-3">
            <div className="text-2xl font-bold">{accounts.length}</div>
            <div className="text-xs text-muted-foreground">登録アカウント数</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <div className="text-2xl font-bold text-green-600">{activeCount}</div>
            <div className="text-xs text-muted-foreground">有効なアカウント</div>
          </CardContent>
        </Card>
      </div>

      {/* 仕組みの説明 */}
      <Card className="border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950">
        <CardContent className="p-4 space-y-3">
          <p className="text-sm font-medium text-amber-900 dark:text-amber-100">
            🔑 複数Zoomアカウントの使い方
          </p>
          <p className="text-xs text-amber-800 dark:text-amber-200">
            会社で複数のZoomアカウントを使っている場合、それぞれのアカウントを登録することで
            どのアカウントで録画した会議でも、ソウルくんが議事録を作れるようになります。
          </p>
          <div className="rounded-md border border-amber-300 bg-white/60 p-3 space-y-2 dark:bg-black/20">
            <p className="text-xs font-semibold text-amber-900 dark:text-amber-100">📋 設定手順（1アカウントにつき1回）</p>
            <ol className="space-y-1.5 text-xs text-amber-800 dark:text-amber-200">
              <li className="flex items-start gap-2">
                <span className="shrink-0 rounded-full bg-amber-400 text-white w-4 h-4 flex items-center justify-center text-[10px] font-bold mt-0.5">1</span>
                <span>
                  <a
                    href="https://marketplace.zoom.us/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 font-semibold text-blue-700 underline hover:text-blue-900"
                  >
                    Zoom App Marketplace <ExternalLink className="h-3 w-3" />
                  </a>
                  {' '}にZoomアカウントでログインする
                </span>
              </li>
              <li className="flex items-start gap-2">
                <span className="shrink-0 rounded-full bg-amber-400 text-white w-4 h-4 flex items-center justify-center text-[10px] font-bold mt-0.5">2</span>
                <span>右上の「Develop」→「Build App」をクリック → 「General App」を選択して作成</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="shrink-0 rounded-full bg-amber-400 text-white w-4 h-4 flex items-center justify-center text-[10px] font-bold mt-0.5">3</span>
                <span>「App Credentials」タブを開く → <strong>Account ID</strong> をコピーして下の欄に貼り付ける</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="shrink-0 rounded-full bg-amber-400 text-white w-4 h-4 flex items-center justify-center text-[10px] font-bold mt-0.5">4</span>
                <span>「Feature」タブ → 「Event Subscriptions」を有効にする → <strong>Secret Token</strong> をコピーして下の欄に貼り付ける</span>
              </li>
            </ol>
          </div>
        </CardContent>
      </Card>

      {/* 新規追加フォーム */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Plus className="h-4 w-4" />
            アカウントを追加
          </CardTitle>
        </CardHeader>
        <CardContent>
          <AddAccountForm
            onSuccess={() => queryClient.invalidateQueries({ queryKey: ['zoom-accounts'] })}
          />
        </CardContent>
      </Card>

      {/* アカウント一覧 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Key className="h-4 w-4" />
              登録済みアカウント（{accounts.length}件）
            </CardTitle>
            <Button onClick={() => refetch()} size="sm" variant="ghost">
              <RefreshCw className="h-3 w-3" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
              アカウントの読み込みに失敗しました。再度お試しください。
            </div>
          )}
          {accounts.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              <Key className="mx-auto mb-2 h-8 w-8 opacity-30" />
              <p>まだアカウントが登録されていません</p>
              <p className="mt-1 text-xs">上のフォームからZoomアカウントを追加してください</p>
            </div>
          ) : (
            <div className="space-y-2">
              {accounts.map((account) => (
                <AccountRow
                  key={account.id}
                  account={account}
                  onDelete={(id) => deleteMutation.mutate(id)}
                  onUpdate={(id, data) => updateMutation.mutate({ id, data })}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ===== メインページ =====

export function ZoomSettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('configs');

  const tabs: { id: TabId; label: string }[] = [
    { id: 'configs', label: '送信先設定' },
    { id: 'accounts', label: 'アカウント管理' },
  ];

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ヘッダー */}
        <div>
          <h1 className="text-2xl font-bold md:text-3xl">Zoom連携設定</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Zoom録画の議事録自動生成の設定を管理します
          </p>
        </div>

        {/* タブ */}
        <div className="flex border-b">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'border-b-2 border-primary text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* タブコンテンツ */}
        {activeTab === 'configs' ? <ConfigsTab /> : <AccountsTab />}
      </div>
    </AppLayout>
  );
}
