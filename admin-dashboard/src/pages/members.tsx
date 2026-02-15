/**
 * Members page
 * Displays member list with search, sort, pagination
 * Uses /admin/members
 */

import { useState, useDeferredValue } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { api } from '@/lib/api';
import type { MembersListResponse } from '@/types/api';
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
import { Search, ChevronLeft, ChevronRight } from 'lucide-react';
import { InfoTooltip } from '@/components/ui/info-tooltip';

const LIMIT = 20;

export function MembersPage() {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDeferredValue(search);
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError } = useQuery<MembersListResponse>({
    queryKey: ['members', debouncedSearch, offset],
    queryFn: () =>
      api.members.getList({
        search: debouncedSearch || undefined,
        limit: LIMIT,
        offset,
      }),
  });

  const totalCount = data?.total_count ?? 0;
  const page = Math.floor(offset / LIMIT) + 1;
  const totalPages = Math.max(1, Math.ceil(totalCount / LIMIT));

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold">メンバー</h1>
          <p className="text-muted-foreground">
            {totalCount}名のメンバーが登録されています
          </p>
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

        {/* Members Table */}
        <Card>
          <CardHeader>
            <CardTitle>
              メンバー一覧
              <InfoTooltip text="ソウルくんに登録されている全メンバーの一覧です。検索で絞り込みができます" />
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
                      <TableRow key={member.user_id}>
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
      </div>
    </AppLayout>
  );
}
