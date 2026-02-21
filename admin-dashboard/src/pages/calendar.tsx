/**
 * 会社カレンダーページ
 *
 * ss.calendar.share@gmail.com（サービスアカウント経由）の予定を表示する。
 * 連携設定から分離した独立ページ。
 */

import { useState } from 'react';
import {
  Calendar,
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
import { useCalendarEvents } from '@/hooks/use-integrations';

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

export function CalendarPage() {
  const [eventDays, setEventDays] = useState(14);

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useCalendarEvents(eventDays);

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
          <Calendar className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">カレンダー</h1>
            <p className="text-muted-foreground">会社のGoogleカレンダーの予定を確認できます</p>
          </div>
        </div>

        {/* 会社カレンダー予定一覧 */}
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
                            <div className="mt-2 h-2 w-2 rounded-full bg-blue-500 flex-shrink-0" />
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
      </div>
    </AppLayout>
  );
}
