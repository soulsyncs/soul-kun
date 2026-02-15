/**
 * Card view component for org chart
 * Grid layout showing departments as cards
 */

import { Building2, Users } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { DepartmentTreeNode } from '@/types/api';

interface CardViewProps {
  departments: DepartmentTreeNode[];
  selectedDeptId: string | null;
  onSelectDepartment: (deptId: string) => void;
}

export function CardView({
  departments,
  selectedDeptId,
  onSelectDepartment,
}: CardViewProps) {
  // Flatten tree for card view
  const flatDepts = flattenTree(departments);

  if (flatDepts.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Building2 className="mr-2 h-5 w-5" />
        部署が登録されていません
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {flatDepts.map((dept) => (
        <Card
          key={dept.id}
          className={cn(
            'cursor-pointer transition-all hover:shadow-md',
            dept.id === selectedDeptId && 'ring-2 ring-primary',
            !dept.is_active && 'opacity-50'
          )}
          onClick={() => onSelectDepartment(dept.id)}
        >
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium truncate">
                {dept.name}
              </CardTitle>
              {dept.level > 0 && (
                <Badge variant="secondary" className="text-xs shrink-0 ml-2">
                  L{dept.level}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Users className="h-4 w-4" />
              <span>{dept.member_count}名</span>
            </div>
            {dept.description && (
              <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
                {dept.description}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function flattenTree(nodes: DepartmentTreeNode[]): DepartmentTreeNode[] {
  const result: DepartmentTreeNode[] = [];
  for (const node of nodes) {
    result.push(node);
    if (node.children.length > 0) {
      result.push(...flattenTree(node.children));
    }
  }
  return result;
}
