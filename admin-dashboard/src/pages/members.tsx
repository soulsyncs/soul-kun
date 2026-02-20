/**
 * Members page
 * Displays member list with search, sort, pagination
 * Click a row to see member detail in side panel
 * Phase 3 追加: 隠れたキーマン発見タブ
 */

import { useState, useDeferredValue } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { api } from '@/lib/api';
import type { MembersListResponse, MemberDetailResponse, KeyPersonScore } from '@/types/api';
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
import { Search, ChevronLeft, ChevronRight, RefreshCw, Users, X, Star, TrendingUp, TrendingDown, Minus, Download } from 'lucide-react';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { downloadCSV } from '@/lib/utils';

const LIMIT = 20;

function TrendIcon({ trend }: { trend: string }) {
  if (trend === 'rising') return <TrendingUp className="h-3 w-3 text-green-600" />;
  if (trend === 'declining') return <TrendingDown className="h-3 w-3 text-red-500" />;
  return <Minus className="h-3 w-3 text-muted-foreground" />;
}

function KeymanRow({ person, rank }: { person: KeyPersonScore; rank: number }) {
  const scoreColor =
    person.score >= 80 ? 'text-green-600' :
    person.score >= 50 ? 'text-blue-600' :
    'text-muted-foreground';

  return (
    <TableRow>
      <TableCell className="font-bold text-lg text-muted-foreground w-12">
        {rank <= 3 ? ['🥇', '🥈', '🥉'][rank - 1] : `#${rank}`}
      </TableCell>
      <TableCell>
        <div className="font-medium">{person.name ?? '-'}</div>
        {person.department_name && (
          <div className="text-xs text-muted-foreground mt-0.5">{person.department_name}</div>
        )}
      </TableCell>
      <TableCell className="text-right">
        <span className={`text-xl font-bold ${scoreColor}`}>
          {person.score.toFixed(1)}
        </span>
        <span className="text-xs text-muted-foreground ml-0.5">pt</span>
      </TableCell>
      <TableCell className="text-right text-sm">
        {person.total_requests.toLocaleString()}回
      </TableCell>
      <TableCell className="text-right text-sm">
        {person.active_days}日
      </TableCell>
      <TableCell className="text-right text-sm">
        {person.tiers_used}種
      </TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-1">
          <TrendIcon trend={person.recent_trend} />
          <span className="text-xs text-muted-foreground">
            {person.recent_trend === 'rising' ? '増加' :
             person.recent_trend === 'declining' ? '減少' : '安定'}
          </span>
        </div>
      </TableCell>
    </TableRow>
  );
}

type TabType = 'list' | 'keymen';

