/**
 * List view component for org chart
 * Table layout with sortable columns
 */

import { useState } from 'react';
import { ArrowUpDown, Building2, Users } from 'lucide-react';
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
import { cn } from '@/lib/utils';
import type { DepartmentTreeNode } from '@/types/api';

interface ListViewProps {
  departments: DepartmentTreeNode[];
  selectedDeptId: string | null;
  onSelectDepartment: (deptId: string) => void;
}

type SortKey = 'name' | 'level' | 'member_count';

export function ListView({
  departments,
  selectedDeptId,
  onSelectDepartment,
}: ListViewProps) {
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortAsc, setSortAsc] = useState(true);

  // Flatten tree for list view
  const flatDepts = flattenTree(departments);

  const sorted = [...flatDepts].sort((a, b) => {
    const dir = sortAsc ? 1 : -1;
    if (sortKey === 'name') return a.name.localeCompare(b.name) * dir;
    if (sortKey === 'level') return (a.level - b.level) * dir;
    return (a.member_count - b.member_count) * dir;
  });

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  if (flatDepts.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Building2 className="mr-2 h-5 w-5" />
        部署が登録されていません
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toggleSort('name')}
            >
              部署名
              <ArrowUpDown className="ml-1 h-3 w-3" />
            </Button>
          </TableHead>
          <TableHead>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toggleSort('level')}
            >
              階層
              <ArrowUpDown className="ml-1 h-3 w-3" />
            </Button>
          </TableHead>
          <TableHead>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toggleSort('member_count')}
            >
              メンバー数
              <ArrowUpDown className="ml-1 h-3 w-3" />
            </Button>
          </TableHead>
          <TableHead>説明</TableHead>
          <TableHead>状態</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((dept) => (
          <TableRow
            key={dept.id}
            className={cn(
              'cursor-pointer',
              dept.id === selectedDeptId && 'bg-primary/10',
              !dept.is_active && 'opacity-50'
            )}
            onClick={() => onSelectDepartment(dept.id)}
          >
            <TableCell className="font-medium">
              <span style={{ paddingLeft: `${dept.level * 16}px` }}>
                {dept.name}
              </span>
            </TableCell>
            <TableCell>
              <Badge variant="secondary">L{dept.level}</Badge>
            </TableCell>
            <TableCell>
              <span className="flex items-center gap-1">
                <Users className="h-3 w-3 text-muted-foreground" />
                {dept.member_count}
              </span>
            </TableCell>
            <TableCell className="max-w-[200px] truncate text-muted-foreground">
              {dept.description || '—'}
            </TableCell>
            <TableCell>
              <Badge variant={dept.is_active ? 'default' : 'secondary'}>
                {dept.is_active ? '有効' : '無効'}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
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
