/**
 * Members page
 * Displays member list with search, sort, pagination
 * Click a row to see member detail in side panel
 * Uses /admin/members and /admin/members/{id}/detail
 */

import { useState, useDeferredValue } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { api } from '@/lib/api';
import type { MembersListResponse, MemberDetailResponse } from '@/types/api';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Search, ChevronLeft, ChevronRight, RefreshCw, Users, X } from 'lucide-react';
import { InfoTooltip } from '@/components/ui/info-tooltip';

const LIMIT = 20;

export function MembersPage() {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDeferredValue(search);
  const [offset, setOffset] = useState(0);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery<MembersListResponse>({
    queryKey: ['members', debouncedSearch, offset],
    queryFn: () =>
      api.members.getList({
        search: debouncedSearch || undefined,
        limit: LIMIT,
        offset,
      }),
  });

  const { data: detailData, isLoading: detailLoading } = useQuery<MemberDetailResponse>({
    queryKey: ['members', 'detail', selectedUserId],
    queryFn: () => api.members.getFullDetail(selectedUserId!),
    enabled: !!selectedUserId,
  });

  const totalCount = data?.total_count ?? 0;
  const page = Math.floor(offset / LIMIT) + 1;
  const totalPages = Math.max(1, Math.ceil(totalCount / LIMIT));

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Users className="h-6 w-6" />
              メンバー
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {totalCount}名のメンバーが登録されています
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Search */}
        <Card>
          <CardContent className="pt-6">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="名前またはメールで検索..."
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
                className="flex h-10 w-full rounded-md border border-input bg-background pl-10 pr-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
          </CardContent>
        </Card>

        <div className="flex gap-4">
          {/* Members Table */}
          <Card className={selectedUserId ? 'flex-1' : 'w-full'}>
            <CardHeader>
              <CardTitle>
                メンバー一覧
                <InfoTooltip text="ソウルくんに登録されている全メンバーの一覧です。クリックで詳細を表示します" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="flex items-center justify-center h-64">
                  <div className="animate-pulse text-muted-foreground">
                    メンバーを読み込み中...
                  </div>
                </div>
              ) : isError ? (
                <div className="flex items-center justify-center h-64">
                  <div className="text-destructive">
                    メンバーの読み込みに失敗しました。しばらくしてからお試しください。
                  </div>
                </div>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>名前</TableHead>
                        <TableHead>部署</TableHead>
                        <TableHead>役職</TableHead>
                        <TableHead className="text-right">レベル</TableHead>
                        <TableHead className="text-right">登録日</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(data?.members ?? []).map((member) => (
                        <TableRow
                          key={member.user_id}
                          className={`cursor-pointer transition-colors hover:bg-muted/50 ${
                            selectedUserId === member.user_id ? 'bg-muted/30' : ''
                          }`}
                          onClick={() => setSelectedUserId(
                            selectedUserId === member.user_id ? null : member.user_id
                          )}
                        >
                          <TableCell className="font-medium">
                            {member.name ?? '-'}
                          </TableCell>
                          <TableCell>
                            {member.department ? (
                              <Badge variant="secondary">
                                {member.department}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {member.role ?? '-'}
                          </TableCell>
                          <TableCell className="text-right">
                            {member.role_level ?? '-'}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground">
                            {member.created_at
                              ? format(
                                  parseISO(member.created_at),
                                  'yyyy/MM/dd'
                                )
                              : '-'}
                          </TableCell>
                        </TableRow>
                      ))}
                      {(data?.members ?? []).length === 0 && (
                        <TableRow>
                          <TableCell
                            colSpan={5}
                            className="text-center text-muted-foreground h-24"
                          >
                            {search
                              ? `「${search}」に一致するメンバーが見つかりません`
                              : 'メンバーが見つかりません'}
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>

                  {/* Pagination */}
                  {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-4 pt-4 border-t">
                      <p className="text-sm text-muted-foreground">
                        {offset + 1}-
                        {Math.min(offset + LIMIT, totalCount)}件目 / 全{totalCount}件
                      </p>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                          disabled={offset <= 0}
                        >
                          <ChevronLeft className="h-4 w-4" />
                          前へ
                        </Button>
                        <span className="flex items-center text-sm text-muted-foreground px-2">
                          {page} / {totalPages}
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setOffset(offset + LIMIT)}
                          disabled={page >= totalPages}
                        >
                          次へ
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          {/* Detail panel */}
          {selectedUserId && (
            <Card className="w-[360px] shrink-0">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-sm">メンバー詳細</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedUserId(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>

                {detailLoading ? (
                  <div className="space-y-3">
                    <Skeleton className="h-6 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-4 w-1/3" />
                  </div>
                ) : detailData ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-lg font-medium">{detailData.name ?? '-'}</div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {detailData.is_active ? (
                          <Badge variant="default" className="text-xs">有効</Badge>
                        ) : (
                          <Badge variant="destructive" className="text-xs">無効</Badge>
                        )}
                      </div>
                    </div>

                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">メール</span>
                        <span className="font-medium">{detailData.email ?? '-'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">ChatWork ID</span>
                        <span className="font-medium">{detailData.chatwork_account_id ?? '-'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">権限レベル</span>
                        <span className="font-medium">{detailData.role_level ?? '-'}</span>
                      </div>
                      {detailData.created_at && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">登録日</span>
                          <span className="font-medium">
                            {format(parseISO(detailData.created_at), 'yyyy/MM/dd')}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Departments */}
                    {detailData.departments.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">所属部署</h4>
                        <div className="space-y-1">
                          {detailData.departments.map((dept) => (
                            <div key={dept.department_id} className="flex items-center gap-2 text-sm">
                              <Badge variant={dept.is_primary ? 'default' : 'outline'} className="text-xs">
                                {dept.department_name}
                              </Badge>
                              {dept.role && (
                                <span className="text-xs text-muted-foreground">{dept.role}</span>
                              )}
                              {dept.is_primary && (
                                <span className="text-xs text-muted-foreground">(主)</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
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
