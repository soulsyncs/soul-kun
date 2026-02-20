/**
 * Org Chart page
 * 3 view modes: tree, card, list
 * Department detail panel with member list
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Network,
  LayoutGrid,
  List,
  TreePine,
  Plus,
  RefreshCw,
  Users,
  Target,
  Activity,
} from 'lucide-react';
import { api } from '@/lib/api';
import type { GoalsListResponse, EmotionTrendsResponse } from '@/types/api';
import { AppLayout } from '@/components/layout/app-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import { TreeView } from '@/components/org-chart/tree-view';
import { CardView } from '@/components/org-chart/card-view';
import { ListView } from '@/components/org-chart/list-view';
import { DepartmentEditor } from '@/components/org-chart/department-editor';
import { MemberDetail } from '@/components/org-chart/member-detail';
import { useDepartmentsTree, useDepartmentDetail } from '@/hooks/use-departments';
import { useRbac } from '@/hooks/use-rbac';
import type { DepartmentMember } from '@/types/api';

type ViewMode = 'tree' | 'card' | 'list';

export function OrgChartPage() {
  const [viewMode, setViewMode] = useState<ViewMode>('tree');
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null);
  const [selectedMember, setSelectedMember] = useState<DepartmentMember | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingDept, setEditingDept] = useState<null | 'new' | 'edit'>(null);

  const { canEdit } = useRbac();
  const { data: treeData, isLoading, refetch } = useDepartmentsTree();
  const { data: detailData, isLoading: isDetailLoading } =
    useDepartmentDetail(selectedDeptId);

  const { data: deptGoals, isLoading: isGoalsLoading } = useQuery<GoalsListResponse>({
    queryKey: ['dept-goals', selectedDeptId],
    queryFn: () => api.goals.getList({ department_id: selectedDeptId!, limit: 5 }),
    enabled: !!selectedDeptId,
  });

  const { data: deptWellness, isLoading: isWellnessLoading } = useQuery<EmotionTrendsResponse>({
    queryKey: ['dept-wellness', selectedDeptId],
    queryFn: () => api.wellness.getTrends({ department_id: selectedDeptId!, days: 14 }),
    enabled: !!selectedDeptId,
  });

  const departments = treeData?.departments ?? [];

  // Dept drilldown: goals
  const goals = deptGoals?.goals ?? [];
  const totalGoals = deptGoals?.total_count ?? 0;

  // Dept drilldown: wellness
  const wellnessTrends = deptWellness?.trends ?? [];
  const recentScore = wellnessTrends.length > 0
    ? wellnessTrends[wellnessTrends.length - 1].avg_score
    : null;
  const wellnessColor = recentScore === null
    ? 'text-muted-foreground'
    : recentScore >= 7 ? 'text-green-600'
    : recentScore >= 5 ? 'text-yellow-600'
    : 'text-red-600';
  const wellnessLabel = recentScore === null
    ? 'データなし'
    : recentScore >= 7 ? '良好'
    : recentScore >= 5 ? '注意'
    : '要対応';

  const handleCreateDept = () => {
    setEditingDept('new');
    setEditorOpen(true);
  };

  const handleEditDept = () => {
    setEditingDept('edit');
    setEditorOpen(true);
  };

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Network className="h-6 w-6" />
              組織図
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {treeData?.total_count ?? 0}部署
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* View mode toggle */}
            <div className="flex rounded-lg border bg-card p-1">
              <Button
                variant={viewMode === 'tree' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('tree')}
              >
                <TreePine className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === 'card' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('card')}
              >
                <LayoutGrid className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === 'list' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('list')}
              >
                <List className="h-4 w-4" />
              </Button>
            </div>

            <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading}>
              <RefreshCw className={`mr-1 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
              更新
            </Button>

            {canEdit && (
              <Button size="sm" onClick={handleCreateDept}>
                <Plus className="mr-1 h-4 w-4" />
                部署追加
              </Button>
            )}
          </div>
        </div>

        {/* Main content */}
        <div className="flex flex-col gap-6 md:flex-row">
          {/* Left: Department view */}
          <div className="flex-1 min-w-0">
            <Card>
              <CardContent className="p-4">
                {isLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Skeleton key={i} className="h-8 w-full" />
                    ))}
                  </div>
                ) : viewMode === 'tree' ? (
                  <TreeView
                    departments={departments}
                    selectedDeptId={selectedDeptId}
                    onSelectDepartment={setSelectedDeptId}
                  />
                ) : viewMode === 'card' ? (
                  <CardView
                    departments={departments}
                    selectedDeptId={selectedDeptId}
                    onSelectDepartment={setSelectedDeptId}
                  />
                ) : (
                  <ListView
                    departments={departments}
                    selectedDeptId={selectedDeptId}
                    onSelectDepartment={setSelectedDeptId}
                  />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right: Detail panel */}
          {selectedDeptId && (
            <>
              {/* スマホ用背景オーバーレイ */}
              <div
                className="fixed inset-0 bg-black/40 z-30 md:hidden"
                onClick={() => { setSelectedDeptId(null); setSelectedMember(null); }}
              />
              <div className="fixed bottom-0 left-0 right-0 max-h-[75vh] overflow-y-auto rounded-t-xl bg-background z-40 space-y-4 p-4 md:relative md:bottom-auto md:left-auto md:right-auto md:max-h-none md:overflow-visible md:rounded-none md:z-auto md:p-0 md:w-80 md:shrink-0">
              {/* Department detail */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">部署詳細</CardTitle>
                    <div className="flex items-center gap-2">
                      {canEdit && detailData?.department && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleEditDept}
                        >
                          編集
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={() => { setSelectedDeptId(null); setSelectedMember(null); }}
                        aria-label="閉じる"
                      >
                        ✕
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {isDetailLoading ? (
                    <div className="space-y-2">
                      <Skeleton className="h-5 w-32" />
                      <Skeleton className="h-4 w-48" />
                    </div>
                  ) : detailData?.department ? (
                    <div className="space-y-3">
                      <div>
                        <div className="font-medium">
                          {detailData.department.name}
                        </div>
                        {detailData.department.description && (
                          <p className="text-sm text-muted-foreground mt-1">
                            {detailData.department.description}
                          </p>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <Badge variant="secondary">
                          階層 {detailData.department.level}
                        </Badge>
                        <Badge
                          variant={
                            detailData.department.is_active
                              ? 'default'
                              : 'secondary'
                          }
                        >
                          {detailData.department.is_active ? '有効' : '無効'}
                        </Badge>
                      </div>
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              {/* Members list */}
              {detailData?.members && detailData.members.length > 0 && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Users className="h-4 w-4" />
                      メンバー ({detailData.members.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {detailData.members.map((member) => (
                      <div key={member.user_id}>
                        <button
                          className="w-full text-left rounded-lg p-2 hover:bg-accent transition-colors text-sm"
                          onClick={() =>
                            setSelectedMember(
                              selectedMember?.user_id === member.user_id
                                ? null
                                : member
                            )
                          }
                        >
                          <div className="font-medium">
                            {member.name || '名前未設定'}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            {member.role && <span>{member.role}</span>}
                            {member.is_primary && (
                              <Badge variant="outline" className="text-xs">
                                主所属
                              </Badge>
                            )}
                          </div>
                        </button>
                        {selectedMember?.user_id === member.user_id && (
                          <>
                            <Separator className="my-2" />
                            <MemberDetail member={member} onClose={() => setSelectedMember(null)} />
                          </>
                        )}
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Department Goals */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Target className="h-4 w-4" />
                    目標
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {isGoalsLoading ? (
                    <div className="space-y-2">
                      <Skeleton className="h-4 w-full" />
                      <Skeleton className="h-4 w-3/4" />
                    </div>
                  ) : goals.length === 0 ? (
                    <p className="text-sm text-muted-foreground">目標データなし</p>
                  ) : (
                    <div className="space-y-2">
                      {goals.map((goal) => (
                        <div key={goal.id}>
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="truncate text-xs flex-1">{goal.title}</span>
                            <span className="text-xs text-muted-foreground ml-2 shrink-0">
                              {goal.progress_pct != null ? `${Math.round(goal.progress_pct)}%` : '—'}
                            </span>
                          </div>
                          <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                goal.status === 'completed' ? 'bg-green-500' :
                                goal.status === 'overdue' ? 'bg-red-500' :
                                'bg-primary'
                              }`}
                              style={{ width: `${Math.min(goal.progress_pct ?? 0, 100)}%` }}
                            />
                          </div>
                        </div>
                      ))}
                      {totalGoals > 5 && (
                        <p className="text-xs text-muted-foreground mt-1">
                          他 {totalGoals - 5}件の目標があります
                        </p>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Department Wellness */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Activity className="h-4 w-4" />
                    ウェルネス（直近14日）
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {isWellnessLoading ? (
                    <Skeleton className="h-8 w-24" />
                  ) : wellnessTrends.length === 0 ? (
                    <p className="text-sm text-muted-foreground">データなし</p>
                  ) : (
                    <div>
                      <div className={`text-2xl font-bold ${wellnessColor}`}>
                        {recentScore != null ? recentScore.toFixed(1) : '—'}
                        <span className="text-sm font-normal text-muted-foreground ml-1">/ 10</span>
                      </div>
                      <div className={`text-sm font-medium ${wellnessColor}`}>{wellnessLabel}</div>
                      {/* Mini bar chart: last 7 days */}
                      <div className="flex items-end gap-0.5 mt-2 h-8">
                        {wellnessTrends.slice(-7).map((entry) => (
                          <div
                            key={entry.date}
                            className={`flex-1 rounded-sm ${
                              entry.avg_score >= 7 ? 'bg-green-400' :
                              entry.avg_score >= 5 ? 'bg-yellow-400' :
                              'bg-red-400'
                            }`}
                            style={{ height: `${Math.max((entry.avg_score / 10) * 100, 10)}%` }}
                          />
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">直近7日の推移</p>
                    </div>
                  )}
                </CardContent>
              </Card>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Department editor dialog */}
      <DepartmentEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        department={
          editingDept === 'edit' ? detailData?.department ?? null : null
        }
        parentDeptId={editingDept === 'new' ? selectedDeptId : undefined}
      />
    </AppLayout>
  );
}
