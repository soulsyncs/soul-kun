/**
 * 連携設定ページ
 *
 * 外部サービス（Googleカレンダー等）のOAuth連携を管理する。
 * 会社カレンダーの予定は /calendar ページで確認できます。
 */

import { useState } from 'react';
import {
  Link2,
  Calendar,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
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

        {/* ====== OAuth連携（個人カレンダー用・将来拡張用） ====== */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Calendar className="h-6 w-6 text-gray-400" />
                <div>
                  <CardTitle className="text-base">個人カレンダー連携</CardTitle>
                  <p className="text-xs text-muted-foreground mt-0.5">将来の拡張用（Googleログイン方式）</p>
                </div>
              </div>
              {calendarStatus?.is_connected ? (
                <Badge variant="default" className="bg-green-600">接続済み</Badge>
              ) : (
                <Badge variant="secondary">未接続</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
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
                </div>
                {showDisconnectConfirm ? (
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-red-600">本当に解除しますか？</span>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={handleDisconnect}
                      disabled={disconnectMutation.isPending}
                    >
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
              <div className="space-y-3">
                <Button
                  onClick={handleConnect}
                  disabled={connectMutation.isPending}
                  variant="outline"
                >
                  {connectMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Calendar className="mr-2 h-4 w-4" />
                  )}
                  個人のGoogleアカウントを接続
                </Button>
                {connectMutation.isError && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">
                    <AlertCircle className="h-4 w-4 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium">接続できませんでした</p>
                      <p className="text-xs">Google OAuth設定がサーバー側で完了していません。管理者にご連絡ください。</p>
                    </div>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  ※ 会社カレンダーは「カレンダー」メニューで確認できます。個人の予定もソウルくんに見せたい場合に使用します。
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
