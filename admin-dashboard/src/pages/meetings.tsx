/**
 * Meetings page
 * Shows meeting list with transcript/recording indicators
 * Clicking transcript badge opens detail modal
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Video, RefreshCw, Clock, FileText, Mic, X } from 'lucide-react';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useMeetingsList } from '@/hooks/use-meetings';
import { api } from '@/lib/api';
import type { MeetingDetailResponse } from '@/types/api';

function formatDuration(seconds: number | null): string {
  if (!seconds) return '-';
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}分`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}時間${mins % 60}分`;
}

export function MeetingsPage() {
  const { data, isLoading, refetch } = useMeetingsList();
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);

  const { data: detailData, isLoading: detailLoading } = useQuery<MeetingDetailResponse>({
    queryKey: ['meetings', 'detail', selectedMeetingId],
    queryFn: () => api.meetings.getDetail(selectedMeetingId!),
    enabled: !!selectedMeetingId,
  });

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

        <div className="flex gap-4">
          {/* Meeting list */}
          <Card className={selectedMeetingId ? 'flex-1' : 'w-full'}>
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
                      className={`rounded-lg border p-3 cursor-pointer transition-colors hover:bg-muted/50 ${
                        selectedMeetingId === meeting.id ? 'ring-2 ring-primary bg-muted/30' : ''
                      }`}
                      onClick={() => setSelectedMeetingId(
                        selectedMeetingId === meeting.id ? null : meeting.id
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <div className="font-medium text-sm">
                          {meeting.title || '無題のミーティング'}
                        </div>
                        <div className="flex items-center gap-2">
                          {meeting.has_transcript && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 text-xs px-2"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedMeetingId(meeting.id);
                              }}
                            >
                              <FileText className="mr-1 h-3 w-3" />
                              議事録
                            </Button>
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
                        {meeting.source && meeting.source !== meeting.meeting_type && (
                          <Badge variant="outline" className="text-xs">
                            {meeting.source}
                          </Badge>
                        )}
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

          {/* Detail panel */}
          {selectedMeetingId && (
            <Card className="w-[480px] shrink-0">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-sm">ミーティング詳細</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedMeetingId(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>

                {detailLoading ? (
                  <div className="space-y-3">
                    <Skeleton className="h-6 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                    <Skeleton className="h-40 w-full" />
                  </div>
                ) : detailData ? (
                  <div className="space-y-4">
                    <div>
                      <div className="font-medium">
                        {detailData.meeting.title || '無題のミーティング'}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1 flex gap-2">
                        <Badge variant="outline">{detailData.meeting.meeting_type}</Badge>
                        {detailData.meeting.source && detailData.meeting.source !== detailData.meeting.meeting_type && (
                          <Badge variant="outline">{detailData.meeting.source}</Badge>
                        )}
                        {detailData.meeting.meeting_date && (
                          <span>{detailData.meeting.meeting_date.slice(0, 10)}</span>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-2 flex items-center gap-1">
                        <FileText className="h-4 w-4" />
                        議事録
                      </h4>
                      {detailData.transcript ? (
                        <div className="rounded border p-3 text-sm whitespace-pre-wrap max-h-[500px] overflow-y-auto bg-muted/30">
                          {detailData.transcript}
                        </div>
                      ) : (
                        <div className="text-sm text-muted-foreground">
                          議事録はありません
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
