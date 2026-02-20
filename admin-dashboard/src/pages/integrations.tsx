/**
 * 連携設定ページ
 *
 * Googleカレンダー等の外部サービス連携を管理する。
 * 会社カレンダー（サービスアカウント経由）の予定一覧も表示する。
 */

import { useState } from 'react';
import {
  Link2,
  Calendar,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  MapPin,
  Clock,
  ChevronRight,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  useGoogleCalendarStatus,
  useGoogleCalendarConnect,
  useGoogleCalendarDisconnect,
  useCalendarEvents,
} from '@/hooks/use-integrations';

// 日付フォーマット用ヘルパー
function formatEventTime(startStr: string, endStr: string, allDay: boolean): string {
  if (allDay) return '終日';
  const start = new Date(startStr);
  const end = new Date(endStr);
  const startTime = start.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  const endTime = end.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  return `${startTime} 〜 ${endTime}`;
}

function isToday(dateStr: string): boolean {
  const today = new Date();
  const date = new Date(dateStr);
  return (
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  );
}

function isTomorrow(dateStr: string): boolean {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const date = new Date(dateStr);
  return (
    date.getFullYear() === tomorrow.getFullYear() &&
    date.getMonth() === tomorrow.getMonth() &&
    date.getDate() === tomorrow.getDate()
  );
}

export function IntegrationsPage() {
  const { data: calendarStatus, isLoading, error } = useGoogleCalendarStatus();
  const connectMutation = useGoogleCalendarConnect();
  const disconnectMutation = useGoogleCalendarDisconnect();
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false);
  const [eventDays, setEventDays] = useState(14);

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useCalendarEvents(eventDays);

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

  // イベントを日付ごとにグループ化
  type EventItem = NonNullable<typeof eventsData>['events'][number];
  const groupedEvents: Record<string, EventItem[]> = {};
  if (eventsData?.events) {
    for (const ev of eventsData.events) {
      const dateKey = new Date(ev.start).toLocaleDateString('ja-JP', {
        year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
      });
      if (!groupedEvents[dateKey]) groupedEvents[dateKey] = [];
      groupedEvents[dateKey].push(ev);
    }
  }

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* ヘッダー */}
        <div className="flex items-center gap-3">
          <Link2 className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">連携設定 / カレンダー</h1>
            <p className="text-muted-foreground">会社のGoogleカレンダーの予定を確認できます</p>
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

        {/* ====== 会社カレンダー予定一覧（サービスアカウント） ====== */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-3">
                <Calendar className="h-6 w-6 text-blue-600" />
                <div>
                  <CardTitle>会社カレンダー</CardTitle>
                  <p className="text-xs text-muted-foreground mt-0.5">ss.calendar.share@gmail.com</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="default" className="bg-green-600">接続済み</Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => refetchEvents()}
                  disabled={eventsLoading}
                >
                  {eventsLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : '更新'}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* 表示期間選択 */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-muted-foreground">表示期間：</span>
              {[7, 14, 30].map((d) => (
                <Button
                  key={d}
                  variant={eventDays === d ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setEventDays(d)}
                >
                  {d === 7 ? '1週間' : d === 14 ? '2週間' : '1ヶ月'}
                </Button>
              ))}
            </div>

            {eventsLoading ? (
              <div className="flex items-center justify-center py-8 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                <span>予定を読み込み中...</span>
              </div>
            ) : eventsError ? (
              <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
                <AlertCircle className="h-5 w-5 flex-shrink-0" />
                <div>
                  <p className="font-medium">カレンダーの取得に失敗しました</p>
                  <p className="text-sm">しばらく待ってから「更新」を押してください</p>
                </div>
              </div>
            ) : Object.keys(groupedEvents).length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <Calendar className="h-10 w-10 mx-auto mb-2 opacity-30" />
                <p>この期間に予定はありません</p>
              </div>
            ) : (
              <div className="space-y-4">
                {Object.entries(groupedEvents).map(([dateLabel, events]) => {
                  const firstEvent = events[0];
                  const isEventToday = isToday(firstEvent.start);
                  const isEventTomorrow = isTomorrow(firstEvent.start);

                  return (
                    <div key={dateLabel}>
                      {/* 日付ヘッダー */}
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-semibold text-foreground">{dateLabel}</span>
                        {isEventToday && (
                          <Badge className="text-xs bg-blue-600 text-white">今日</Badge>
                        )}
                        {isEventTomorrow && (
                          <Badge variant="outline" className="text-xs border-blue-400 text-blue-600">明日</Badge>
                        )}
                      </div>
                      {/* その日のイベント一覧 */}
                      <div className="space-y-2 ml-1">
                        {events.map((ev) => (
                          <div
                            key={ev.id}
                            className="flex items-start gap-3 rounded-lg border p-3 hover:bg-muted/40 transition-colors"
                          >
                            <div className="mt-0.5 h-2 w-2 rounded-full bg-blue-500 flex-shrink-0 mt-2" />
                            <div className="flex-1 min-w-0">
                              <p className="font-medium text-sm truncate">{ev.summary}</p>
                              <div className="flex items-center gap-3 mt-1 flex-wrap">
                                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                                  <Clock className="h-3 w-3" />
                                  <span>{formatEventTime(ev.start, ev.end, ev.all_day)}</span>
                                </div>
                                {ev.location && (
                                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                                    <MapPin className="h-3 w-3" />
                                    <span className="truncate max-w-[200px]">{ev.location}</span>
                                  </div>
                                )}
                              </div>
                            </div>
                            {ev.html_link && (
                              <a
                                href={ev.html_link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-muted-foreground hover:text-foreground flex-shrink-0"
                              >
                                <ChevronRight className="h-4 w-4" />
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}

                <p className="text-xs text-muted-foreground text-right">
                  全 {eventsData?.total ?? 0} 件の予定
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Separator />

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
                <p className="text-xs text-muted-foreground">
                  ※ 会社カレンダーはすでに上部で確認できます。個人の予定もソウルくんに見せたい場合に使用します。
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
