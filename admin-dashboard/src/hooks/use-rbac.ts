/**
 * RBAC hook for role-based access control
 *
 * Level 5+: 閲覧権限（管理部/取締役）
 * Level 6:  編集権限（代表/CFO）
 */

import { useAuth } from './use-auth';

export function useRbac() {
  const { user } = useAuth();
  const roleLevel = user?.role_level ?? 0;

  return {
    /** 閲覧権限（Level 5以上） */
    canView: roleLevel >= 5,
    /** 編集権限（Level 6以上） */
    canEdit: roleLevel >= 6,
    /** 現在のロールレベル */
    roleLevel,
  };
}