export function MembersPage() {
  const [activeTab, setActiveTab] = useState<TabType>('list');
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

  const { data: keymenData, isLoading: keymenLoading, refetch: refetchKeymen } = useQuery({
    queryKey: ['members', 'keymen'],
    queryFn: () => api.members.getKeymen(),
    enabled: activeTab === 'keymen',
  });

  const totalCount = data?.total_count ?? 0;
  const page = Math.floor(offset / LIMIT) + 1;
  const totalPages = Math.max(1, Math.ceil(totalCount / LIMIT));

  const handleDownloadMembersCsv = () => {
    const rows = (data?.members ?? []).map((m) => [
      m.name ?? '',
      m.department ?? '',
      m.role ?? '',
      m.role_level ?? '',
      m.created_at ? format(parseISO(m.created_at), 'yyyy/MM/dd') : '',
    ]);
    downloadCSV(
      `members_${format(new Date(), 'yyyyMMdd')}.csv`,
      ['名前', '部署', '役職', '権限レベル', '登録日'],
      rows
    );
  };

  const handleDownloadKeymenCsv = () => {
    const rows = (keymenData?.top_keymen ?? []).map((p, i) => [
      i + 1,
      p.name ?? '',
      p.department_name ?? '',
      p.score.toFixed(1),
      p.total_requests,
      p.active_days,
      p.tiers_used,
      p.recent_trend === 'rising' ? '増加' : p.recent_trend === 'declining' ? '減少' : '安定',
    ]);
    downloadCSV(
      `keymen_ranking_${format(new Date(), 'yyyyMMdd')}.csv`,
      ['順位', '名前', '部署', 'スコア', 'リクエスト数', 'アクティブ日数', '使用機能数', '傾向'],
      rows
    );
  };

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
          <Button
            variant="outline"
            size="sm"
            onClick={() => activeTab === 'list' ? refetch() : refetchKeymen()}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            更新
          </Button>
        </div>

        {/* Tab selector */}
        <div className="flex gap-2 border-b">
          <button
            className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'list'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setActiveTab('list')}
          >
            <Users className="h-4 w-4 inline mr-1" />
            メンバー一覧
          </button>
          <button
            className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'keymen'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setActiveTab('keymen')}
          >
            <Star className="h-4 w-4 inline mr-1" />
            隠れたキーマン発見
            <InfoTooltip text="AI活用ログから組織の鍵となる人物をスコアリング。AIによる推定値です" />
          </button>
        </div>

        {/* ===== Tab: メンバー一覧 ===== */}
        {activeTab === 'list' && (
          <>
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

            <div className="flex flex-col md:flex-row gap-4">
              {/* Members Table */}
              <Card className={selectedUserId ? 'flex-1' : 'w-full'}>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>
                    メンバー一覧
                    <InfoTooltip text="ソウルくんに登録されている全メンバーの一覧です。クリックで詳細を表示します" />
                  </CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleDownloadMembersCsv}
                    disabled={!data?.members.length}
                  >
                    <Download className="h-4 w-4 mr-1" />
                    CSV
                  </Button>
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
                      <div className="overflow-x-auto">
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
                      </div>

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
                <Card className="w-full md:w-[360px] md:shrink-0">
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
                          <div className="flex justify-between items-start gap-2">
                            <span className="text-muted-foreground shrink-0">メール</span>
                            <span className="font-medium text-right break-all">{detailData.email ?? '-'}</span>
                          </div>
                          <div className="flex justify-between items-start gap-2">
                            <span className="text-muted-foreground shrink-0">ChatWork ID</span>
                            <span className="font-medium text-right break-all">{detailData.chatwork_account_id ?? '-'}</span>
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
          </>
        )}

        {/* ===== Tab: 隠れたキーマン発見 ===== */}
        {activeTab === 'keymen' && (
          <Card>
            <CardHeader className="pb-3 flex flex-row items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Star className="h-4 w-4 text-yellow-500" />
                AIキーマン スコアランキング（直近90日）
                <InfoTooltip text="AI活用回数・継続日数・機能の多様性から総合スコアを算出。組織を実際に支えているキーパーソンを可視化します。AIによる推定値です" />
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={handleDownloadKeymenCsv}
                disabled={!keymenData?.top_keymen.length}
              >
                <Download className="h-4 w-4 mr-1" />
                CSV
              </Button>
            </CardHeader>
            <CardContent>
              {keymenLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : !keymenData?.top_keymen.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  AIキーマンデータがありません（AI活用ログが必要です）
                </div>
              ) : (
                <>
                  <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12">順位</TableHead>
                        <TableHead>名前 / 部署</TableHead>
                        <TableHead className="text-right">
                          スコア
                          <InfoTooltip text="AI活用回数40%・継続日数40%・機能多様性20%の重み付けで計算" />
                        </TableHead>
                        <TableHead className="text-right">AI活用数</TableHead>
                        <TableHead className="text-right">継続日数</TableHead>
                        <TableHead className="text-right">機能種類</TableHead>
                        <TableHead className="text-right">トレンド</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {keymenData.top_keymen.map((person) => (
                        <KeymanRow key={person.user_id} person={person} rank={person.rank} />
                      ))}
                    </TableBody>
                  </Table>
                  </div>

                  <div className="mt-4 p-3 bg-muted/30 rounded-lg text-xs text-muted-foreground">
                    <strong>スコアの見方：</strong>
                    80pt以上 = 組織の中核人材 / 50〜79pt = 重要貢献者 / 50pt未満 = 通常活用者。
                    集計期間: 直近{keymenData.period_days}日間。
                    トレンドは直近30日と前30日の比較（+30%以上で「増加」、-30%以上で「減少」）。
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </AppLayout>
  );
}
