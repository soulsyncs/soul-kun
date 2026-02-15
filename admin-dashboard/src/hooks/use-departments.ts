/**
 * Department data hooks using TanStack Query
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  CreateDepartmentRequest,
  UpdateDepartmentRequest,
} from '@/types/api';

/** 部署ツリー取得 */
export function useDepartmentsTree() {
  return useQuery({
    queryKey: ['departments', 'tree'],
    queryFn: () => api.departments.getTree(),
  });
}

/** 部署詳細取得 */
export function useDepartmentDetail(deptId: string | null) {
  return useQuery({
    queryKey: ['departments', 'detail', deptId],
    queryFn: () => api.departments.getDetail(deptId!),
    enabled: !!deptId,
  });
}

/** メンバー詳細取得 */
export function useMemberDetail(userId: string | null) {
  return useQuery({
    queryKey: ['members', 'detail', userId],
    queryFn: () => api.members.getFullDetail(userId!),
    enabled: !!userId,
  });
}

/** 部署作成 */
export function useCreateDepartment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateDepartmentRequest) => api.departments.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
}

/** 部署更新 */
export function useUpdateDepartment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ deptId, data }: { deptId: string; data: UpdateDepartmentRequest }) =>
      api.departments.update(deptId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
}

/** 部署削除 */
export function useDeleteDepartment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deptId: string) => api.departments.delete(deptId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
}

/** メンバー情報更新 */
export function useUpdateMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: Parameters<typeof api.members.update>[1] }) =>
      api.members.update(userId, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['members', 'detail', variables.userId] });
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
}

/** メンバー所属部署更新 */
export function useUpdateMemberDepartments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: Parameters<typeof api.members.updateDepartments>[1] }) =>
      api.members.updateDepartments(userId, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['members', 'detail', variables.userId] });
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
}
