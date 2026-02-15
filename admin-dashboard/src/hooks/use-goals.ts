/**
 * Goals data hooks (TanStack Query)
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useGoalsList(params?: {
  status?: string;
  department_id?: string;
  period_type?: string;
}) {
  return useQuery({
    queryKey: ['goals', 'list', params],
    queryFn: () => api.goals.getList(params),
  });
}

export function useGoalDetail(goalId: string | null) {
  return useQuery({
    queryKey: ['goals', 'detail', goalId],
    queryFn: () => api.goals.getDetail(goalId!),
    enabled: !!goalId,
  });
}

export function useGoalStats() {
  return useQuery({
    queryKey: ['goals', 'stats'],
    queryFn: () => api.goals.getStats(),
  });
}
