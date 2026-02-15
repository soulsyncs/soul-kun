/**
 * Meetings page
 * Shows meeting list with transcript/recording indicators
 */

import { Video, RefreshCw, Clock, FileText, Mic } from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useMeetingsList } from '@/hooks/use-meetings';

function formatDuration(seconds: number | null): string {
  if (!seconds) return '-';
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}分`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}時間${mins % 60}分`;
}

export function MeetingsPage() {
  const { data, isLoading, refetch } = useMeetingsList();

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Video className="h-6 w-6" />
              ミーティング
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {data?.total_count ?? 0}件のミーティング
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Meeting list */}
        <Card>
          <CardContent className="p-4">
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            ) : !data?.meetings.length ? (
              <div className="text-center py-8 text-muted-foreground">
                ミーティングがありません
              </div>
            ) : (
              <div className="space-y-2">
                {data.meetings.map((meeting) => (
                  <div
                    key={meeting.id}
                    className="rounded-lg border p-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="font-medium text-sm">
                        {meeting.title || '無題のミーティング'}
                      </div>
                      <div className="flex items-center gap-2">
                        {meeting.has_transcript && (
                          <Badge variant="outline" className="text-xs">
                            <FileText className="mr-1 h-3 w-3" />
                            議事録
                          </Badge>
                        )}
                        {meeting.has_recording && (
                          <Badge variant="outline" className="text-xs">
                            <Mic className="mr-1 h-3 w-3" />
                            録音
                          </Badge>
                        )}
                        <Badge variant={meeting.status === 'completed' ? 'secondary' : 'default'}>
                          {meeting.status}
                        </Badge>
                      </div>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground flex gap-3">
                      <Badge variant="outline" className="text-xs">
                        {meeting.meeting_type}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {meeting.source}
                      </Badge>
                      {meeting.meeting_date && (
                        <span>{meeting.meeting_date.slice(0, 10)}</span>
                      )}
                      {meeting.duration_seconds && (
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDuration(meeting.duration_seconds)}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
