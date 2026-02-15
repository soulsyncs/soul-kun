/**
 * Department editor dialog for creating/editing departments
 */

import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useCreateDepartment,
  useUpdateDepartment,
  useDeleteDepartment,
} from '@/hooks/use-departments';
import type { DepartmentResponse } from '@/types/api';

interface DepartmentEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  department: DepartmentResponse | null;
  parentDeptId?: string | null;
}

export function DepartmentEditor({
  open,
  onOpenChange,
  department,
  parentDeptId,
}: DepartmentEditorProps) {
  const isEdit = !!department;
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [displayOrder, setDisplayOrder] = useState(0);

  const createMutation = useCreateDepartment();
  const updateMutation = useUpdateDepartment();
  const deleteMutation = useDeleteDepartment();

  useEffect(() => {
    if (department) {
      setName(department.name);
      setDescription(department.description || '');
      setDisplayOrder(department.display_order);
    } else {
      setName('');
      setDescription('');
      setDisplayOrder(0);
    }
  }, [department, open]);

  const handleSave = async () => {
    if (!name.trim()) return;

    if (isEdit && department) {
      await updateMutation.mutateAsync({
        deptId: department.id,
        data: { name: name.trim(), description: description.trim() || undefined, display_order: displayOrder },
      });
    } else {
      await createMutation.mutateAsync({
        name: name.trim(),
        parent_department_id: parentDeptId || undefined,
        description: description.trim() || undefined,
        display_order: displayOrder,
      });
    }
    onOpenChange(false);
  };

  const handleDelete = async () => {
    if (!department) return;
    if (!confirm(`部署「${department.name}」を削除しますか？`)) return;

    await deleteMutation.mutateAsync(department.id);
    onOpenChange(false);
  };

  const isPending =
    createMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? '部署を編集' : '部署を作成'}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="dept-name">部署名</Label>
            <Input
              id="dept-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例: 営業部"
              maxLength={100}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="dept-desc">説明</Label>
            <Input
              id="dept-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="任意"
              maxLength={500}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="dept-order">表示順</Label>
            <Input
              id="dept-order"
              type="number"
              min={0}
              value={displayOrder}
              onChange={(e) => setDisplayOrder(Number(e.target.value))}
            />
          </div>
        </div>

        <DialogFooter className="flex justify-between">
          {isEdit && (
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={isPending}
            >
              削除
            </Button>
          )}
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isPending}
            >
              キャンセル
            </Button>
            <Button onClick={handleSave} disabled={isPending || !name.trim()}>
              {isPending ? '保存中...' : '保存'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
