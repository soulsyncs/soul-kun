/**
 * 連携設定ページ
 *
 * Googleカレンダー等の外部サービス連携を管理する。
 */

import { useState } from 'react';
import { Link2, Calendar, CheckCircle, XCircle, AlertCircle, Loader2 } from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  useGoogleCalendarStatus,
  useGoogleCalendarConnect,
  useGoogleCalendarDisconnect,
} from '@/hooks/use-integrations';

export function IntegrationsPage() {
  const { data: calendarStatus, isLoading, error } = useGoogleCalendarStatus();
  const connectMutation = useGoogleCalendarConnect();
  const disconnectMutation = useGoogleCalendarDisconnect();
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false);

  // URLパラメータで接続完了を検知
  const searchParams = new URLSearchParams(window.location.search);
  const justConnected = searchParams.get('connected') === 'true';

  const handleConnect = () => {
    connectMutation.mutate();
  };

  const handleDisconnect = () => {
    disconnectMutation.mutate();
    setShowDisconnectConfirm(false);
  };

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ヘッダー */}
        <div className="flex items-center gap-3">
          <Link2 className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">連携設定</h1>
            <p className="text-muted-foreground">外部サービスとの連携を管理します</p>
          </div>
        </div>

        {/* 接続完了メッセージ */}
        {justConnected && (
          <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-4 text-green-800">
            <CheckCircle className="h-5 w-5" />
            <span>Googleカレンダーの連携が完了しました</span>
          </div>
        )}

        <Separator />

        {/* Googleカレンダー連携 */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Calendar className="h-6 w-6 text-blue-600" />
                <CardTitle>Googleカレンダー</CardTitle>
              </div>
              {calendarStatus?.is_connected ? (
                <Badge variant="default" className="bg-green-600">接続済み</Badge>
              ) : (
                <Badge variant="secondary">未接続</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Googleカレンダーを連携すると、Zoom議事録が自動で正しいChatWorkルームに配信されます。
              カレンダーの予定に <code className="rounded bg-muted px-1">CW:ルームID</code> と書くだけでOKです。
            </p>

            {isLoading ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>読み込み中...</span>
              </div>
            ) : error ? (
              <div className="flex items-center gap-2 text-red-600">
                <AlertCircle className="h-4 w-4" />
                <span>接続状態の取得に失敗しました</span>
              </div>
            ) : calendarStatus?.is_connected ? (
              /* 接続済み表示 */
              <div className="space-y-3">
                <div className="rounded-lg border bg-muted/50 p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">アカウント</span>
                    <span className="text-sm">{calendarStatus.google_email || '不明'}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">接続日</span>
                    <span className="text-sm">
                      {calendarStatus.connected_at
                        ? new Date(calendarStatus.connected_at).toLocaleDateString('ja-JP')
                        : '不明'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">トークン状態</span>
                    {calendarStatus.token_valid ? (
                      <div className="flex items-center gap-1 text-green-600">
                        <CheckCircle className="h-3 w-3" />
                        <span className="text-sm">有効</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 text-amber-600">
                        <AlertCircle className="h-3 w-3" />
                        <span className="text-sm">再接続が必要</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* トークン失効時の再接続ボタン */}
                {!calendarStatus.token_valid && (
                  <Button
                    onClick={handleConnect}
                    disabled={connectMutation.isPending}
                  >
                    {connectMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : null}
                    再接続する
                  </Button>
                )}

                {/* 接続解除 */}
                {showDisconnectConfirm ? (
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-red-600">本当に解除しますか？</span>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={handleDisconnect}
                      disabled={disconnectMutation.isPending}
                    >
                      {disconnectMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : null}
                      解除する
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setShowDisconnectConfirm(false)}
                    >
                      キャンセル
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowDisconnectConfirm(true)}
                  >
                    <XCircle className="mr-2 h-4 w-4" />
                    連携を解除
                  </Button>
                )}
              </div>
            ) : (
              /* 未接続表示 */
              <div className="space-y-3">
                <Button
                  onClick={handleConnect}
                  disabled={connectMutation.isPending}
                  className="bg-blue-600 hover:bg-blue-700"
                >
                  {connectMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Calendar className="mr-2 h-4 w-4" />
                  )}
                  Googleカレンダーを接続
                </Button>
                <p className="text-xs text-muted-foreground">
                  接続すると、ソウルくんが指定したGoogleアカウントのカレンダーを閲覧できるようになります。
                  読み取りのみで、カレンダーの内容を変更することはありません。
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
