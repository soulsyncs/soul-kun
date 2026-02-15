/**
 * Tree view component for org chart
 * Recursive tree with expand/collapse, member counts, and click-to-select
 */

import { useState } from 'react';
import { ChevronRight, ChevronDown, Users, Building2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { DepartmentTreeNode } from '@/types/api';

interface TreeViewProps {
  departments: DepartmentTreeNode[];
  selectedDeptId: string | null;
  onSelectDepartment: (deptId: string) => void;
}

export function TreeView({
  departments,
  selectedDeptId,
  onSelectDepartment,
}: TreeViewProps) {
  if (departments.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Building2 className="mr-2 h-5 w-5" />
        部署が登録されていません
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {departments.map((dept) => (
        <TreeNode
          key={dept.id}
          node={dept}
          selectedDeptId={selectedDeptId}
          onSelectDepartment={onSelectDepartment}
          depth={0}
        />
      ))}
    </div>
  );
}

interface TreeNodeProps {
  node: DepartmentTreeNode;
  selectedDeptId: string | null;
  onSelectDepartment: (deptId: string) => void;
  depth: number;
}

function TreeNode({
  node,
  selectedDeptId,
  onSelectDepartment,
  depth,
}: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(depth < 2);
  const hasChildren = node.children.length > 0;
  const isSelected = node.id === selectedDeptId;

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm cursor-pointer transition-colors',
          isSelected
            ? 'bg-primary text-primary-foreground'
            : 'hover:bg-accent',
          !node.is_active && 'opacity-50'
        )}
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
        onClick={() => onSelectDepartment(node.id)}
      >
        {/* Expand/collapse toggle */}
        <button
          className={cn(
            'flex h-5 w-5 items-center justify-center rounded transition-colors',
            hasChildren ? 'hover:bg-accent/50' : 'invisible'
          )}
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded(!isExpanded);
          }}
        >
          {hasChildren &&
            (isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            ))}
        </button>

        {/* Department icon */}
        <Building2
          className={cn(
            'h-4 w-4 shrink-0',
            isSelected ? 'text-primary-foreground' : 'text-muted-foreground'
          )}
        />

        {/* Department name */}
        <span className="flex-1 truncate font-medium">{node.name}</span>

        {/* Member count badge */}
        <span
          className={cn(
            'flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
            isSelected
              ? 'bg-primary-foreground/20 text-primary-foreground'
              : 'bg-muted text-muted-foreground'
          )}
        >
          <Users className="h-3 w-3" />
          {node.member_count}
        </span>
      </div>

      {/* Children */}
      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              selectedDeptId={selectedDeptId}
              onSelectDepartment={onSelectDepartment}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
