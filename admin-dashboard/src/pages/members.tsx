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
          <h1 className="text-3xl font-bold">Members</h1>
          <p className="text-muted-foreground">
            {totalCount} members registered
          </p>
        </div>

        {/* Search */}
        <Card>
          <CardContent className="pt-6">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search by name or email..."
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
            <CardTitle>Member List</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center h-64">
                <div className="animate-pulse text-muted-foreground">
                  Loading members...
                </div>
              </div>
            ) : isError ? (
              <div className="flex items-center justify-center h-64">
                <div className="text-destructive">
                  Failed to load members. Please try again later.
                </div>
              </div>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Department</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead className="text-right">Level</TableHead>
                      <TableHead className="text-right">Joined</TableHead>
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
                            ? `No members found for "${search}"`
                            : 'No members found'}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between mt-4 pt-4 border-t">
                    <p className="text-sm text-muted-foreground">
                      Showing {offset + 1}-
                      {Math.min(offset + LIMIT, totalCount)} of {totalCount}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                        disabled={offset <= 0}
                      >
                        <ChevronLeft className="h-4 w-4" />
                        Prev
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
                        Next
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
