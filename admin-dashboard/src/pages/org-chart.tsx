/**
 * Org Chart page
 * 3 view modes: tree, card, list
 * Department detail panel with member list
 */

import { useState } from 'react';
import {
  Network,
  LayoutGrid,
  List,
  TreePine,
  Plus,
  RefreshCw,
  Users,
} from 'lucide-react';
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

  const departments = treeData?.departments ?? [];

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

            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="mr-1 h-4 w-4" />
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
        <div className="flex gap-6">
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
            <div className="w-80 shrink-0 space-y-4">
              {/* Department detail */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">部署詳細</CardTitle>
                    {canEdit && detailData?.department && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleEditDept}
                      >
                        編集
                      </Button>
                    )}
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
                            <MemberDetail member={member} />
                          </>
                        )}
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
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
